import pytest
from src.sdk.client import OrchestratorClient
from src.sdk.decorators import task

def test_register_agent_validation():
    client = OrchestratorClient()
    
    # Test empty name
    with pytest.raises(ValueError, match="Agent name cannot be empty or blank"):
        client.register_agent("", "test-agent")
        
    # Test blank name with whitespace
    with pytest.raises(ValueError, match="Agent name cannot be empty or blank"):
        client.register_agent("   ", "test-agent")
        
    # Test None name
    with pytest.raises(ValueError, match="Agent name cannot be empty or blank"):
        client.register_agent(None, "test-agent")

    # Test non-string name
    with pytest.raises(ValueError, match="Agent name cannot be empty or blank"):
        client.register_agent(123, "test-agent")


def test_task_decorator_timeout_validation():
    # Test zero timeout
    with pytest.raises(ValueError, match="Timeout must be a positive number"):
        @task(timeout=0)
        async def dummy_task_zero():
            pass
            
    # Test negative timeout
    with pytest.raises(ValueError, match="Timeout must be a positive number"):
        @task(timeout=-10)
        async def dummy_task_negative():
            pass

    # Test valid positive timeout doesn't raise
    @task(timeout=5)
    async def dummy_task_valid():
        return "ok"
        
    assert dummy_task_valid.__task_config__["timeout"] == 5
