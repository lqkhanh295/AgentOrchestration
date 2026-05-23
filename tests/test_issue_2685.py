import pytest
import shutil
import tempfile
from pathlib import Path
from src.agent.sandbox import AgentSandbox

def test_sandbox_path_traversal_create():
    sandbox = AgentSandbox()
    
    # Path traversal patterns should raise ValueError
    with pytest.raises(ValueError):
        sandbox.create("../evil_agent")
        
    with pytest.raises(ValueError):
        sandbox.create("subfolder/../../evil_agent")

    sandbox.cleanup_all()

def test_sandbox_get_path_missing_and_out_of_root():
    sandbox = AgentSandbox()
    agent_id = "legit_agent"
    path = sandbox.create(agent_id)
    
    # Check it exists first
    assert sandbox.get_path(agent_id) == path
    
    # Simulate tracked directory removed outside the manager
    shutil.rmtree(path, ignore_errors=True)
    assert sandbox.get_path(agent_id) is None
    
    # Re-create and track an out of root path (simulating a compromised dictionary entry)
    path = sandbox.create(agent_id)
    outside_dir = Path(tempfile.mkdtemp(prefix="ao_outside_"))
    try:
        # Manually overwrite the path tracker with a path outside the base_path
        sandbox._sandboxes[agent_id] = outside_dir
        assert sandbox.get_path(agent_id) is None
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)

    sandbox.cleanup_all()
