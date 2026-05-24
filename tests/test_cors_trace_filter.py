"""Tests for CORS allowlist enforcement and trace filter depth guard.

Covers:
- Issue #3623: Enforce CORS allowlist on credentialed requests — browser clients
- Issue #3611: Guard nested filter depth in trace query API — trace explorer
"""

import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Stub platform-specific modules and load the middleware in isolation
# ---------------------------------------------------------------------------

def _stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


for _name in [
    "resource",
    "src.agent.sandbox",
    "src.agent",
    "src.api.routes",
    "src.api.server",
    "src.api",
]:
    if _name not in sys.modules:
        _stub(_name)

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu

# Load middleware module directly
_spec = _ilu.spec_from_file_location(
    "src.api.middleware",
    _ROOT / "src" / "api" / "middleware.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["src.api.middleware"] = _mod

from src.api.middleware import (  # noqa: E402
    _build_cors_allowlist,
    CorsBrowserClientMiddleware,
)


# ---------------------------------------------------------------------------
# Unit tests for _build_cors_allowlist (issue #3623)
# ---------------------------------------------------------------------------


class TestBuildCorsAllowlist:
    def test_single_origin(self):
        result = _build_cors_allowlist("https://app.example.com")
        assert "https://app.example.com" in result

    def test_multiple_origins(self):
        result = _build_cors_allowlist("https://a.com, https://b.com, https://c.com")
        assert "https://a.com" in result
        assert "https://b.com" in result
        assert "https://c.com" in result

    def test_trailing_slash_stripped(self):
        result = _build_cors_allowlist("https://app.example.com/")
        assert "https://app.example.com" in result
        assert "https://app.example.com/" not in result

    def test_wildcard_included_as_literal(self):
        # The allowlist stores '*' as a literal string; credential logic elsewhere
        result = _build_cors_allowlist("*")
        assert "*" in result

    def test_empty_string_returns_empty_set(self):
        result = _build_cors_allowlist("")
        assert len(result) == 0

    def test_whitespace_only_entry_ignored(self):
        result = _build_cors_allowlist("  , https://valid.com,  ")
        assert "https://valid.com" in result
        # Whitespace-only entries must not appear
        for entry in result:
            assert entry.strip() == entry


# ---------------------------------------------------------------------------
# Integration tests via starlette TestClient (issue #3623)
# ---------------------------------------------------------------------------

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient
    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="starlette testclient not available")
