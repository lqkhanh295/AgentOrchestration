"""Tests for auth scheme casing fix and scheduler workflow deletion race fix.

Covers:
- Issue #3616: Validate auth scheme casing consistently — bearer parsing
- Issue #3608: Prevent run creation after deletion — workflow removal race
"""

import sys
import time
import asyncio
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

# Middleware
_spec = _ilu.spec_from_file_location(
    "src.api.middleware",
    _ROOT / "src" / "api" / "middleware.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["src.api.middleware"] = _mod

# Scheduler (no problematic imports)
_s_spec = _ilu.spec_from_file_location(
    "src.orchestrator.scheduler",
    _ROOT / "src" / "orchestrator" / "scheduler.py",
)
_s_mod = _ilu.module_from_spec(_s_spec)
_s_spec.loader.exec_module(_s_mod)
sys.modules["src.orchestrator.scheduler"] = _s_mod

from src.api.middleware import _parse_bearer_token, AuthMiddleware  # noqa: E402
from src.orchestrator.scheduler import (  # noqa: E402
    TaskScheduler,
    WorkflowDeletedError,
)


# ---------------------------------------------------------------------------
# Tests for _parse_bearer_token (issue #3616)
# ---------------------------------------------------------------------------


class TestParseBearerToken:
    def test_standard_bearer_extracted(self):
        assert _parse_bearer_token("Bearer my-token-123") == "my-token-123"

    def test_lowercase_bearer_accepted(self):
        """RFC 6750 §2.1: scheme name is case-insensitive (issue #3616)."""
        assert _parse_bearer_token("bearer my-token-123") == "my-token-123"

    def test_uppercase_bearer_accepted(self):
        assert _parse_bearer_token("BEARER my-token-123") == "my-token-123"

    def test_mixed_case_bearer_accepted(self):
        assert _parse_bearer_token("BeArEr my-token-123") == "my-token-123"

    def test_basic_scheme_rejected(self):
        assert _parse_bearer_token("Basic dXNlcjpwYXNz") is None

    def test_empty_header_returns_none(self):
        assert _parse_bearer_token("") is None

    def test_missing_header_returns_none(self):
        assert _parse_bearer_token(None) is None

    def test_scheme_only_returns_none(self):
        """A header with only a scheme and no token is invalid."""
        assert _parse_bearer_token("Bearer") is None

    def test_extra_whitespace_handled(self):
        # split(None, 1) collapses any whitespace run
        result = _parse_bearer_token("Bearer  my-token")
        # "  my-token" has a leading space — callers validate the token itself
        assert result is not None and "my-token" in result

    def test_token_with_dots_preserved(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ3b3JrZXIifQ.sig"
        assert _parse_bearer_token(f"Bearer {jwt}") == jwt


# ---------------------------------------------------------------------------
# Integration tests via starlette TestClient (issue #3616)
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
class TestAuthMiddlewareBearerCasing:
    @pytest.fixture
    def client(self):
        app = Starlette(routes=[
            Route("/api/v2/auth/token", lambda r: JSONResponse({"t": 1})),
            Route("/api/v2/secure", lambda r: JSONResponse({"data": "ok"})),
        ])
        app.add_middleware(AuthMiddleware)
        return TestClient(app, raise_server_exceptions=False)

    def test_bearer_standard_case_accepted(self, client):
        resp = client.get("/api/v2/secure", headers={"Authorization": "Bearer token123"})
        assert resp.status_code == 200

    def test_bearer_lowercase_accepted(self, client):
        """Lowercase 'bearer' must not bypass or be rejected (issue #3616)."""
        resp = client.get("/api/v2/secure", headers={"Authorization": "bearer token123"})
        assert resp.status_code == 200

    def test_bearer_uppercase_accepted(self, client):
        resp = client.get("/api/v2/secure", headers={"Authorization": "BEARER token123"})
        assert resp.status_code == 200

    def test_basic_scheme_rejected(self, client):
        resp = client.get("/api/v2/secure", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_missing_auth_rejected(self, client):
        resp = client.get("/api/v2/secure")
        assert resp.status_code == 401

    def test_public_token_endpoint_no_auth(self, client):
        resp = client.get("/api/v2/auth/token")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests for TaskScheduler deletion guard (issue #3608)
# ---------------------------------------------------------------------------


class TestWorkflowDeletedError:
    def test_is_runtime_error(self):
        assert issubclass(WorkflowDeletedError, RuntimeError)


class TestTaskSchedulerDeletionGuard:
    def test_enqueue_without_workflow_id_succeeds(self):
        sched = TaskScheduler()
        task = {"name": "task1"}
        task_id = sched.enqueue(task)
        assert task_id is not None

    def test_enqueue_undeleted_workflow_succeeds(self):
        sched = TaskScheduler()
        task = {"name": "task1", "workflow_id": "wf-001"}
        task_id = sched.enqueue(task)
        assert task_id is not None

    def test_enqueue_deleted_workflow_raises(self):
        """Enqueue must raise WorkflowDeletedError after mark_workflow_deleted."""
        sched = TaskScheduler()
        sched.mark_workflow_deleted("wf-deleted")
        with pytest.raises(WorkflowDeletedError):
            sched.enqueue({"name": "late-task", "workflow_id": "wf-deleted"})

    def test_schedule_deleted_workflow_raises(self):
        """schedule() must also block new runs for deleted workflows."""
        sched = TaskScheduler()
        sched.mark_workflow_deleted("wf-deleted")
        with pytest.raises(WorkflowDeletedError):
            sched.schedule({"name": "late-delayed-task", "workflow_id": "wf-deleted"}, delay=5.0)

    def test_mark_deleted_is_idempotent(self):
        sched = TaskScheduler()
        sched.mark_workflow_deleted("wf-x")
        sched.mark_workflow_deleted("wf-x")  # Should not raise
        with pytest.raises(WorkflowDeletedError):
            sched.enqueue({"workflow_id": "wf-x"})

    def test_different_workflow_not_affected(self):
        sched = TaskScheduler()
        sched.mark_workflow_deleted("wf-deleted")
        task_id = sched.enqueue({"workflow_id": "wf-alive"})
        assert task_id is not None

    def test_error_message_contains_workflow_id(self):
        sched = TaskScheduler()
        sched.mark_workflow_deleted("wf-gone")
        with pytest.raises(WorkflowDeletedError) as exc_info:
            sched.enqueue({"workflow_id": "wf-gone"})
        assert "wf-gone" in str(exc_info.value)

    def test_existing_in_flight_tasks_unaffected(self):
        """Deletion guard should not invalidate already-running tasks."""
        sched = TaskScheduler()
        task = {"workflow_id": "wf-live"}
        task_id = sched.enqueue(task)
        # Dequeue the task so it moves to _in_flight
        dequeued = asyncio.run(sched.dequeue())
        assert dequeued is not None
        # Now delete the workflow while the task is already running
        sched.mark_workflow_deleted("wf-live")
        # In-flight tasks (already past the guard) can still be completed
        assert sched.complete(task_id) is True

    def test_normal_scheduler_operations_still_work(self):
        sched = TaskScheduler()
        task = {"workflow_id": "wf-normal"}
        task_id = sched.enqueue(task)
        result = asyncio.run(sched.dequeue())
        assert result is not None
        assert result["id"] == task_id
        assert sched.complete(task_id) is True
