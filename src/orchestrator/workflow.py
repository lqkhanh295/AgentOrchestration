"""Workflow Manager — Defines and executes multi-step agent workflows."""

import hashlib
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        compensate: Optional[Callable] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.compensate = compensate  # Compensation (rollback) action
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


# ---------------------------------------------------------------------------
# Blob store with content-digest-based deduplication (issue #3567)
# ---------------------------------------------------------------------------

class DigestMismatchError(ValueError):
    """Raised when a stored blob's digest does not match the provided content.

    This closes the window between metadata creation and content verification:
    deduplication decisions are only made after the digest is confirmed, so
    distinct blobs cannot be silently aliased to each other.
    """


class BlobStore:
    """Content-addressed artifact store.

    Deduplication is based exclusively on verified SHA-256 content digests
    (issue #3567).  Logical artifact names are used as labels only; the
    immutable blob reference (digest) is always computed and stored first
    before any deduplication decision is made.
    """

    def __init__(self):
        # digest → blob_content mapping (immutable after first write)
        self._blobs: Dict[str, bytes] = {}
        # logical_name → digest mapping (mutable; tracks latest upload per name)
        self._name_to_digest: Dict[str, str] = {}

    @staticmethod
    def compute_digest(content: bytes) -> str:
        """Return the hex-encoded SHA-256 digest of *content*."""
        return hashlib.sha256(content).hexdigest()

    def put(self, name: str, content: bytes) -> str:
        """Store *content* under logical *name* and return the content digest.

        Steps:
        1. Compute digest **before** any deduplication check.
        2. If the digest is new, store the blob.
        3. If the digest already exists, verify the stored content matches —
           raising :class:`DigestMismatchError` on collision.
        4. Update the name → digest mapping after the blob is confirmed.

        This ensures the deduplication key is always the verified digest, not
        the logical name (issue #3567).
        """
        digest = self.compute_digest(content)

        if digest in self._blobs:
            # Verify content identity (guard against SHA-256 pre-image attacks
            # or internal corruption)
            if self._blobs[digest] != content:
                raise DigestMismatchError(
                    f"Content digest collision for blob {digest!r}; "
                    "stored content does not match provided content"
                )
            logger.debug("Deduplicating blob %s (name=%r)", digest[:16], name)
        else:
            # First time seeing this digest — store the blob
            self._blobs[digest] = content
            logger.debug("Stored new blob %s (name=%r)", digest[:16], name)

        # Record the immutable blob reference for this logical name
        self._name_to_digest[name] = digest
        return digest

    def get(self, name: str) -> Optional[Tuple[bytes, str]]:
        """Retrieve (content, digest) for the latest upload under *name*."""
        digest = self._name_to_digest.get(name)
        if digest is None:
            return None
        content = self._blobs.get(digest)
        if content is None:
            return None
        return content, digest

    def get_by_digest(self, digest: str) -> Optional[bytes]:
        """Retrieve blob content directly by digest."""
        return self._blobs.get(digest)


# ---------------------------------------------------------------------------
# Workflow manager with compensation engine (issue #3555)
# ---------------------------------------------------------------------------

class WorkflowManager:
    """Manages workflow lifecycle with a compensation engine.

    Enhancements (issue #3555 — compensating actions):
    * Each :class:`WorkflowStep` may declare a ``compensate`` callable.
    * When a step fails after one or more steps have already completed,
      :meth:`_run_compensations` runs the completed steps' compensation
      actions in **reverse** order (LIFO).
    * Once compensation begins, all subsequent steps are marked
      :attr:`StepStatus.BLOCKED` so they never execute.
    * Compensation errors are logged but do not mask the original failure.
    """

    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def _run_compensations(self, completed_steps: List[WorkflowStep]) -> None:
        """Run compensation actions for completed steps in reverse (LIFO) order.

        Each step's ``compensate`` callable is invoked if present.  Errors
        are caught and logged so that all compensations are attempted even
        if one fails.
        """
        for step in reversed(completed_steps):
            if step.compensate is not None:
                try:
                    step.compensate()
                    step.status = StepStatus.ROLLED_BACK
                    logger.info("Compensated step %r (%s)", step.name, step.id)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Compensation failed for step %r (%s): %s",
                        step.name,
                        step.id,
                        exc,
                    )

    def execute_workflow(self, workflow_id: str) -> bool:
        """Execute all steps in the workflow sequentially.

        On step failure:
        1. Mark the failing step as FAILED.
        2. Mark all subsequent (not-yet-started) steps as BLOCKED.
        3. Run compensations for previously completed steps in LIFO order.
        4. Mark the workflow as FAILED and return False.
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        completed_steps: List[WorkflowStep] = []

        for i, step in enumerate(workflow.steps):
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
                completed_steps.append(step)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                logger.error(
                    "Workflow %r step %r failed: %s; "
                    "blocking %d downstream step(s) and running compensations",
                    workflow.name,
                    step.name,
                    e,
                    len(workflow.steps) - i - 1,
                )

                # Block all remaining (downstream) steps (issue #3555)
                for downstream_step in workflow.steps[i + 1:]:
                    downstream_step.status = StepStatus.BLOCKED

                # Run compensations in reverse for already-completed steps
                self._run_compensations(completed_steps)

                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True


# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
