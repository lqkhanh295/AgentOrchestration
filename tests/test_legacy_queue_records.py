import asyncio
import json

from src.orchestrator.scheduler import TaskScheduler


def test_malformed_legacy_json_is_rejected_without_queue_mutation():
    scheduler = TaskScheduler()
    scheduler.enqueue({"type": "existing"})

    malformed = '{"payload": "secret-token"'
    assert scheduler.enqueue_legacy_record(malformed) is None

    task = asyncio.run(scheduler.dequeue())
    assert task["type"] == "existing"
    assert asyncio.run(scheduler.dequeue()) is None
    audit = scheduler.queue_audit()
    assert audit[-1]["action"] == "legacy_record_rejected"
    assert "secret-token" not in str(audit)


def test_legacy_record_with_bad_payload_is_rejected_safely():
    scheduler = TaskScheduler()
    record = {
        "job_id": "legacy-1",
        "payload": "not-a-task",
        "private": {"token": "do-not-copy"},
    }

    assert scheduler.enqueue_legacy_record(record) is None
    assert asyncio.run(scheduler.dequeue()) is None
    audit = scheduler.queue_audit()
    assert audit[-1]["legacy_id"] == "legacy-1"
    assert audit[-1]["reason"] == "legacy record payload must be an object"
    assert "do-not-copy" not in str(audit)


def test_legacy_record_enqueue_is_idempotent_by_legacy_id():
    scheduler = TaskScheduler()
    record = json.dumps(
        {
            "job_id": "legacy-2",
            "payload": {"type": "sync", "payload": {"value": 1}},
        }
    )

    first_task_id = scheduler.enqueue_legacy_record(record)
    second_task_id = scheduler.enqueue_legacy_record(record)

    assert first_task_id == second_task_id
    task = asyncio.run(scheduler.dequeue())
    assert task["type"] == "sync"
    assert task["legacy_id"] == "legacy-2"
    assert asyncio.run(scheduler.dequeue()) is None
    assert scheduler.queue_audit()[-1]["action"] == (
        "legacy_record_deduplicated"
    )


def test_legacy_record_requires_task_type_before_enqueue():
    scheduler = TaskScheduler()
    record = {"job_id": "legacy-3", "payload": {"payload": {"value": 1}}}

    assert scheduler.enqueue_legacy_record(record) is None
    assert asyncio.run(scheduler.dequeue()) is None
    assert scheduler.queue_audit()[-1]["reason"] == (
        "legacy payload is missing task type"
    )
