import sys
import pytest
from unittest.mock import MagicMock
from src.agent.sandbox import AgentSandbox, ResourceLimits

def test_apply_limits_disk_mb_success():
    import sys
    resource_mod = sys.modules.get("resource")
    if resource_mod is None:
        pytest.skip("resource module is not available")

    # Set up mock attributes
    original_fsize = getattr(resource_mod, "RLIMIT_FSIZE", None)
    original_setrlimit = getattr(resource_mod, "setrlimit", None)
    try:
        resource_mod.RLIMIT_FSIZE = 99  # Mock constant
        resource_mod.setrlimit = MagicMock()
        
        sandbox = AgentSandbox()
        limits = ResourceLimits(disk_mb=50)
        sandbox.apply_limits("test_agent", limits)
        
        # Verify setrlimit was called with RLIMIT_FSIZE and the correct bytes
        resource_mod.setrlimit.assert_any_call(99, (50 * 1024 * 1024, 50 * 1024 * 1024))
    finally:
        # Restore original attributes
        if original_fsize is not None:
            resource_mod.RLIMIT_FSIZE = original_fsize
        elif hasattr(resource_mod, "RLIMIT_FSIZE"):
            delattr(resource_mod, "RLIMIT_FSIZE")
        if original_setrlimit is not None:
            resource_mod.setrlimit = original_setrlimit

def test_apply_limits_disk_mb_fails_when_unsupported():
    import sys
    resource_mod = sys.modules.get("resource")
    if resource_mod is None:
        pytest.skip("resource module is not available")

    # Set up mock attributes to simulate unsupported/failed platform
    original_fsize = getattr(resource_mod, "RLIMIT_FSIZE", None)
    original_setrlimit = getattr(resource_mod, "setrlimit", None)
    try:
        # Remove RLIMIT_FSIZE attribute to simulate platform that doesn't support it
        if hasattr(resource_mod, "RLIMIT_FSIZE"):
            delattr(resource_mod, "RLIMIT_FSIZE")
            
        sandbox = AgentSandbox()
        limits = ResourceLimits(disk_mb=50)
        with pytest.raises(ValueError) as excinfo:
            sandbox.apply_limits("test_agent", limits)
        assert "Enforcing disk_mb limit is not supported" in str(excinfo.value)
    finally:
        if original_fsize is not None:
            resource_mod.RLIMIT_FSIZE = original_fsize
        if original_setrlimit is not None:
            resource_mod.setrlimit = original_setrlimit
