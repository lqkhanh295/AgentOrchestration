import pytest
import os
from src.common.config import Config
from src.common.errors import ConfigurationError

def test_json_parse_failures_with_path_context(tmp_path):
    config_file = tmp_path / "bad_config.json"
    # Write malformed JSON
    config_file.write_text('{\n  "app": {\n    "name": "test",\n    "port": 8080,\n  }\n}') # trailing comma is invalid in JSON
    
    with pytest.raises(ConfigurationError) as exc_info:
        Config(str(config_file))
        
    err_msg = str(exc_info.value)
    assert "bad_config.json" in err_msg
    assert "line 4" in err_msg or "line 5" in err_msg or "line" in err_msg
    assert "column" in err_msg
