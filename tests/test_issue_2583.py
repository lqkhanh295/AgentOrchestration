import time
import asyncio
import pytest
from src.orchestrator.scheduler import TaskScheduler

def test_priority_queue_polling_delayed_and_completed_guards():
    scheduler = TaskScheduler()
    
    # 1. Schedule a delayed task
    task = {"type": "delayed_task", "target_agent": "agent_1"}
    task_id = scheduler.schedule(task, delay=0.1, queue="default", priority=5)
    
    # Verify that the task is currently in self._scheduled
    assert task_id in scheduler._scheduled
    
    # 2. Attempting to enqueue this task directly before its delay has passed should be rejected
    # because it is still delayed.
    scheduler.enqueue(task)
    
    # dequeue immediately should return None (not enqueued because it's still delayed)
    result = asyncio.run(scheduler.dequeue(queue="default"))
    assert result is None
    
    # 3. Wait for the delay to expire
    time.sleep(0.12)
    
    # dequeue should now find it expired, enqueue it to its target queue with priority, and return it
    dequeued = asyncio.run(scheduler.dequeue(queue="default"))
    assert dequeued is not None
    assert dequeued["id"] == task_id
    assert dequeued["type"] == "delayed_task"
    
    # 4. Mark the task as completed (ack transaction)
    assert scheduler.complete(task_id) is True
    assert task_id in scheduler._completed
    
    # 5. Try to re-enqueue the completed task should be rejected/safely deferred
    scheduler.enqueue(task)
    
    # verify it is not in flight or queue
    assert task_id not in scheduler._in_flight
    assert len(scheduler._queues.get("default", [])) == 0
