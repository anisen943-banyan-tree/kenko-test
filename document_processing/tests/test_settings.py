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
    # settings.py
    class Settings(BaseSettings):
        jwt_secret_key: str = Field(default="test_secret_key_123", alias="JWT_SECRET_KEY")
        database_dsn: str = Field(default="sqlite:///:memory:", alias="DATABASE_DSN")
        database_url: str = "postgresql://postgres:postgres@localhost:5432/claims_test"
        hostlist: ClassVar[str] = 'localhost:5432'
        environment: str = Field(default="production", alias="ENVIRONMENT")
        test_database_url: str = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
        test_environment: str = os.getenv("TEST_ENVIRONMENT", "test").lower()
        openai_api_key: str = os.getenv("OPENAI_API_KEY", "your_default_value")
        aws_access_key_id: str = "test"
        aws_secret_access_key: str = "test"
        aws_region: str = "us-east-1"

        @property
        def JWT_SECRET_KEY(self) -> str:
            return self.jwt_secret_key

        @property
        def is_test_env(self):
            return self.environment == "test"

        model_config = ConfigDict(
            case_sensitive=True,
            extra="allow",
            env_nested_delimiter="__",
            env_file=".env"
        )
    def test_settings_default_values(override_settings):
        settings = override_settings
        
        # Test default values
        assert settings.jwt_secret_key == 'test_jwt_secret_key'
        assert settings.database_dsn == 'test_database_dsn'
        assert settings.environment == 'test'
        assert settings.hostlist == 'localhost:5432'
        assert settings.aws_region == 'us-east-1'
        assert settings.aws_access_key_id == 'test'
        assert settings.aws_secret_access_key == 'test'

    def test_settings_property_methods(override_settings):
        settings = override_settings
        
        # Test property methods
        assert settings.JWT_SECRET_KEY == settings.jwt_secret_key
        assert settings.is_test_env is True

    def test_settings_database_urls(override_settings):
        settings = override_settings
        
        # Test database URLs
        assert settings.database_url == 'postgresql://test_user:test_password@localhost/test_dbname'
        assert settings.test_database_url == 'postgresql://test_user:test_password@localhost/test_dbname'

    def test_settings_environment_detection(override_settings):
        settings = override_settings
        
        # Test environment detection
        assert settings.environment == 'test'
        assert settings.test_environment == 'test'
        assert settings.is_test_env is True

    def test_settings_model_config(override_settings):
        settings = override_settings
        
        # Test model configuration
        assert settings.model_config['case_sensitive'] is True
        assert settings.model_config['extra'] == 'allow'
        assert settings.model_config['env_nested_delimiter'] == '__'

    @pytest.mark.parametrize("env_var,expected", [
        ("JWT_SECRET_KEY", "test_jwt_secret_key"),
        ("DATABASE_DSN", "test_database_dsn"),
        ("DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname"),
        ("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname"),
        ("ENVIRONMENT", "test"),
    ])
    def test_settings_env_vars(override_settings, env_var, expected):
        # Test that environment variables are correctly loaded
        assert os.getenv(env_var) == expected

    def test_settings_aws_credentials(override_settings):
        settings = override_settings
        
        # Test AWS credentials
        assert settings.aws_access_key_id == 'test'
        assert settings.aws_secret_access_key == 'test'
        assert settings.aws_region == 'us-east-1'

    def test_settings_openai_api_key(override_settings):
        settings = override_settings
        
        # Test OpenAI API key
        assert hasattr(settings, 'openai_api_key')
        # Default value test
        assert settings.openai_api_key == 'your_default_value'