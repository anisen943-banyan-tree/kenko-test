# src/config/settings.py
from pydantic import BaseSettings
import os

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")
    environment: str = os.getenv("ENVIRONMENT", "development")

settings = Settings()