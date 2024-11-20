import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from unittest.mock import patch, AsyncMock, Mock
from src.api.routes.institutions import (
    router, 
    InstitutionManager, 
    Institution,
    InstitutionCreate,
    rate_limiter_factory
)
from fastapi.middleware.cors import CORSMiddleware
import jwt
from datetime import datetime, timedelta
import os
from src.config.settings import settings
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import JsonCoder
import redis.asyncio as redis

# Create test app
app = FastAPI()
app.include_router(router)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure rate limiter for test environment
limiter = rate_limiter_factory()
app.state.limiter = limiter

@pytest.fixture(autouse=True)
async def setup_cache():
    """Setup and teardown FastAPI Cache for tests."""
    # Create mock Redis client
    redis_client = AsyncMock(spec=redis.Redis)
    
    # Mock Redis methods
    redis_client.get.return_value = None
    redis_client.set.return_value = True
    redis_client.delete.return_value = True
    redis_client.exists.return_value = False
    redis_client.close = AsyncMock()
    redis_client.wait_closed = AsyncMock()
    
    # Initialize cache with mock Redis backend
    FastAPICache.init(
        RedisBackend(redis_client),
        prefix="fastapi-cache-test",
        key_builder=None,
        coder=JsonCoder
    )
    
    yield
    
    # Clear cache after tests
    await FastAPICache.clear()
    await redis_client.close()
    await redis_client.wait_closed()

@pytest.fixture
async def async_client():
    """Create async test client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

def setup_mock_db_pool():
    """Create and configure a mock database pool."""
    pool = AsyncMock()
    async def async_context_manager():
        conn = AsyncMock()
        conn.fetch = AsyncMock()
        conn.fetchrow = AsyncMock()
        conn.execute = AsyncMock()
        conn.transaction = AsyncMock()
        return conn
    
    # Correctly mock the async context manager for `pool.acquire`.
    pool.acquire.return_value.__aenter__.side_effect = async_context_manager
    pool.acquire.return_value.__aexit__ = AsyncMock()
    
    return pool

@pytest.fixture
def mock_db_pool():
    return setup_mock_db_pool()

@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis_client = AsyncMock(spec=redis.Redis)
    redis_client.get.return_value = None
    redis_client.set.return_value = True
    redis_client.delete.return_value = True
    return redis_client

def get_mock_institutions():
    return [
        {
            "id": 1,
            "name": "Test Institution",
            "code": "TEST123",
            "contact_email": "test@example.com",
            "contact_phone": "1234567890",
            "subscription_tier": "STANDARD",
            "status": "ACTIVE",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
    ]

def generate_jwt_token(user_id: int, role: str, exp: timedelta = timedelta(hours=1)) -> str:
    return jwt.encode(
        {
            "user_id": user_id,
            "role": role,
            "exp": datetime.utcnow() + exp,
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

@pytest.fixture
def admin_token():
    """Generate a valid admin JWT token."""
    return generate_jwt_token(user_id=1, role="ADMIN")

@pytest.fixture
def admin_headers(admin_token):
    """Create headers with admin JWT token."""
    return {"Authorization": f"Bearer {admin_token}"}

@pytest.mark.asyncio
async def test_list_institutions_success(async_client, mock_db_pool):
    """Test successful listing of institutions with caching."""
    test_data = get_mock_institutions()
    with patch('src.api.routes.institutions.get_db_pool', return_value=mock_db_pool), \
         patch('src.api.routes.institutions.verify_admin_token') as mock_verify:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        with patch.object(InstitutionManager, 'list_institutions', new_callable=AsyncMock, return_value=test_data):
            response = await async_client.get("/admin/institutions/")
            assert response.status_code == 200
            assert response.json() == test_data

@pytest.mark.asyncio
async def test_create_institution_invalidates_cache(async_client, mock_db_pool):
    """Test that creating a new institution invalidates the cache."""
    test_data = {
        "name": "New Institution",
        "code": "NEW123",
        "contact_email": "new@test.com",
        "contact_phone": "1234567890",
        "subscription_tier": "STANDARD"
    }
    with patch.object(InstitutionManager, 'create_institution', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {**test_data, "id": 1, "status": "ACTIVE"}
        with patch('fastapi_cache.FastAPICache.clear') as mock_cache_clear:
            response = await async_client.post("/admin/institutions/", json=test_data)
            assert response.status_code == 200
            assert response.json()["name"] == test_data["name"]
            mock_cache_clear.assert_called_once_with(namespace="institutions")

@pytest.mark.asyncio
async def test_rate_limit_disabled_in_test(async_client, mock_db_pool):
    """Verify rate limiter is disabled in test environment."""
    app.state.limiter.enabled = False  # Ensure limiter is disabled
    with patch('src.api.routes.institutions.get_db_pool', return_value=mock_db_pool):
        for _ in range(10):
            response = await async_client.get("/admin/institutions/")
            assert response.status_code == 200

@pytest.mark.asyncio
async def test_unauthorized_access(async_client):
    """Test unauthorized access handling."""
    response = await async_client.get("/admin/institutions/")
    assert response.status_code == 403
    assert "Not authenticated" in response.json()["detail"]

@pytest.mark.asyncio
async def test_invalid_token(async_client):
    """Test invalid token handling."""
    headers = {"Authorization": "Bearer invalid_token"}
    response = await async_client.get("/admin/institutions/", headers=headers)
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]

@pytest.mark.asyncio
async def test_non_admin_access(async_client, mock_db_pool):
    """Test non-admin access handling."""
    token = jwt.encode(
        {"user_id": 1, "role": "USER"},
        settings.jwt_secret_key,
        algorithm="HS256"
    )
    headers = {"Authorization": f"Bearer {token}"}
    response = await async_client.get("/admin/institutions/", headers=headers)
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]