import pytest
from unittest.mock import patch
from urllib.error import URLError
from src.sdk.client import OrchestratorClient

def test_sdk_error_includes_context():
    client = OrchestratorClient()
    
    with patch('src.sdk.client.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = URLError("Connection refused")
        
        with pytest.raises(RuntimeError) as exc_info:
            client.register_agent("test", "worker")
            
        error_msg = str(exc_info.value)
        assert "SDK transport error [POST /agents]" in error_msg
        assert "Connection refused" in error_msg
