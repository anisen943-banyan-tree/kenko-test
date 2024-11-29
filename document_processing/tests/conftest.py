import pytest
import asyncpg
import asyncio
import os
import logging
from typing import AsyncGenerator
from pathlib import Path
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from datetime import datetime, timedelta, timezone
import jwt

# Add src to Python path
import sys
src_path = str(Path(__file__).parent.parent / "src")
if (src_path not in sys.path):
    sys.path.insert(0, src_path)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global settings object
from src.config.settings import Settings  # Updated import path
settings = Settings()

pytest_plugins = ('pytest_asyncio',)

TEST_CONFIG = {
    "database": {
        "min_connections": 1,
        "max_connections": 10,
        "timeout": 30,
        "retry_attempts": 3,
        "retry_delay": 1
    },
    "redis": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "timeout": 5
    },
    "jwt": {
        "test_secret": "test_secret_key",
        "expiry_hours": 1
    }
}

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
def set_env_vars():
    os.environ['JWT_SECRET_KEY'] = settings.jwt_secret_key
    os.environ['DATABASE_URL'] = settings.database_url
    os.environ['ENVIRONMENT'] = settings.environment
    os.environ['TEST_ENVIRONMENT'] = 'test'
    logger.info("Test environment variables set.")
    yield
    os.environ.pop('JWT_SECRET_KEY', None)
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('ENVIRONMENT', None)
    os.environ.pop('TEST_ENVIRONMENT', None)

@pytest.fixture(scope="session")
@pytest.mark.asyncio
async def db_pool(event_loop):
    try:
        pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=TEST_CONFIG['database']['min_connections'],
            max_size=TEST_CONFIG['database']['max_connections'],
            timeout=TEST_CONFIG['database']['timeout']
        )
        await wait_for_service(
            lambda: check_db_connection(pool), 
            service_name="database",
            timeout=5  # Reduced timeout for tests
        )
        yield pool
        await pool.close()
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        raise

@pytest.fixture(scope="session")
async def redis_client():
    redis = Redis(
        host=TEST_CONFIG['redis']['host'],
        port=TEST_CONFIG['redis']['port'],
        db=TEST_CONFIG['redis']['db'],
        socket_timeout=TEST_CONFIG['redis']['timeout']
    )
    await wait_for_service(lambda: check_redis_connection(redis), service_name="Redis")
    yield redis
    redis.close()

@pytest.fixture
def generate_test_token():
    def _generate_test_token(user_id: int, role: str = "ADMIN", exp: timedelta = timedelta(hours=TEST_CONFIG['jwt']['expiry_hours'])):
        payload = {
            "user_id": user_id,
            "role": role,
            "exp": (datetime.now(timezone.utc) + exp).timestamp(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return _generate_test_token

@pytest.fixture
async def test_client(initialize_app):
    async with AsyncClient(app=initialize_app, base_url="http://test") as client:
        yield client

@pytest.fixture(scope="session")
@pytest.mark.asyncio
async def initialize_app(event_loop):
    app = create_app()
    async with app.lifespan():
        yield app

@pytest.fixture
async def mock_document_processor(mocker):
    mock_processor = mocker.patch('src.document.document_processor.DocumentProcessor', autospec=True)
    mock_processor_instance = mock_processor.return_value
    mock_processor_instance.store_document = AsyncMock(return_value="mock_document_id")
    return mock_processor_instance

@pytest.fixture(autouse=True)
async def setup_cache():
    FastAPICache.init(InMemoryBackend())
    yield
    await FastAPICache.clear()

@pytest.fixture(autouse=True)
def mock_aws_services(mocker):
    mock_s3 = mocker.patch('boto3.client')
    mock_s3.return_value.upload_fileobj.return_value = None
    mock_s3.return_value.download_fileobj.return_value = None
    return mock_s3

async def wait_for_service(check_func, service_name="service", timeout=30, interval=0.1):
    """Wait for a service to become available."""
    start_time = datetime.now()
    while (datetime.now() - start_time).seconds < timeout:
        try:
            await check_func()
            return
        except Exception as e:
            logger.debug(f"Waiting for {service_name}: {str(e)}")
            await asyncio.sleep(interval)
    raise TimeoutError(f"Timeout waiting for {service_name}")

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Setup test environment variables."""
    test_env = {
        "TEST_ENV": "true",
        "DATABASE_URL": "sqlite:///:memory:",
        "API_KEY": "test-key"
    }
    for key, value in test_env.items():
        os.environ[key] = value
    yield test_env
    for key in test_env:
        os.environ.pop(key, None)

async def check_db_connection(pool):
    """Check if database is accessible."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")

@pytest.fixture(autouse=True)
async def setup_test_cache():
    """Initialize cache backend for tests."""
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.inmemory import InMemoryBackend
    
    backend = InMemoryBackend()
    FastAPICache.init(backend, prefix="test")
    
    # Ensure backend is properly initialized
    await backend.set("test_key", "test_value", 60)
    
    yield
    
    # Cleanup
    await FastAPICache.clear()