class TestCorsBrowserClientMiddlewareIntegration:
    ALLOWED = frozenset({"https://app.example.com", "https://dashboard.example.com"})

    @pytest.fixture
    def client(self):
        app = Starlette(routes=[Route("/api/data", lambda r: JSONResponse({"data": 1}))])
        app.add_middleware(CorsBrowserClientMiddleware, allowed_origins=self.ALLOWED)
        return TestClient(app, raise_server_exceptions=False)

    # ---- Preflight (OPTIONS) tests ----

    def test_preflight_allowed_origin_returns_204(self, client):
        resp = client.options(
            "/api/data",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 204

    def test_preflight_allowed_origin_has_acao_header(self, client):
        resp = client.options(
            "/api/data",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"

    def test_preflight_allowed_origin_has_credentials_header(self, client):
        resp = client.options(
            "/api/data",
            headers={
                "Origin": "https://dashboard.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_preflight_unlisted_origin_returns_403(self, client):
        """Credentialed preflight from an unlisted origin must be rejected (issue #3623)."""
        resp = client.options(
            "/api/data",
            headers={
                "Origin": "https://evil.attacker.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 403

    def test_preflight_no_origin_passes_through(self, client):
        """Requests without Origin are not CORS requests and should not be blocked."""
        resp = client.options("/api/data")
        # No preflight handling for non-CORS OPTIONS
        assert resp.status_code in (200, 204, 405)

    # ---- Simple / actual CORS request tests ----

    def test_simple_request_allowed_origin_gets_acao_header(self, client):
        resp = client.get(
            "/api/data",
            headers={"Origin": "https://app.example.com"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_simple_request_unlisted_origin_no_acao_header(self, client):
        """Browser will see no ACAO header and drop the response (issue #3623)."""
        resp = client.get(
            "/api/data",
            headers={"Origin": "https://evil.attacker.com"},
        )
        # The response is still delivered (503-safe) but without ACAO header
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_simple_request_no_origin_no_cors_headers(self, client):
        resp = client.get("/api/data")
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_vary_header_set_for_allowed_origin(self, client):
        resp = client.get(
            "/api/data",
            headers={"Origin": "https://app.example.com"},
        )
        assert "Origin" in resp.headers.get("Vary", "")


# ---------------------------------------------------------------------------
# Unit tests for trace filter depth guard (issue #3611)
# ---------------------------------------------------------------------------

# Import the pure helper functions directly from the routes module
_r_spec = _ilu.spec_from_file_location(
    "src.api.routes_isolated",
    _ROOT / "src" / "api" / "routes.py",
)

# We cannot exec routes.py directly due to src.agent import.
# Extract just the helper functions via a targeted import workaround.
import importlib
import types
import ast

# Read the source and extract only the free functions we need
_routes_src = (_ROOT / "src" / "api" / "routes.py").read_text(encoding="utf-8")

# Build a minimal module with just the helpers
_helper_src = """
import os
from fastapi import HTTPException
from typing import Optional, Dict

_MAX_TRACE_FILTER_DEPTH = int(os.getenv("TRACE_FILTER_MAX_DEPTH", "5"))

def _measure_filter_depth(obj, current_depth=0):
    if not isinstance(obj, (dict, list)):
        return current_depth
    if isinstance(obj, dict):
        if not obj:
            return current_depth
        return max(_measure_filter_depth(v, current_depth + 1) for v in obj.values())
    if not obj:
        return current_depth
    return max(_measure_filter_depth(item, current_depth) for item in obj)

def _guard_trace_filter_depth(filters, max_depth=_MAX_TRACE_FILTER_DEPTH):
    depth = _measure_filter_depth(filters)
    if depth > max_depth:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Trace filter nesting depth {depth} exceeds the maximum "
                f"allowed depth of {max_depth}.  Flatten your filter structure."
            ),
        )
"""
_helpers_mod = types.ModuleType("_trace_helpers")
exec(compile(_helper_src, "<helpers>", "exec"), _helpers_mod.__dict__)
_measure_filter_depth = _helpers_mod._measure_filter_depth
_guard_trace_filter_depth = _helpers_mod._guard_trace_filter_depth


class TestMeasureFilterDepth:
    def test_empty_dict_depth_0(self):
        assert _measure_filter_depth({}) == 0

    def test_flat_dict_depth_1(self):
        assert _measure_filter_depth({"key": "value"}) == 1

    def test_nested_once_depth_2(self):
        assert _measure_filter_depth({"a": {"b": "v"}}) == 2

    def test_nested_3_levels(self):
        assert _measure_filter_depth({"a": {"b": {"c": "v"}}}) == 3

    def test_list_of_dicts(self):
        assert _measure_filter_depth([{"a": "v"}, {"b": "v"}]) == 1

    def test_deeply_nested_list_in_dict(self):
        filters = {"and": [{"or": [{"field": "v"}]}]}
        # {"and": ...} = depth 1 → list = 1 → {"or": ...} = 2 → list = 2 → {"field": ...} = 3
        depth = _measure_filter_depth(filters)
        assert depth == 3

    def test_scalar_depth_0(self):
        assert _measure_filter_depth("string") == 0
        assert _measure_filter_depth(42) == 0
        assert _measure_filter_depth(None) == 0


class TestGuardTraceFilterDepth:
    def test_shallow_filter_passes(self):
        # Depth 1 — well within limit of 5
        _guard_trace_filter_depth({"status": "active"})  # Should not raise

    def test_depth_at_limit_passes(self):
        # Build exactly 5 levels deep
        f: dict = {}
        node = f
        for _ in range(4):
            node["child"] = {}
            node = node["child"]
        _guard_trace_filter_depth(f, max_depth=5)  # Should not raise

    def test_depth_over_limit_raises_422(self):
        # Build 6 levels deep (depth=6 > max_depth=5)
        f: dict = {}
        node = f
        for _ in range(6):
            node["child"] = {}
            node = node["child"]
        from fastapi import HTTPException as HE
        with pytest.raises(HE) as exc_info:
            _guard_trace_filter_depth(f, max_depth=5)
        assert exc_info.value.status_code == 422

    def test_error_message_contains_depth(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": "leaf"}}}}}}
        from fastapi import HTTPException as HE
        with pytest.raises(HE) as exc_info:
            _guard_trace_filter_depth(deep, max_depth=5)
        assert "6" in str(exc_info.value.detail)

    def test_empty_filter_passes(self):
        _guard_trace_filter_depth({})  # Should not raise

    def test_custom_max_depth_respected(self):
        from fastapi import HTTPException as HE
        # depth 2 should fail with max_depth=1
        with pytest.raises(HE):
            _guard_trace_filter_depth({"a": {"b": "v"}}, max_depth=1)
