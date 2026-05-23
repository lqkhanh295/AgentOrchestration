import pytest
from src.sdk.decorators import task, on_event

def test_task_decorator_metadata():
    @task(name="custom_task", retries=2, timeout=10)
    async def my_task():
        return "done"

    assert hasattr(my_task, "__task_config__")
    assert my_task.__task_config__["name"] == "custom_task"
    assert my_task.__task_config__["retries"] == 2
    assert my_task.__task_config__["timeout"] == 10

def test_on_event_decorator_metadata():
    @on_event(event_type="user_registered")
    async def my_event_handler():
        return "processed"

    assert hasattr(my_event_handler, "__event_handler__")
    assert my_event_handler.__event_handler__ == "user_registered"
