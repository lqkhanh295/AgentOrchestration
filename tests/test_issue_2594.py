import pytest
from src.orchestrator.scheduler import TaskScheduler

def test_legacy_queue_records_and_malformed_payloads():
    scheduler = TaskScheduler()
    
    # 1. Invalid payload types (None, int, invalid string) should raise ValueError
    with pytest.raises(ValueError):
        scheduler.enqueue(None)
        
    with pytest.raises(ValueError):
        scheduler.enqueue(123)
        
    with pytest.raises(ValueError):
        scheduler.enqueue("invalid JSON string")
        
    # 2. Dict missing vital fields (neither type nor target_agent) should raise ValueError
    with pytest.raises(ValueError):
        scheduler.enqueue({"only_some_data": 42})
        
    # 3. Legacy JSON string representing a valid task should be parsed and enqueued successfully
    valid_legacy_payload_str = '{"type": "legacy_task", "target_agent": "agent_123"}'
    task_id = scheduler.enqueue(valid_legacy_payload_str)
    assert task_id is not None
    
    # Verify it can be dequeued
    import asyncio
    task = asyncio.run(scheduler.dequeue())
    assert task is not None
    assert task["type"] == "legacy_task"
    assert task["target_agent"] == "agent_123"
    assert "id" in task
