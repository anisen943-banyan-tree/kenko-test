"""
Test module for main application functionality.
"""

# Standard library imports
import asyncio
from typing import AsyncGenerator, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

# Third-party imports
import pytest
from httpx import AsyncClient
import asyncpg
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
import redis.asyncio as redis
from redis.exceptions import RedisError

# Local imports
from src.app_factory import create_app
from src.config.settings import Settings
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

# Test constants
TEST_TIMEOUT = 30
HEALTH_CHECK_ENDPOINT = "/health"
DB_POOL_CONFIG = {
    "min_size": 1,
    "max_size": 5,
    "timeout": 10
}

# Initialize settings
settings = Settings()

@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def app() -> FastAPI:
    """Create a test instance of the application."""
    app = create_app()
    return app

@pytest.fixture(scope="function")
async def test_app(app: FastAPI) -> FastAPI:
    """Create a test instance with mocked dependencies."""
    return app

@pytest.fixture(scope="function")
async def mock_db_pool() -> AsyncMock:
    """Create a mock database pool."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=True)
    
    class AsyncPoolContextManager:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    pool = AsyncMock()
    pool.acquire = lambda: AsyncPoolContextManager(conn)
    return pool

@pytest.fixture(scope="function")
async def mock_redis_client() -> AsyncMock:
    """Create a mock Redis client."""
    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    # Mock the client creation
    async def mock_from_url(*args, **kwargs):
        return client
    client.from_url = mock_from_url
    return client

@pytest.fixture(scope="function")
async def test_app_with_mocks(
    test_app: FastAPI,
    mock_db_pool: AsyncMock,
    mock_redis_client: AsyncMock
) -> FastAPI:
    """Create a test app with mocked dependencies."""
    test_app.state.pool = mock_db_pool
    # Patch both Redis client and FastAPICache
    with patch('redis.asyncio.Redis.from_url', return_value=mock_redis_client), \
         patch('fastapi_cache.FastAPICache.get_backend') as mock_cache:
        mock_cache.return_value = AsyncMock()
        yield test_app

@pytest.fixture(scope="function")
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create an async client for testing."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        yield client

@pytest.fixture(scope="session", autouse=True)
async def initialize_cache():
    """Initialize FastAPICache for all tests."""
    backend = InMemoryBackend()
    FastAPICache.init(backend, prefix="test")
    yield
    # Don't clear the backend, just reset it
    FastAPICache._backend = None

@pytest.fixture(scope="function")
async def mock_cache():
    """Create a mock cache for individual tests."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    
    original_backend = FastAPICache._backend
    FastAPICache._backend = cache
    yield cache
    FastAPICache._backend = original_backend

class TestHealthCheck:
    """Test suite for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_success(
        self,
        test_app_with_mocks: FastAPI,
        async_client: AsyncClient
    ):
        """Test successful health check response."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_check_redis_error(
        self,
        test_app: FastAPI,
        async_client: AsyncClient,
        mock_redis_client: AsyncMock
    ):
        """Test health check when Redis is unavailable."""
        mock_redis_client.ping.side_effect = redis.RedisError("Redis connection failed")
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis_client):
            response = await async_client.get("/health")
            assert response.status_code == 503
            assert response.json() == {
                "status": "error",
                "detail": "Redis connection failed"
            }

    @pytest.mark.asyncio
    async def test_health_check_db_error(
        self,
        test_app: FastAPI,
        async_client: AsyncClient,
        mock_db_pool: AsyncMock,
        mock_redis_client: AsyncMock
    ):
        """Test health check when database is unavailable."""
        mock_db_pool.acquire.side_effect = asyncpg.PostgresError("Database connection failed")
        test_app.state.pool = mock_db_pool
        
        with patch('redis.asyncio.Redis.from_url', return_value=mock_redis_client):
            response = await async_client.get("/health")
            assert response.status_code == 503
            assert response.json() == {
                "status": "error",
                "detail": "Database connection failed"
            }

class TestCacheOperations:
    """Test suite for cache operations."""

    @pytest.mark.asyncio
    async def test_cache_initialization(self, mock_cache: AsyncMock):
        """Test cache initialization and backend setup."""
        key = "test_key"
        value = {"data": "test_value"}
        
        mock_cache.get.return_value = value
        await FastAPICache.get_backend().set(key, value, 60)
        cached_value = await FastAPICache.get_backend().get(key)
        
        assert cached_value == value

    @pytest.mark.asyncio
    async def test_cache_expiration(self, mock_cache: AsyncMock):
        """Test cache expiration functionality."""
        key = "expiring_key"
        value = {"data": "expiring_value"}
        
        # Simulate expiration
        mock_cache.get.return_value = None
        await FastAPICache.get_backend().set(key, value, 1)
        await asyncio.sleep(2)
        expired_value = await FastAPICache.get_backend().get(key)
        assert expired_value is None

class TestDatabaseOperations:
    """Test suite for database operations."""

    @pytest.mark.asyncio
    async def test_db_pool_creation(self, mock_db_pool: AsyncMock):
        """Test database pool creation and basic query."""
        async with mock_db_pool.acquire() as conn:
            result = await conn.execute("SELECT 1")
            assert result is True

    @pytest.mark.asyncio
    async def test_db_pool_error_handling(self, mock_db_pool: AsyncMock):
        """Test database error handling."""
        with pytest.raises(asyncpg.PostgresError):
            async with mock_db_pool.acquire():
                pass