# src/config/settings.py
from pydantic_settings import BaseSettings  # BaseSettings is now in pydantic-settings
from pydantic import ConfigDict
from pydantic import Field
import os
import logging
import json_log_formatter

class Settings(BaseSettings):
    jwt_secret_key: str = Field(default="default_secret_key", alias="JWT_SECRET_KEY")
    database_dsn: str = Field(default="sqlite:///:memory:", alias="DATABASE_DSN")  # Fallback to SQLite for tests
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://claimsuser:Claims2024#Secure!@localhost/claimsdb_test"
    )
    environment: str = Field(default="production", alias="ENVIRONMENT")
    test_database_url: str = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
    test_environment: str = os.getenv("TEST_ENVIRONMENT", "test").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "your_default_value")
    # Add this property to provide uppercase compatibility
    @property
    def JWT_SECRET_KEY(self) -> str:
        return self.jwt_secret_key

    @property
    def is_test_env(self):
        return self.environment == "test"

    model_config = ConfigDict(case_sensitive=True, extra="allow", env_nested_delimiter="__")

# Ensure environment variables are accessible during tests
if os.getenv("ENVIRONMENT", "development").lower() == "test":
    os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
    logging.info("Test environment detected. DATABASE_URL set to test database URL.")

formatter = json_log_formatter.JSONFormatter()
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

settings = Settings()