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

@pytest.fixture(scope='session', autouse=True)
def set_env_vars():
    # Update the JWT_SECRET_KEY to use the lowercase "jwt_secret_key" attribute
    os.environ['JWT_SECRET_KEY'] = settings.jwt_secret_key
    os.environ['DATABASE_URL'] = settings.database_url
    os.environ['ENVIRONMENT'] = settings.environment
    os.environ['TEST_ENVIRONMENT'] = 'test'
    os.environ['ANOTHER_ENV_VAR'] = 'another_value'  # Example additional env var
    
    logger.info("Test environment variables set.")

@pytest.fixture(scope="session")
async def db_pool():
    """Create a session-scoped database pool."""
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10
    )
    yield pool
    await pool.close()

@pytest.fixture
async def db_pool_transaction(db_pool):
    """Start a transaction for each test and roll it back afterward."""
    async with db_pool.acquire() as connection:
        transaction = connection.transaction()
        await transaction.start()
        yield connection  # Provide the connection to the test
        await transaction.rollback()  # Roll back after the test

@pytest.fixture
async def setup_test_data(db_pool_transaction):
    """Initialize test data in the database."""
    connection = db_pool_transaction
    # Example: Insert test data
    await connection.execute("""
        INSERT INTO users (id, name, email) VALUES ($1, $2, $3)
    """, 1, 'Test User', 'test@example.com')
    # Add more test data as required
    yield
    # No need for cleanup; transaction rollback will handle it

# Create a session-scoped event loop fixture
@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    import asyncio
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

# Update initialize_app to use session-scoped event_loop
@pytest.fixture(scope="session")
async def initialize_app(event_loop, db_pool):
    """Initialize the FastAPI app with proper event loop and db_pool."""
    from src.main import app
    from src.document.document_processor import ProcessorConfig

    # Create ProcessorConfig instance
    processor_config = ProcessorConfig()

    # Initialize DocumentProcessor with db_pool and processor_config
    app.state.document_processor = DocumentProcessor(pool=db_pool, config=processor_config)

    await app.router.startup()
    yield app
    await app.router.shutdown()

# Add test client fixture for FastAPI tests
@pytest.fixture
async def test_client(initialize_app):
    """Create test client for FastAPI app."""
    from httpx import AsyncClient
    async with AsyncClient(app=initialize_app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

from datetime import datetime, timezone

@pytest.fixture
def test_token():
    """Generate test JWT token."""
    import jwt
    from datetime import datetime, timedelta
    
    payload = {
        "user_id": "test_user",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    return jwt.encode(payload, os.getenv('JWT_SECRET_KEY'), algorithm="HS256")

@pytest.fixture
def mock_settings(mocker):
    """Mock Settings class."""
    mocker.patch.object(settings, 'some_setting', 'mocked_value')
    return settings

@pytest.fixture(autouse=True)
async def cleanup_database():
    """Clean up after each test."""
    yield
    # Perform any necessary cleanup here
    # Since we're rolling back transactions, the database should be clean
    # For other resources like files or caches, add cleanup code here

import pytest
from src.main import app
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

@pytest.fixture
async def document_processor():
    processor = DocumentProcessor()  # Proper initialization
    yield processor

@pytest.fixture(scope="function", autouse=True)
async def db_session(db_pool):
    async with db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        yield conn
        await tx.rollback()

from httpx import AsyncClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

@pytest.fixture
async def test_client(app):
    FastAPICache.init(RedisBackend(redis.StrictRedis(host="localhost")), prefix="test-cache")
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client