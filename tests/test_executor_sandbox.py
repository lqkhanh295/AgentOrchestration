import pytest
from src.agent.executor import AgentExecutor

def test_executor_requires_positive_max_concurrent():
    with pytest.raises(ValueError, match="positive integer"):
        AgentExecutor(max_concurrent=0)
    
    with pytest.raises(ValueError, match="positive integer"):
        AgentExecutor(max_concurrent=-5)
        
    with pytest.raises(ValueError, match="positive integer"):
        AgentExecutor(max_concurrent="5")
        
    executor = AgentExecutor(max_concurrent=5)
    assert executor.max_concurrent == 5
