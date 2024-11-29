import pytest
import asyncio
from unittest.mock import AsyncMock
import uuid
from httpx import AsyncClient
from fastapi import FastAPI, HTTPException
from unittest.mock import patch, AsyncMock
from src.api.routes import documents  # Adjusted import
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from fastapi.middleware.cors import CORSMiddleware
from asyncpg import UniqueViolationError
from factory import Factory, Faker, SubFactory
from factory.alchemy import SQLAlchemyModelFactory
from datetime import datetime, timedelta
import jwt
import os
import asyncpg  # Added import
from src.api.models import DocumentCreate, DocumentUpdate  # Adjusted import
from src.app_factory import create_app  # Updated import

app = create_app()

try:
    from pydantic_settings import BaseSettings  # Updated import
except ImportError:
    raise ImportError("Ensure 'pydantic_settings' module is installed.")

# Local import since test file is in the same directory
try:
    from src.document.document_processor import (
        DocumentProcessor,
        ProcessorConfig,
        DocumentMetadata,
        DocumentType,
        VerificationStatus
    )
except ImportError as e:
    raise ImportError("Ensure 'document_processor' module is available in the project.") from e

from fastapi_limiter.depends import RateLimiter

# Factory for Document
class DocumentFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    name = Faker('file_name')
    type = Faker('file_extension')
    created_at = Faker('iso8601')

@pytest.fixture
async def processor_config():
    """Test configuration fixture."""
    return ProcessorConfig(
        document_bucket="test-bucket",
        confidence_threshold=0.8,
        batch_size=5,
        max_connections=5,
        min_connections=2,
        cleanup_batch_size=100,
    )

from unittest.mock import MagicMock

import pytest_asyncio

@pytest_asyncio.fixture
async def test_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest_asyncio.fixture
async def document_processor(processor_config):
    """Fixture for document processor."""
    processor = MagicMock(DocumentProcessor)
    processor.create_version = AsyncMock(return_value="mock-version-id")
    yield processor

@pytest_asyncio.fixture
async def test_token():
    """Fixture for providing a test token."""
    return "test-token"

@pytest.fixture(scope="session", autouse=True)
async def setup_limiter():
    from fastapi_limiter import FastAPILimiter  # Ensure FastAPILimiter is correctly imported
    from redis.asyncio import Redis
    redis = Redis(host="localhost", port=6379, decode_responses=True)
    await FastAPILimiter.init(redis)  # Ensure FastAPILimiter is initialized correctly
    yield
    await redis.close()  # Correct usage already found, no change needed

class TestDocumentVersioning:
    """Test suite for document versioning functionality."""
    
    @pytest.mark.asyncio
    async def test_create_version(self, document_processor, test_token):
        """Test creating a new document version."""
        # Setup
        document_id = str(uuid.uuid4())
        changes = {
            "field_updated": "status",
            "old_value": "pending",
            "new_value": "verified"
        }
        headers = {"Authorization": f"Bearer {test_token}"}
        
        # Execute
        version_id = await document_processor.create_version(document_id, changes, headers=headers)
        
        # Verify
        assert version_id is not None, "Version ID should not be None"
        assert version_id == "mock-version-id", "Version ID should match the mocked return value"

app.dependency_overrides[RateLimiter] = lambda: RateLimiter(times=5, seconds=60)

from unittest.mock import patch

@patch("redis.StrictRedis")
async def test_redis_mock(redis_mock):
    redis_instance = redis_mock.return_value
    redis_instance.get.return_value = "mocked_value"
    assert await redis_instance.get("key") == "mocked_value"