import pytest
import asyncpg
import asyncio
import os
import logging
from typing import AsyncGenerator
from pathlib import Path

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

@pytest.fixture(scope="function", autouse=True)
def set_env_vars():
    # Update the JWT_SECRET_KEY to use the lowercase "jwt_secret_key" attribute
    os.environ['JWT_SECRET_KEY'] = settings.jwt_secret_key
    os.environ['DATABASE_URL'] = settings.database_url
    os.environ['ENVIRONMENT'] = settings.environment
    os.environ['TEST_ENVIRONMENT'] = 'test'
    os.environ['ANOTHER_ENV_VAR'] = 'another_value'  # Example additional env var
    
    logger.info("Test environment variables set.")

@pytest.fixture(scope="session")
def setup_session_env():
    import os
    os.environ["TEST_ENV"] = "true"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["API_KEY"] = "test-key"
    yield
    os.environ.pop("TEST_ENV")
    os.environ.pop("DATABASE_URL")
    os.environ.pop("API_KEY")

@pytest.fixture(scope="function")
def setup_test_env():
    import os
    os.environ["TEST_ENV"] = "true"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["API_KEY"] = "test-key"
    print("Test environment variables set.")
    yield
    print("Tearing down test environment.")
    os.environ.pop("TEST_ENV")
    os.environ.pop("DATABASE_URL")
    os.environ.pop("API_KEY")

from fastapi import FastAPI
from httpx import AsyncClient
from contextlib import asynccontextmanager
from src.app_factory import create_app
from src.document.document_processor import DocumentProcessor, ProcessorConfig
from src.config.settings import settings
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from unittest.mock import AsyncMock

@pytest.fixture(scope="session", autouse=True)
async def initialize_app():
    """Initialize the app and DocumentProcessor before any tests run."""
    app = create_app()
    async with asynccontextmanager(app.lifespan)(app):
        yield app

@pytest.fixture
async def test_client(initialize_app):
    """Create test client with initialized DocumentProcessor."""
    async with AsyncClient(app=initialize_app, base_url="http://test") as client:
        yield client

@pytest.fixture(scope="function", autouse=True)
async def db_pool():
    """Create a function-scoped database pool."""
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,  # Use same DSN as DocumentProcessor
        min_size=1,
        max_size=10
    )
    yield pool
    await pool.close()  # Ensures connections are released

