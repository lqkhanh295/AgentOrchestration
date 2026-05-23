import sys
import time
import pytest
from src.agent.runtime import AgentRuntime, RuntimeState

def test_heartbeat_revive_completed_runs():
    runtime = AgentRuntime()
    agent_id = "test_heartbeat_agent"
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    
    # 1. Start agent
    started = runtime.start(agent_id, cmd)
    assert started is True
    assert runtime.is_running(agent_id) is True
    assert runtime.get_state(agent_id) == RuntimeState.RUNNING
    assert runtime._locks.get(agent_id) is True
    
    # Send a valid heartbeat
    assert runtime.heartbeat(agent_id) is True
    
    # 2. Record terminal outcome
    runtime.record_terminal_outcome(agent_id, "success")
    assert runtime.get_state(agent_id) == RuntimeState.STOPPED
    assert runtime._terminal_outcomes.get(agent_id) == "success"
    assert runtime._locks.get(agent_id) is None
    
    # 3. Attempting to send heartbeat for completed run should fail and return False
    assert runtime.heartbeat(agent_id) is False
    
    # State should remain STOPPED (not revived to RUNNING)
    assert runtime.get_state(agent_id) == RuntimeState.STOPPED

def test_heartbeat_timeout_kills_agent():
    runtime = AgentRuntime()
    agent_id = "test_timeout_agent"
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    
    started = runtime.start(agent_id, cmd)
    assert started is True
    
    # Set heartbeat time back to simulate timeout
    runtime._heartbeats[agent_id] = time.monotonic() - 100
    
    # check_heartbeats should detect timeout and terminate the agent
    timed_out = runtime.check_heartbeats(timeout_seconds=50)
    assert agent_id in timed_out
    assert runtime.is_running(agent_id) is False
    assert runtime.get_state(agent_id) == RuntimeState.STOPPED
    assert runtime._terminal_outcomes[agent_id] == "heartbeat_timeout"
    assert runtime._locks.get(agent_id) is None
