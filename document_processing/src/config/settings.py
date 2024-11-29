# src/config/settings.py
from pydantic_settings import BaseSettings  # BaseSettings is now in pydantic-settings
from pydantic import ConfigDict
from pydantic import Field
import os
import logging
import json_log_formatter
from typing import ClassVar

class Settings(BaseSettings):
    jwt_secret_key: str = Field(default="test_secret_key_123", alias="JWT_SECRET_KEY", json_schema_extra={"description": "JWT secret key for authentication"})
    database_dsn: str = Field(default="sqlite:///:memory:", alias="DATABASE_DSN", json_schema_extra={"description": "Database DSN for connection"})  # Fallback to SQLite for tests
    database_url: str = "postgresql://postgres:postgres@localhost:5432/claims_test"
    hostlist: ClassVar[str] = 'localhost:5432'  # Updated with ClassVar annotation
    environment: str = Field(default="production", alias="ENVIRONMENT", json_schema_extra={"description": "Environment setting"})
    test_database_url: str = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
    test_environment: str = os.getenv("TEST_ENVIRONMENT", "test").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "your_default_value")
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL", json_schema_extra={"description": "Redis URL for caching"})
    # Add this property to provide uppercase compatibility
    @property
    def JWT_SECRET_KEY(self) -> str:
        return self.jwt_secret_key

    @property
    def REDIS_URL(self) -> str:
        return self.redis_url

    @property
    def is_test_env(self):
        return self.environment == "test"

    model_config = ConfigDict(
        case_sensitive=True,
        extra="allow",
        env_nested_delimiter="__",
        env_file=".env",
    )

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