@pytest.fixture
def generate_test_token():
    def _generate_test_token(user_id: int, role: str = "ADMIN", exp: timedelta = timedelta(hours=1)):
        payload = {
            "user_id": user_id,
            "role": role,
            "exp": (datetime.now(timezone.utc) + exp).timestamp(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return _generate_test_token

@pytest.fixture(autouse=True)
async def setup_cache():
    """Setup and teardown FastAPI Cache for tests."""
    FastAPICache.init(RedisBackend())
    yield
    await FastAPICache.clear()

@pytest.fixture(autouse=True)
async def cleanup_lambda_artifacts():
    yield
    await delete_processing_artifacts()  # Mock or define this cleanup logic.

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    import asyncio
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

# Add mock_document_processor fixture
from unittest.mock import AsyncMock

@pytest.fixture
async def mock_document_processor(mocker):
    """Mock DocumentProcessor class."""
    mock_processor = mocker.patch('src.document.document_processor.DocumentProcessor', autospec=True)
    mock_processor_instance = mock_processor.return_value
    mock_processor_instance.store_document = AsyncMock(return_value="mock_document_id")
    return mock_processor_instance

# Update test_client fixture to use mock_document_processor
@pytest.fixture
async def test_client(mock_document_processor):
    """Create test client for FastAPI app."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# Add test client fixture for FastAPI tests
@pytest.fixture
async def async_client():
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url="http://testserver") as client:
        yield client

from datetime import datetime, timezone, timedelta
import jwt

@pytest.fixture
def test_token():
    secret_key = settings.jwt_secret_key
    payload = {
        "user_id": "test_user",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")

@pytest.fixture
def generate_test_token():
    def _generate_test_token(user_id: int, role: str = "ADMIN", exp: timedelta = timedelta(hours=1)):
        payload = {
            "user_id": user_id,
            "role": role,
            "exp": (datetime.now(timezone.utc) + exp).timestamp(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return _generate_test_token

@pytest.fixture
def mock_settings(mocker):
    """Mock Settings class."""
    mocker.patch.object(settings, 'some_setting', 'mocked_value')
    return settings

@pytest.fixture(autouse=True)
async def cleanup_lambda_artifacts():
    yield
    await delete_processing_artifacts()  # Mock or define this cleanup logic.

@pytest.fixture(autouse=True)
async def cleanup_database():
    yield
    # Perform any necessary cleanup here
    # Since we're rolling back transactions, the database should be clean
    # For other resources like files or caches, add cleanup code here

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add any existing initialization from __init__.py if needed

@pytest.fixture(scope="session")
def test_db():
    engine = create_engine("sqlite:///:memory:")
    yield engine
    engine.dispose()

@pytest.fixture(scope="function")
def session(test_db):
    Session = sessionmaker(bind=test_db)
    session = Session()
    yield session
    session.close()

@pytest.fixture(scope="function")
async def async_fixture(event_loop):
    result = await some_async_setup()
    yield result
    await some_async_teardown(result)

from httpx import AsyncClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from src.app_factory import create_app
from src.document.document_processor import DocumentProcessor
from unittest.mock import AsyncMock

@pytest.fixture
async def test_client():
    # Create app instance
    app = create_app()

    # Mock and initialize app state
    app.state.document_processor = AsyncMock(spec=DocumentProcessor)

    # Use test client
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture(scope="function", autouse=True)
async def cleanup_test_partitions(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE test_partition CASCADE")

@pytest.fixture
async def create_test_partition():
    institution_id = generate_unique_institution_id()
    await create_partition(institution_id)
    return institution_id

async def create_partition(partition_name):
    async with db_pool.acquire() as conn:
        await conn.execute(f"CREATE TABLE IF NOT EXISTS {partition_name}")

async def create_institution_partition(institution_id):
    await create_partition(f"institution_{institution_id}")

@pytest.fixture
async def cleanup_test_partitions():
    await drop_all_test_partitions()

async def drop_all_test_partitions():
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS test_partition CASCADE")

@pytest.fixture
async def create_partition(db_pool):
    """
    Create a database partition if it does not already exist.
    """
    async with db_pool.acquire() as conn:
        partition_key = "test_partition"
        await conn.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = '{partition_key}') THEN
                    CREATE TABLE partition_{partition_key} PARTITION OF your_partitioned_table FOR VALUES IN ('{partition_key}');
                END IF;
            END $$;
        """)

@pytest.fixture
async def manage_partition_transaction(db_pool):
    """
    Manage partition creation and operations within a transaction.
    """
    async with db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS partition_test (...)")
            yield
            await transaction.commit()
        except Exception as e:
            await transaction.rollback()
            raise e

@pytest.fixture(scope="function", autouse=True)
async def cleanup_partitions(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE your_partitioned_table CASCADE")

@pytest.fixture
async def partition_test_data(db_pool):
    """
    Insert test data into the appropriate partition for testing.
    """
    async with db_pool.acquire() as conn:
        partition_key = "test_partition"
        await conn.execute(f"""
            INSERT INTO partitioned_table (partition_key, other_column)
            VALUES ('{partition_key}', 'test_data');
        """)
        yield partition_key
        await conn.execute(f"""
            DELETE FROM partitioned_table WHERE partition_key = '{partition_key}';
        """)

@pytest.fixture(autouse=True)
async def setup_cache():
    """Setup and teardown FastAPI Cache for tests."""
    FastAPICache.init(InMemoryBackend())
    yield
    await FastAPICache.clear()

@pytest.fixture
def mock_trigger_lambda(monkeypatch):
    def fake_trigger_lambda(*args, **kwargs):
        return {"status": "success"}
    monkeypatch.setattr("src.document.document_processor.trigger_lambda", fake_trigger_lambda)

from unittest.mock import AsyncMock

@pytest.fixture
async def mock_document_processor(mocker):
    """Mock DocumentProcessor class."""
    mock_processor = mocker.patch('src.document.document_processor.DocumentProcessor', autospec=True)
    mock_processor_instance = mock_processor.return_value
    mock_processor_instance.store_document = AsyncMock(return_value="mock_document_id")
    return mock_processor_instance

import pytest
from unittest.mock import patch

@pytest.fixture
def mock_role_check():
    """Mock the role_check function to always return True."""
    with patch('src.api.routes.institutions.role_check', return_value=True):
        yield

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from contextlib import asynccontextmanager
from src.app_factory import create_app
from src.document.document_processor import DocumentProcessor, ProcessorConfig
from src.config.settings import settings

@pytest.fixture(scope="session", autouse=True)
async def initialize_app():
    """Initialize the app and DocumentProcessor before any tests run."""
    app = create_app()
    async with asynccontextmanager(app.lifespan)(app):
        yield app

@pytest.fixture
async def test_client(initialize_app):
    """Create test client with initialized DocumentProcessor."""
    async with AsyncClient(app=initialize_app, base_url="http://test") as client:
        yield client

import jwt
from datetime import datetime, timedelta, timezone
from src.config.settings import settings

@pytest.fixture
def generate_test_token():
    def _generate_test_token(user_id: int, role: str = "ADMIN", exp: timedelta = timedelta(hours=1)):
        payload = {
            "user_id": user_id,
            "role": role,
            "exp": (datetime.now(timezone.utc) + exp).timestamp(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return _generate_test_token

@pytest.fixture
async def processor_config():
    config = ProcessorConfig(
        document_bucket="test-bucket",
        confidence_threshold=0.8,
        batch_size=5,
        max_connections=5,
        min_connections=2,
        cleanup_batch_size=100,
    )
    yield config
    await config.cleanup()

import pytest
from datetime import datetime, timedelta
import jwt
from fastapi.testclient import TestClient
from redis import Redis
from fastapi_limiter import FastAPILimiter

from src.config.settings import settings

@pytest.fixture(autouse=True)
def auth_headers():
    token = jwt.encode(
        {
            "sub": "test_user",
            "role": "ADMIN",
            "exp": datetime.utcnow() + timedelta(hours=1)
        },
        settings.jwt_secret_key,
        algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def test_client(auth_headers):
    app = create_app()
    with TestClient(app) as client:
        client.headers.update(auth_headers)
        yield client

@pytest.fixture(autouse=True)
def mock_document_processor(mocker):
    mock = mocker.patch('src.document.document_processor.DocumentProcessor')
    mock.return_value.trigger_lambda_task.return_value = True
    mock.return_value.initialize.return_value = True
    return mock

@pytest.fixture(autouse=True)
async def setup_redis():
    redis = Redis(host='localhost', port=6379, db=0)
    await FastAPILimiter.init(redis)
    yield
    await redis.flushdb()
    await redis.close()

@pytest.fixture(autouse=True)
def mock_aws_services(mocker):
    mock_s3 = mocker.patch('boto3.client')
    mock_s3.return_value.upload_fileobj.return_value = None
    mock_s3.return_value.download_fileobj.return_value = None
    return mock_s3