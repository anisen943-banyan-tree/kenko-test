# src/config/settings.py
from pydantic_settings import BaseSettings  # BaseSettings is now in pydantic-settings
from pydantic import ConfigDict
from pydantic import Field
import os
import logging
import boto3
import json_log_formatter

class Settings(BaseSettings):
    jwt_secret_key: str = Field(default="default_secret_key", alias="JWT_SECRET_KEY")
    database_dsn: str = os.getenv("DATABASE_DSN", os.getenv("DATABASE_URL", "default_dsn"))
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")
    environment: str = os.getenv("ENVIRONMENT", "development").lower()
    test_database_url: str = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
    test_environment: str = os.getenv("TEST_ENVIRONMENT", "test").lower()
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "your_default_value")
    airtable_api_key: str = boto3.client('secretsmanager', region_name=os.getenv("AWS_REGION")).get_secret_value(SecretId="AirtableApiKey")['SecretString']

    # Add this property to provide uppercase compatibility
    @property
    def JWT_SECRET_KEY(self) -> str:
        return self.jwt_secret_key

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