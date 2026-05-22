import pytest
import asyncio
from src.sdk.decorators import task

@pytest.mark.asyncio
async def test_task_decorator_sync_function():
    @task(timeout=5)
    def sync_func():
        return "sync_success"
        
    result = await sync_func()
    assert result == "sync_success"

@pytest.mark.asyncio
async def test_task_decorator_async_function():
    @task(timeout=5)
    async def async_func():
        return "async_success"
        
    result = await async_func()
    assert result == "async_success"
