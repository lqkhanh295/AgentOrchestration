import pytest
import os
from src.common.config import Config

def test_literal_underscores_in_override_keys(tmp_path, monkeypatch):
    # Set up config file with existing keys containing underscores
    config_file = tmp_path / "config.json"
    config_file.write_text('{"api_url": "http://default", "services": {"auth_service": {"db_port": 5432}}}')
    
    # 1. Smart matching against existing config
    monkeypatch.setenv("AO_API_URL", "http://smart-matched")
    monkeypatch.setenv("AO_SERVICES_AUTH_SERVICE_DB_PORT", "9999")
    
    config = Config(str(config_file))
    assert config.get("api_url") == "http://smart-matched"
    assert config.get("services.auth_service.db_port") == "9999"
    
    # 2. Key mapping
    monkeypatch.setenv("AO_MY_CUSTOM_ENV", "mapped-value")
    config_mapped = Config(str(config_file), key_map={"MY_CUSTOM_ENV": "services.auth_service.custom_key"})
    assert config_mapped.get("services.auth_service.custom_key") == "mapped-value"
    
    # 3. Double underscores convention (maps to literal underscore)
    monkeypatch.setenv("AO_DB__NAME", "my_db") # AO_DB__NAME -> db_name
    config_db = Config(str(config_file))
    assert config_db.get("db_name") == "my_db"
