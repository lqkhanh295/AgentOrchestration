import pytest
import sys
from unittest.mock import patch, mock_open
from src.cli.main import cli

def test_deploy_failure_exit_code():
    test_args = ["main.py", "deploy", "fake_manifest.json"]
    
    with patch.object(sys, 'argv', test_args):
        with patch('builtins.open', mock_open(read_data='{"name": "test", "agent_type": "bot", "config": {}}')):
            with patch('src.cli.main.OrchestratorClient') as MockClient:
                mock_client_instance = MockClient.return_value
                mock_client_instance.register_agent.return_value = {"error": "500", "message": "Internal Server Error"}
                
                with pytest.raises(SystemExit) as exc_info:
                    cli()
                    
                assert exc_info.value.code == 1
