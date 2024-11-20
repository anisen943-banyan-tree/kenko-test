import pytest
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
import asyncio
import asyncpg  # Added import
from src.api.models import DocumentCreate, DocumentUpdate
from src.main import app  # Updated import

try:
    from pydantic_settings import BaseSettings  # Updated import
except ImportError:
    raise ImportError("Ensure 'pydantic_settings' module is installed.")

from redis.asyncio import Redis
from fastapi_limiter.depends import RateLimiter

@pytest.fixture(scope="session", autouse=True)
async def setup_limiter():
    from fastapi_limiter import FastAPILimiter
    from redis.asyncio import Redis
    redis = Redis(host="localhost", port=6379, decode_responses=True)
    await FastAPILimiter.init(redis)
    yield
    await redis.close()

@pytest.fixture(scope="module", autouse=True)
async def setup_rate_limiter():
    try:
        redis = Redis(host='localhost', port=6379, decode_responses=True)
        await FastAPILimiter.init(redis, key_func=get_remote_address)
        yield
    except Exception as e:
        pytest.fail(f"Failed to connect to Redis: {e}")
    finally:
        redis.close()
        await redis.wait_closed()

@pytest.fixture
def mock_document_id():
    # This would be a mock or fixture to represent an existing document ID for testing
    return "mock-document-id"

class BaseTestCase:
    @pytest.fixture(autouse=True)
    async def setup_and_teardown(self):
        async with AsyncClient(app=app, base_url="http://test") as client:
            app.dependency_overrides[RateLimiter] = lambda: RateLimiter(times=5, seconds=60)
            self.client = client
            yield
            await self.client.aclose()

from fastapi.testclient import TestClient
from src.main import app  # Updated import

@pytest.mark.asyncio
class TestDocumentAPI(BaseTestCase):
    def setup_method(self):
        # Initialize the test client
        self.client = TestClient(app)

    @pytest.mark.asyncio
    async def test_upload_document(self, test_token):
        response = await self.client.post(
            "/documents/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 201
        assert "document_id" in response.json()
        assert response.json()["status"] == "Pending"

    async def test_get_document_status(self, test_token, mock_document_id):
        response = await self.client.get(
            f"/status/{mock_document_id}",
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        assert "status" in response.json()
        assert response.json()["status"] in ["Pending", "Completed", "Failed"]

    async def test_unauthorized_access(self):
        response = await self.client.post(
            "/upload",
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 401

    async def test_invalid_document_type(self, test_token):
        response = await self.client.post(
            "/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.txt", b"test content", "text/plain")}
        )
        assert response.status_code == 400

    async def test_non_existent_document_id(self, test_token):
        non_existent_document_id = "non-existent-document-id"
        response = await self.client.get(
            f"/status/{non_existent_document_id}", 
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_health_check(self):
        response = await self.client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

# Define allowed origins for testing
origins = [
    "https://yourdomain.com",
    "http://localhost",
]

# Factory for Document
class DocumentFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    name = Faker('file_name')
    type = Faker('file_extension')
    created_at = Faker('iso8601')