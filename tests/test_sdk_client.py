import pytest
from src.sdk.client import OrchestratorClient

def test_register_agent_blank_name():
    client = OrchestratorClient()
    with pytest.raises(ValueError, match="blank"):
        client.register_agent("", "type")

    with pytest.raises(ValueError, match="blank"):
        client.register_agent("   ", "type")
        
    with pytest.raises(ValueError, match="blank"):
        client.register_agent(None, "type")
