"""Tests for AuthMiddleware: path normalisation and JWT nbf enforcement.

Covers:
- Issue #3537: Collapse duplicate slashes before public route matching (path middleware)
- Issue #3596: Check token not-before time on worker requests (worker auth)
"""

import base64
import importlib
import json
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so we can import src.api.middleware without triggering the
# chain src/api/__init__.py → server.py → routes.py → agent/__init__.py →
# sandbox.py → resource (Linux-only).
# ---------------------------------------------------------------------------

def _stub_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


# Stub out the problematic import chain before anything else touches it
for _name in [
    "resource",
    "src.agent.sandbox",
    "src.agent",
    "src.api.routes",
    "src.api.server",
    "src.api",
]:
    if _name not in sys.modules:
        _stub_module(_name)

# Force-load only the middleware module directly
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "src.api.middleware",
    _ROOT / "src" / "api" / "middleware.py",
)
_middleware_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_middleware_mod)
sys.modules["src.api.middleware"] = _middleware_mod

from src.api.middleware import (  # noqa: E402
    _normalize_path,
    _decode_jwt_payload,
    _check_token_nbf,
    AuthMiddleware,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestNormalizePath:
    def test_single_slash_unchanged(self):
        assert _normalize_path("/api/v2/agents") == "/api/v2/agents"

    def test_leading_double_slash_collapsed(self):
        assert _normalize_path("//api/v2/agents") == "/api/v2/agents"

    def test_triple_slash_collapsed(self):
        assert _normalize_path("///api/v2/agents") == "/api/v2/agents"

    def test_mid_path_double_slash_collapsed(self):
        assert _normalize_path("/api//v2/agents") == "/api/v2/agents"

    def test_multiple_occurrences_collapsed(self):
        assert _normalize_path("//api//v2//agents") == "/api/v2/agents"

    def test_root_path_unchanged(self):
        assert _normalize_path("/") == "/"

    def test_health_path_unchanged(self):
        assert _normalize_path("/health") == "/health"


class TestDecodeJwtPayload:
    @staticmethod
    def _make_jwt(payload: dict) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.fakesig"

    def test_valid_jwt_decoded(self):
        token = self._make_jwt({"sub": "worker-1", "nbf": 1000})
        result = _decode_jwt_payload(token)
        assert result is not None
        assert result["sub"] == "worker-1"
        assert result["nbf"] == 1000

    def test_malformed_token_returns_none(self):
        assert _decode_jwt_payload("not.a.jwt.with.too.many.parts") is None

    def test_single_part_token_returns_none(self):
        assert _decode_jwt_payload("onlyonepart") is None

    def test_non_b64_payload_returns_none(self):
        assert _decode_jwt_payload("header.!!!.sig") is None


class TestCheckTokenNbf:
    @staticmethod
    def _make_jwt(payload: dict) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.fakesig"

    def test_no_nbf_claim_allowed(self):
        token = self._make_jwt({"sub": "worker"})
        assert _check_token_nbf(token) is True

    def test_past_nbf_allowed(self):
        past = int(time.time()) - 3600  # 1 hour ago
        token = self._make_jwt({"sub": "worker", "nbf": past})
        assert _check_token_nbf(token) is True

    def test_current_nbf_allowed(self):
        # nbf exactly at current second should be valid
        now = int(time.time())
        token = self._make_jwt({"sub": "worker", "nbf": now})
        assert _check_token_nbf(token) is True

    def test_future_nbf_rejected(self):
        future = int(time.time()) + 3600  # 1 hour in the future
        token = self._make_jwt({"sub": "worker", "nbf": future})
        assert _check_token_nbf(token) is False

    def test_malformed_token_passes(self):
        # Malformed tokens pass nbf check; downstream handles them
        assert _check_token_nbf("bad-token") is True


# ---------------------------------------------------------------------------
# Integration-style tests using starlette TestClient
# ---------------------------------------------------------------------------

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    from starlette.routing import Route
    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="starlette testclient not available")
class TestAuthMiddlewareIntegration:
    @staticmethod
    def _make_jwt(payload: dict) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"{header}.{payload_b64}.fakesig"

    @pytest.fixture
    def client(self):
        def token_endpoint(request):
            return JSONResponse({"access_token": "test"})

        def secure_endpoint(request):
            return JSONResponse({"data": "secret"})

        routes = [
            Route("/api/v2/auth/token", token_endpoint),
            Route("/api/v2/secure", secure_endpoint),
        ]
        app = Starlette(routes=routes)
        app.add_middleware(AuthMiddleware)
        return TestClient(app, raise_server_exceptions=False)

    # ---- Normal auth behaviour ----

    def test_public_token_endpoint_no_auth_needed(self, client):
        resp = client.get("/api/v2/auth/token")
        assert resp.status_code == 200

    def test_protected_endpoint_with_valid_bearer_token(self, client):
        past = int(time.time()) - 60
        token = self._make_jwt({"sub": "worker", "nbf": past})
        resp = client.get("/api/v2/secure", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_protected_endpoint_missing_auth_rejected(self, client):
        resp = client.get("/api/v2/secure")
        assert resp.status_code == 401

    def test_protected_endpoint_wrong_scheme_rejected(self, client):
        resp = client.get("/api/v2/secure", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    # ---- Issue #3537: duplicate slash bypass ----

    def test_double_slash_prefix_is_blocked(self, client):
        """//api/v2/secure must not bypass authentication (issue #3537)."""
        # Without auth — must be 401, not 200
        resp = client.get("//api/v2/secure")
        assert resp.status_code in (401, 404)

    def test_double_slash_prefix_with_auth_works(self, client):
        """//api/v2/secure with valid auth should succeed (path still resolves)."""
        past = int(time.time()) - 60
        token = self._make_jwt({"sub": "worker", "nbf": past})
        resp = client.get("//api/v2/secure", headers={"Authorization": f"Bearer {token}"})
        # Either 200 (path resolved) or 404 (path not found after normalisation)
        assert resp.status_code in (200, 404)

    # ---- Issue #3596: nbf enforcement ----

    def test_future_nbf_token_rejected(self, client):
        """Tokens with future nbf must be rejected for worker requests (issue #3596)."""
        future = int(time.time()) + 3600
        token = self._make_jwt({"sub": "worker", "nbf": future})
        resp = client.get("/api/v2/secure", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_past_nbf_token_accepted(self, client):
        """Tokens with a past nbf claim should be accepted."""
        past = int(time.time()) - 3600
        token = self._make_jwt({"sub": "worker", "nbf": past})
        resp = client.get("/api/v2/secure", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_token_without_nbf_accepted(self, client):
        """Tokens without nbf claim are valid (nbf is optional per RFC 7519)."""
        token = self._make_jwt({"sub": "worker"})
        resp = client.get("/api/v2/secure", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    # ---- Non-API paths are unaffected ----

    def test_health_endpoint_no_auth(self, client):
        """Non-/api/v2 paths should not require authentication."""
        app = Starlette(routes=[Route("/health", lambda r: JSONResponse({"status": "ok"}))])
        app.add_middleware(AuthMiddleware)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/health")
        assert resp.status_code == 200
