# FILE: document_processing/tests/test_settings.py

import os
import pytest
from src.config.settings import Settings

@pytest.fixture(autouse=True)
def override_env_vars(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test_jwt_secret_key")
    monkeypatch.setenv("DATABASE_DSN", "test_database_dsn")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test_user:test_password@localhost/test_db")

@pytest.fixture
def override_settings(monkeypatch):
    # Apply monkeypatch for environment variables
    monkeypatch.setenv('JWT_SECRET_KEY', 'test_jwt_secret_key')
    monkeypatch.setenv('DATABASE_DSN', 'test_database_dsn')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://test_user:test_password@localhost/test_dbname')
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://test_user:test_password@localhost/test_dbname')
    monkeypatch.setenv('ENVIRONMENT', 'test')
    monkeypatch.setenv('TEST_ENVIRONMENT', 'test')
    
    # Instantiate Settings
    settings = Settings()
    
    return settings

def test_settings(override_settings):
    settings = override_settings
    
    # Validate environment variables
    assert os.getenv('JWT_SECRET_KEY') == 'test_jwt_secret_key'
    assert os.getenv('DATABASE_DSN') == 'test_database_dsn'
    assert os.getenv('DATABASE_URL') == 'postgresql://test_user:test_password@localhost/test_dbname'
    assert os.getenv('TEST_DATABASE_URL') == 'postgresql://test_user:test_password@localhost/test_dbname'
    assert os.getenv('ENVIRONMENT') == 'test'
    assert os.getenv('TEST_ENVIRONMENT') == 'test'

    # Validate Settings attributes
    assert settings.jwt_secret_key == 'test_jwt_secret_key'