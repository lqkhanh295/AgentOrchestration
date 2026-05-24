"""Tests for BlobStore (content-digest deduplication) and WorkflowManager compensation engine.

Covers:
- Issue #3567: Record content digest before artifact deduplication — blob store
- Issue #3555: Block downstream after partial rollback — compensating actions
"""

import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Load the workflow module in isolation
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "src.orchestrator.workflow",
    _ROOT / "src" / "orchestrator" / "workflow.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["src.orchestrator.workflow"] = _mod

from src.orchestrator.workflow import (  # noqa: E402
    BlobStore,
    DigestMismatchError,
    WorkflowManager,
    WorkflowStep,
    StepStatus,
)

import hashlib


# ---------------------------------------------------------------------------
# Tests for BlobStore (issue #3567)
# ---------------------------------------------------------------------------


class TestBlobStoreComputeDigest:
    def test_returns_sha256_hex(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        assert BlobStore.compute_digest(content) == expected

    def test_different_content_different_digest(self):
        d1 = BlobStore.compute_digest(b"content-A")
        d2 = BlobStore.compute_digest(b"content-B")
        assert d1 != d2

    def test_same_content_same_digest(self):
        assert BlobStore.compute_digest(b"abc") == BlobStore.compute_digest(b"abc")


class TestBlobStorePut:
    def test_put_returns_digest(self):
        store = BlobStore()
        digest = store.put("artifact.bin", b"data")
        assert digest == BlobStore.compute_digest(b"data")

    def test_put_same_content_twice_deduplicates(self):
        store = BlobStore()
        d1 = store.put("a.bin", b"same content")
        d2 = store.put("b.bin", b"same content")
        assert d1 == d2  # Same digest

    def test_deduplication_uses_content_not_name(self):
        """Same logical name with different content must produce different blobs."""
        store = BlobStore()
        d1 = store.put("artifact.bin", b"version-1")
        d2 = store.put("artifact.bin", b"version-2")
        assert d1 != d2, (
            "Different content must produce different digests "
            "(deduplication must be content-based, not name-based)"
        )

    def test_put_stores_immutable_blob(self):
        store = BlobStore()
        content = b"important data"
        digest = store.put("file.bin", content)
        retrieved = store.get_by_digest(digest)
        assert retrieved == content


class TestBlobStoreGet:
    def test_get_existing_blob(self):
        store = BlobStore()
        store.put("report.csv", b"col1,col2\n1,2")
        result = store.get("report.csv")
        assert result is not None
        content, digest = result
        assert content == b"col1,col2\n1,2"
        assert digest == BlobStore.compute_digest(b"col1,col2\n1,2")

    def test_get_missing_name_returns_none(self):
        store = BlobStore()
        assert store.get("nonexistent.bin") is None

    def test_get_by_digest_existing(self):
        store = BlobStore()
        store.put("x.bin", b"payload")
        d = BlobStore.compute_digest(b"payload")
        assert store.get_by_digest(d) == b"payload"

    def test_get_by_digest_missing(self):
        store = BlobStore()
        assert store.get_by_digest("0" * 64) is None

    def test_name_tracking_updated_on_overwrite(self):
        """Latest upload should be returned for a given name."""
        store = BlobStore()
        store.put("model.pt", b"v1")
        store.put("model.pt", b"v2")
        result = store.get("model.pt")
        assert result is not None
        content, _ = result
        assert content == b"v2"


class TestBlobStoreDeduplicationIntegrity:
    def test_digest_is_computed_before_deduplication_decision(self):
        """Deduplication key must be the verified digest, not the logical name."""
        store = BlobStore()
        content_a = b"artifact-version-A"
        content_b = b"artifact-version-B"

        # Upload same-name artifacts with different content
        d_a = store.put("build.tar.gz", content_a)
        d_b = store.put("build.tar.gz", content_b)

        assert d_a != d_b
        # Both blobs must be independently retrievable by digest
        assert store.get_by_digest(d_a) == content_a
        assert store.get_by_digest(d_b) == content_b


# ---------------------------------------------------------------------------
# Tests for WorkflowManager compensation engine (issue #3555)
# ---------------------------------------------------------------------------


class TestWorkflowCompensation:
    def _make_step(self, name: str, fail: bool = False, compensate_log: list = None):
        comp_log = compensate_log if compensate_log is not None else []
        def handler():
            if fail:
                raise RuntimeError(f"Step {name!r} failed deliberately")
            return f"{name}-result"
        def compensate():
            comp_log.append(name)
        step = WorkflowStep(name=name, handler=handler, compensate=compensate)
        step._comp_log = comp_log
        return step

    def test_successful_workflow_all_completed(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step-1", lambda: "ok-1"))
        wf.add_step(WorkflowStep("step-2", lambda: "ok-2"))
        assert mgr.execute_workflow(wf.id) is True
        assert wf.status == StepStatus.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in wf.steps)

    def test_failed_step_blocks_downstream(self):
        """After step-2 fails, step-3 must be BLOCKED, not PENDING or executed."""
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step-1", lambda: "ok"))
        wf.add_step(WorkflowStep("step-2", handler=lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
        wf.add_step(WorkflowStep("step-3", lambda: "should-not-run"))

        result = mgr.execute_workflow(wf.id)

        assert result is False
        assert wf.status == StepStatus.FAILED
        assert wf.steps[1].status == StepStatus.FAILED
        assert wf.steps[2].status == StepStatus.BLOCKED, (
            "Downstream steps must be BLOCKED after partial rollback (issue #3555)"
        )

    def test_compensations_run_in_lifo_order(self):
        """Compensation actions must run in reverse (LIFO) order."""
        comp_log = []
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")

        def make_handler(name):
            def handler():
                return f"{name}-done"
            return handler

        def make_compensate(name):
            def compensate():
                comp_log.append(name)
            return compensate

        wf.add_step(WorkflowStep("A", make_handler("A"), compensate=make_compensate("A")))
        wf.add_step(WorkflowStep("B", make_handler("B"), compensate=make_compensate("B")))
        wf.add_step(WorkflowStep("C", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                                  compensate=make_compensate("C")))

        mgr.execute_workflow(wf.id)

        # C failed (never completed), B and A completed → compensations B then A
        assert comp_log == ["B", "A"], (
            f"Expected LIFO order ['B', 'A'], got {comp_log}"
        )

    def test_steps_without_compensate_skipped_gracefully(self):
        """Steps without a compensate callable should not cause errors."""
        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step-1", lambda: "ok"))  # No compensate
        wf.add_step(WorkflowStep("step-2", handler=lambda: (_ for _ in ()).throw(RuntimeError("x"))))

        # Should not raise
        result = mgr.execute_workflow(wf.id)
        assert result is False
        assert wf.steps[0].status == StepStatus.COMPLETED  # No rollback possible

    def test_compensation_error_does_not_mask_original_failure(self):
        """Even if compensation raises, execute_workflow must return False."""
        def bad_compensate():
            raise RuntimeError("compensation itself failed")

        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step-1", lambda: "ok", compensate=bad_compensate))
        wf.add_step(WorkflowStep("step-2", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        result = mgr.execute_workflow(wf.id)
        assert result is False
        assert wf.status == StepStatus.FAILED

    def test_completed_steps_marked_rolled_back_after_compensation(self):
        comp_log = []
        def make_compensate(name):
            def fn():
                comp_log.append(name)
            return fn

        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-wf")
        wf.add_step(WorkflowStep("A", lambda: "done", compensate=make_compensate("A")))
        wf.add_step(WorkflowStep("B", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        mgr.execute_workflow(wf.id)

        assert wf.steps[0].status == StepStatus.ROLLED_BACK

    def test_unknown_workflow_returns_false(self):
        mgr = WorkflowManager()
        assert mgr.execute_workflow("nonexistent-id") is False
