"""Reducer diagnostics for orchestrator lifecycle transitions."""

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional


class TaskLifecycleReducer:
    """Guards task lifecycle transitions and stores sanitized failures."""

    _ALLOWED_TRANSITIONS = {
        "pending": {"running"},
        "running": {"completed", "failed"},
        "completed": set(),
        "failed": set(),
    }

    def __init__(self):
        self._states: Dict[str, str] = {}
        self._revisions: Dict[str, int] = {}
        self._errors: List[Dict[str, Any]] = []

    def reduce(
        self,
        task: Dict[str, Any],
        next_state: str,
        *,
        attempt: Optional[int] = None,
        revision: Optional[int] = None,
        reason: str = "",
    ) -> bool:
        task_id = task.get("id")
        if not task_id:
            self._record_error(
                task_id="unknown",
                code="missing_task_id",
                current_state="unknown",
                next_state=next_state,
                attempt=attempt,
                revision=revision,
                reason=reason,
            )
            return False

        current_state = self._states.get(task_id, "pending")
        current_revision = self._revisions.get(task_id, 0)
        expected_attempt = task.get("retries", 0)
        expected_revision = current_revision + 1
        actual_attempt = expected_attempt if attempt is None else attempt
        actual_revision = expected_revision if revision is None else revision

        if actual_attempt != expected_attempt:
            self._record_error(
                task_id=task_id,
                code="stale_attempt",
                current_state=current_state,
                next_state=next_state,
                attempt=actual_attempt,
                revision=actual_revision,
                reason=reason,
            )
            return False

        if actual_revision != expected_revision:
            self._record_error(
                task_id=task_id,
                code="stale_revision",
                current_state=current_state,
                next_state=next_state,
                attempt=actual_attempt,
                revision=actual_revision,
                reason=reason,
            )
            return False

        if next_state == current_state:
            self._record_error(
                task_id=task_id,
                code="duplicate_transition",
                current_state=current_state,
                next_state=next_state,
                attempt=actual_attempt,
                revision=actual_revision,
                reason=reason,
            )
            return False

        allowed = self._ALLOWED_TRANSITIONS.get(current_state, set())
        if next_state not in allowed:
            self._record_error(
                task_id=task_id,
                code="invalid_lifecycle_transition",
                current_state=current_state,
                next_state=next_state,
                attempt=actual_attempt,
                revision=actual_revision,
                reason=reason,
            )
            return False

        self._states[task_id] = next_state
        self._revisions[task_id] = actual_revision
        return True

    def state_for(self, task_id: str) -> str:
        return self._states.get(task_id, "pending")

    def revision_for(self, task_id: str) -> int:
        return self._revisions.get(task_id, 0)

    def errors(self) -> List[Dict[str, Any]]:
        return deepcopy(self._errors)

    def _record_error(
        self,
        *,
        task_id: str,
        code: str,
        current_state: str,
        next_state: str,
        attempt: Optional[int],
        revision: Optional[int],
        reason: str,
    ) -> None:
        self._errors.append(
            {
                "task_id": task_id,
                "code": code,
                "current_state": current_state,
                "next_state": next_state,
                "attempt": attempt,
                "revision": revision,
                "reason": reason[:120],
                "recorded_at": time.time(),
            }
        )
