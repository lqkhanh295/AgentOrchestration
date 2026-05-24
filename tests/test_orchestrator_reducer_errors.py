import asyncio

from src.agent import AgentStatus
from src.orchestrator.engine import OrchestrationEngine
from src.orchestrator.reducer_errors import TaskLifecycleReducer


def test_reducer_rejects_stale_revision_without_mutating_state():
    reducer = TaskLifecycleReducer()
    task = {
        "id": "task-1",
        "target_agent": "agent-1",
        "retries": 0,
        "payload": {"token": "super-secret"},
    }

    assert reducer.reduce(task, "running", revision=1)
    assert not reducer.reduce(task, "completed", revision=1)

    assert reducer.state_for("task-1") == "running"
    assert reducer.revision_for("task-1") == 1
    errors = reducer.errors()
    assert errors[-1]["code"] == "stale_revision"
    assert errors[-1]["current_state"] == "running"
    assert errors[-1]["next_state"] == "completed"
    assert "super-secret" not in str(errors)


def test_reducer_rejects_duplicate_transition_separately():
    reducer = TaskLifecycleReducer()
    task = {"id": "task-2", "target_agent": "agent-1", "retries": 0}

    assert reducer.reduce(task, "running", revision=1)
    assert not reducer.reduce(task, "running", revision=2)

    assert reducer.state_for("task-2") == "running"
    assert reducer.revision_for("task-2") == 1
    assert reducer.errors()[-1]["code"] == "duplicate_transition"


def test_reducer_rejects_stale_attempt_and_invalid_lifecycle():
    reducer = TaskLifecycleReducer()
    task = {"id": "task-attempt", "target_agent": "agent-1", "retries": 2}

    assert not reducer.reduce(task, "running", attempt=1, revision=1)
    assert reducer.state_for("task-attempt") == "pending"
    assert reducer.errors()[-1]["code"] == "stale_attempt"

    assert not reducer.reduce(task, "completed", attempt=2, revision=1)
    assert reducer.state_for("task-attempt") == "pending"
    assert reducer.errors()[-1]["code"] == "invalid_lifecycle_transition"


def test_engine_persists_sanitized_reducer_errors_separately():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("worker", "test.worker")
    task = {
        "id": "task-3",
        "target_agent": agent_id,
        "retries": 0,
        "payload": {"private": "do-not-store"},
    }

    assert engine.task_reducer.reduce(task, "running", revision=1)

    asyncio.run(engine._execute_task(task))

    assert engine.task_reducer.state_for("task-3") == "running"
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value
    errors = engine.get_reducer_errors()
    assert errors[-1]["code"] == "duplicate_transition"
    assert "do-not-store" not in str(errors)
