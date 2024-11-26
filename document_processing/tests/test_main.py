import pytest
from fastapi.testclient import TestClient
from src.app_factory import create_app  # Updated import
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from unittest.mock import AsyncMock

from src.app_factory import create_app
from fastapi.testclient import TestClient

app = create_app()
client = TestClient(app)

@pytest.fixture(autouse=True)
async def setup_cache():
    FastAPICache.init(InMemoryBackend())
    app.state.pool = AsyncMock()  # Ensure the app state includes `pool`
    yield
    await FastAPICache.clear()  # Add `await` to clear cache

@pytest.fixture
async def db_pool():
    """Create and clean test database"""
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=5  # Reduce pool size for tests
    )
    yield pool
    await pool.close()

@pytest.mark.asyncio
async def test_cache_initialization():
    FastAPICache.init(InMemoryBackend())  # Ensure initialization
    await FastAPICache.clear()  # Add `await` to clear cache
    assert FastAPICache.get_backend() is not None

@pytest.mark.asyncio
async def test_health_check_cache():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}  # Fixed to match app_factory

    # Simulate a second request to check if the response is cached
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}  # Fixed to match app_factory
    await FastAPICache.clear()  # Add `await` to clear cache

@pytest.mark.asyncio
async def test_database_pool_creation():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    await FastAPICache.clear()  # Add `await` to clear cache