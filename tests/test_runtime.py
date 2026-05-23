import sys
import time
from src.agent.runtime import AgentRuntime, RuntimeState

def test_runtime_lifecycle():
    runtime = AgentRuntime()
    agent_id = "test_agent_1"
    # Run a python process that sleeps for 10 seconds
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    
    # Start the process
    started = runtime.start(agent_id, cmd)
    assert started is True
    assert runtime.is_running(agent_id) is True
    assert runtime.get_state(agent_id) == RuntimeState.RUNNING
    assert agent_id in runtime._start_times

    # Stop the process
    stopped = runtime.stop(agent_id)
    assert stopped is True
    assert runtime.is_running(agent_id) is False
    assert runtime.get_state(agent_id) == RuntimeState.STOPPED
    assert agent_id not in runtime._start_times

def test_runtime_timeout():
    runtime = AgentRuntime()
    agent_id = "test_agent_2"
    # Run a python process that sleeps for 20 seconds
    cmd = [sys.executable, "-c", "import time; time.sleep(20)"]
    
    started = runtime.start(agent_id, cmd)
    assert started is True
    assert runtime.is_running(agent_id) is True

    # No timeout if check_timeouts is called with large timeout
    timed_out = runtime.check_timeouts(timeout_seconds=100)
    assert len(timed_out) == 0
    assert runtime.is_running(agent_id) is True

    # Artificially set the start time back in time to trigger timeout
    runtime._start_times[agent_id] = time.monotonic() - 30

    # Trigger timeout check
    timed_out = runtime.check_timeouts(timeout_seconds=15)
    assert len(timed_out) == 1
    assert timed_out[0] == agent_id
    assert runtime.is_running(agent_id) is False
    # Verify state evaluates to CRASHED when process is terminated
    assert runtime.get_state(agent_id) == RuntimeState.CRASHED
    assert agent_id not in runtime._start_times
