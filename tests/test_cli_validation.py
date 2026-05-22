import pytest
import sys
from unittest.mock import patch
from src.cli.main import validate_agent_id, cli

def test_validate_agent_id_valid():
    assert validate_agent_id("valid-agent_id-123") == True

def test_validate_agent_id_invalid_chars():
    with pytest.raises(SystemExit) as exc:
        validate_agent_id("invalid id!")
    assert exc.value.code == 1

def test_validate_agent_id_empty():
    with pytest.raises(SystemExit) as exc:
        validate_agent_id("")
    assert exc.value.code == 1

def test_cli_logs_valid_id(capsys):
    test_args = ["orchestrator", "logs", "agent-1"]
    with patch.object(sys, 'argv', test_args):
        cli()
        captured = capsys.readouterr()
        assert "Fetching logs for agent: agent-1" in captured.out

def test_cli_logs_invalid_id(capsys):
    test_args = ["orchestrator", "logs", "agent@1"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc:
            cli()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid agent ID format: agent@1" in captured.err
