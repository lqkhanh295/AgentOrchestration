import os
from pathlib import Path
from src.agent.sandbox import AgentSandbox

def test_sandbox_base_path_resolved():
    sandbox = AgentSandbox(base_path="../sensitive")
    assert sandbox.base_path.is_absolute()
    assert sandbox.base_path == Path("../sensitive").resolve()

def test_sandbox_base_path_default_resolved():
    sandbox = AgentSandbox()
    assert sandbox.base_path.is_absolute()
