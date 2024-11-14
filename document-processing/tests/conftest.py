import pytest
import asyncpg
import os
from typing import AsyncGenerator
from pathlib import Path

# Add src to Python path
import sys
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

@pytest.fixture
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Create test database pool."""
    try:
        pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER", "claimsuser"),
            password=os.getenv("DB_PASSWORD", "Claims2024#Secure!"),
            database=os.getenv("DB_NAME", "claimsdb_test")
        )
        yield pool
    finally:
        if 'pool' in locals():
            await pool.close()

@pytest.fixture
async def test_client():
    """Create test client for FastAPI app."""
    from main import app  # Changed import to use main app
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url="http://test", headers={"Content-Type": "application/json"}) as client:
        yield client

@pytest.fixture
def test_token():
    """Generate test JWT token."""
    import jwt
    from datetime import datetime, timedelta
    
    payload = {
        "user_id": "test_user",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, "your-secret-key", algorithm="HS256")

@pytest.fixture
def mock_settings(mocker):
    """Mock Settings class."""
    from src.config import Settings
    settings = Settings()
    mocker.patch.object(settings, 'some_setting', 'mocked_value')
    return settings

# Add any existing initialization from __init__.py if needed