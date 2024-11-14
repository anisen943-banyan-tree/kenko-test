# src/config/settings.py
from pydantic import BaseSettings
import os

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")
    environment: str = os.getenv("ENVIRONMENT", "development")
    test_database_url: str = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_password@localhost/test_dbname")
    test_environment: str = os.getenv("TEST_ENVIRONMENT", "test")

settings = Settings()