import sys
import os
from pathlib import Path
from unittest.mock import patch
from src.cli.main import cli

def test_cli_config_path_expansion():
    test_args = ["ao", "--config", "~/test_config.json", "init", "myproject"]
    with patch.object(sys, "argv", test_args):
        args = cli()
        expected_path = str(Path("~/test_config.json").expanduser().resolve())
        assert args.config == expected_path

def test_cli_config_relative_path_expansion():
    test_args = ["ao", "-c", "relative/config.json", "init", "myproject"]
    with patch.object(sys, "argv", test_args):
        args = cli()
        expected_path = str(Path("relative/config.json").resolve())
        assert args.config == expected_path
