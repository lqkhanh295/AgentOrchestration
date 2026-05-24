"""Tests for request ID propagation and policy engine fail-closed guard.

Covers:
- Issue #3601: Enforce same request ID on background task logs — observability
- Issue #3592: Fail closed when policy engine is unavailable — policy runtime
"""

import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Isolate the middleware module (avoid platform-specific transitive imports)
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

_spec = _ilu.spec_from_file_location(
    "src.api.middleware",
    _ROOT / "src" / "api" / "middleware.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["src.api.middleware"] = _mod

from src.api.middleware import (  # noqa: E402
    _request_id_ctx,
    get_current_request_id,
    check_policy_engine_available,
    PolicyEngineUnavailableError,
    RequestIdMiddleware,
    AuthMiddleware,
)


# ---------------------------------------------------------------------------
# Tests for request ID context var (issue #3601)
# ---------------------------------------------------------------------------


class TestRequestIdContext:
    def test_default_is_empty_string(self):
        assert get_current_request_id() == ""

    def test_set_and_get(self):
        token = _request_id_ctx.set("test-request-1")
        try:
            assert get_current_request_id() == "test-request-1"
        finally:
            _request_id_ctx.reset(token)

    def test_background_task_inherits_request_id(self):
        """Background tasks created with create_task must inherit the request ID."""
        inherited = []

        async def _run():
            token = _request_id_ctx.set("req-abc-123")
            try:
                async def _bg():
                    inherited.append(get_current_request_id())

                task = asyncio.create_task(_bg())
                await task
            finally:
                _request_id_ctx.reset(token)

        asyncio.run(_run())
        assert inherited == ["req-abc-123"], (
            "Background task must inherit the parent context's request ID"
        )

    def test_reset_clears_value(self):
        token = _request_id_ctx.set("to-be-cleared")
        _request_id_ctx.reset(token)
        assert get_current_request_id() == ""

    def test_contexts_are_isolated(self):
        """Two concurrent tasks must not share request IDs."""
        results = {}

        async def _run():
            async def _task(rid: str):
                tok = _request_id_ctx.set(rid)
                try:
                    await asyncio.sleep(0)  # yield
                    results[rid] = get_current_request_id()
                finally:
                    _request_id_ctx.reset(tok)

            await asyncio.gather(_task("id-A"), _task("id-B"))

        asyncio.run(_run())
        assert results.get("id-A") == "id-A"
        assert results.get("id-B") == "id-B"


# ---------------------------------------------------------------------------
# Integration tests for RequestIdMiddleware (issue #3601)
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
class TestRequestIdMiddlewareIntegration:
    @pytest.fixture
    def client(self):
        def home(request):
            return JSONResponse({"rid": get_current_request_id()})

        app = Starlette(routes=[Route("/", home)])
        app.add_middleware(RequestIdMiddleware)
        return TestClient(app, raise_server_exceptions=False)

    def test_generated_request_id_returned_in_header(self, client):
        resp = client.get("/")
        assert "X-Request-ID" in resp.headers
        # Should be a UUID4
        rid = resp.headers["X-Request-ID"]
        assert len(rid) == 36  # len of "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

    def test_client_supplied_request_id_echoed_back(self, client):
        resp = client.get("/", headers={"X-Request-ID": "my-custom-id-42"})
        assert resp.headers["X-Request-ID"] == "my-custom-id-42"

    def test_request_id_available_inside_handler(self, client):
        resp = client.get("/", headers={"X-Request-ID": "handler-check"})
        body = resp.json()
        assert body["rid"] == "handler-check"

    def test_different_requests_get_different_ids(self, client):
        rid1 = client.get("/").headers["X-Request-ID"]
        rid2 = client.get("/").headers["X-Request-ID"]
        assert rid1 != rid2


# ---------------------------------------------------------------------------
# Tests for policy engine fail-closed (issue #3592)
# ---------------------------------------------------------------------------


class TestCheckPolicyEngineAvailable:
    def test_no_client_does_not_raise(self):
        # When no policy client is configured, pass through
        check_policy_engine_available(None)  # Should not raise

    def test_available_engine_does_not_raise(self):
        class FakeClient:
            def is_available(self):
                return True

        check_policy_engine_available(FakeClient())  # Should not raise

    def test_unavailable_engine_raises(self):
        class FakeClient:
            def is_available(self):
                return False

        with pytest.raises(PolicyEngineUnavailableError):
            check_policy_engine_available(FakeClient())

    def test_exception_in_engine_raises_fail_closed(self):
        """Any exception from the policy client must be treated as unavailable."""
        class FlakyClient:
            def is_available(self):
                raise ConnectionError("policy engine unreachable")

        with pytest.raises(PolicyEngineUnavailableError) as exc_info:
            check_policy_engine_available(FlakyClient())

        assert "fail-closed" in str(exc_info.value).lower()

    def test_exception_is_chained(self):
        """The original exception must be chained for debugging."""
        class FlakyClient:
            def is_available(self):
                raise TimeoutError("timeout")

        with pytest.raises(PolicyEngineUnavailableError) as exc_info:
            check_policy_engine_available(FlakyClient())

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, TimeoutError)

    def test_policy_unavailable_error_is_runtime_error(self):
        assert issubclass(PolicyEngineUnavailableError, RuntimeError)
