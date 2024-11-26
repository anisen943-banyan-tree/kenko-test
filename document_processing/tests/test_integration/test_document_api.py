import pytest
import pytest_asyncio
import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

try:
    from pydantic_settings import BaseSettings  # Updated import
except ImportError:
    raise ImportError("Ensure 'pydantic_settings' module is installed.")

from httpx import AsyncClient
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from fastapi.middleware.cors import CORSMiddleware
from asyncpg import UniqueViolationError
from factory import Factory, Faker, SubFactory
from factory.alchemy import SQLAlchemyModelFactory
import jwt
import os
from redis.asyncio import Redis
from fastapi_limiter.depends import RateLimiter

from src.document import document_processor
from src.api.routes import documents  # Adjusted import
from src.api.models import DocumentCreate, DocumentUpdate
from src.app_factory import create_app  # Updated import

app = create_app()

app.include_router(documents.router, prefix="/api/v1/documents")  # Ensure the route is registered

@pytest.fixture(scope="session", autouse=True)
async def setup_limiter():
    from fastapi_limiter import FastAPILimiter
    redis = Redis(host="localhost", port=6379, decode_responses=True)
    await FastAPILimiter.init(redis)
    yield
    await redis.close()

@pytest.fixture(scope="module", autouse=True)
async def setup_rate_limiter():
    try:
        redis = Redis(host='localhost', port=6379, decode_responses=True)
        from fastapi_limiter import FastAPILimiter  # Ensure FastAPILimiter is imported
        await FastAPILimiter.init(redis)  # Ensure FastAPILimiter is initialized correctly
        yield
    except Exception as e:
        pytest.fail(f"Failed to connect to Redis: {e}")
    finally:
        await redis.close()  # Correct usage

@pytest.fixture
def mock_document_id():
    # This would be a mock or fixture to represent an existing document ID for testing
    return "mock-document-id"

class BaseTestCase:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_and_teardown(self):
        async with AsyncClient(app=app, base_url="http://test") as client:
            self.client = client
            yield

# Add logging configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@pytest_asyncio.fixture
async def test_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture(autouse=True)
async def mock_dependencies():
    app.state.pool = AsyncMock()  # Mock database pool
    yield

async def process_document(document_id: str):
    """Mock implementation for testing"""
    return {"status": "processed", "document_id": document_id}

class TestDocumentAPI(BaseTestCase):
    # ...existing code...

    @pytest.mark.asyncio
    async def test_upload_document(self, test_client, test_token):
        url = "/api/v1/documents/upload"  # Updated route
        logger.debug(f"Testing upload endpoint: {url}")
        response = await test_client.post(
            url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        logger.debug(f"Upload response status: {response.status_code}")
        logger.debug(f"Upload response content: {response.text}")
        
        assert response.status_code == 201, f"Upload failed with status {response.status_code}: {response.text}"
        response_data = response.json()
        assert "document_id" in response_data, f"Missing document_id in response: {response_data}"
        assert response_data["status"] == "Pending"

    @pytest.mark.asyncio
    async def test_get_document_status(self, test_client, test_token, mock_document_id):
        url = f"/api/v1/documents/status/{mock_document_id}"  # Updated route
        logger.debug(f"Testing status endpoint: {url}")
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {test_token}"}
            )
            logger.debug(f"Status response: {response.status_code} - {response.text}")
            
            assert response.status_code == 200, f"Status check failed with status {response.status_code}: {response.text}"
            response_data = response.json()
            assert "status" in response_data, f"Missing status in response: {response_data}"
            assert response_data["status"] in ["Pending", "Completed", "Failed"]

    @pytest.mark.asyncio
    async def test_unauthorized_access(self, test_client):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/documents/upload",  # Ensure the correct endpoint is used
                files={"file": ("test.pdf", b"test content", "application/pdf")}
            )
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_document_type(self, test_client, test_token):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/documents/upload",
                headers={"Authorization": f"Bearer {test_token}"},
                files={"file": ("test.txt", b"test content", "text/plain")}
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_non_existent_document_id(self, test_client, test_token):
        non_existent_document_id = "non-existent-document-id"
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                f"/documents/status/{non_existent_document_id}", 
                headers={"Authorization": f"Bearer {test_token}"}
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        url = "/api/v1/documents/health"  # Updated route
        logger.debug(f"Testing health endpoint: {url}")
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(url)
            logger.debug(f"Health check response: {response.status_code} - {response.text}")
            
            assert response.status_code == 200, f"Health check failed: {response.text}"
            assert response.json() == {"status": "ok"}

    @patch("src.document.document_processor.trigger_lambda_task")
    @pytest.mark.asyncio
    async def test_lambda_service_mock(self, mock_trigger_lambda):
        mock_trigger_lambda.return_value = {"results": "mocked_data"}
        mock_trigger_lambda.side_effect = AsyncMock(return_value={"results": "mocked_data"})
        
        response = await process_document("test_document_id")
        assert response == {"results": "mocked_data"}
        await mock_trigger_lambda.assert_called_once_with("test_document_id")

    @patch("src.document.document_processor.trigger_lambda_task")
    @pytest.mark.asyncio
    async def test_lambda_task_failure(self, mock_trigger_lambda):
        mock_trigger_lambda.side_effect = AsyncMock(side_effect=RuntimeError("Lambda task failed."))
        
        with pytest.raises(RuntimeError) as exc_info:
            await process_document("test_document_id")
        assert str(exc_info.value) == "Lambda task failed."

    @pytest.fixture(autouse=True)
    async def cleanup_lambda_artifacts(self):
        """Clean up any processing artifacts created during the test run."""
        # Setup - can add any pre-test initialization here
        yield
        # Cleanup mock data
        if hasattr(document_processor, '_mock_data'):
            document_processor._mock_data = {}

    @pytest.mark.asyncio
    async def test_complete_upload_workflow(self, test_client, test_token):
        # Test full upload -> process -> status check flow
        upload_url = "/api/v1/documents/upload"
        status_url = "/api/v1/documents/status/{document_id}"
        
        # Upload document
        response = await test_client.post(
            upload_url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 201
        document_id = response.json()["document_id"]
        
        # Check status
        response = await test_client.get(
            status_url.format(document_id=document_id),
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        assert response.json()["status"] in ["Pending", "Completed", "Failed"]

    @pytest.mark.asyncio
    async def test_database_persistence(self, test_client, test_token):
        # Test actual database operations
        upload_url = "/api/v1/documents/upload"
        
        # Upload document
        response = await test_client.post(
            upload_url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 201
        document_id = response.json()["document_id"]
        
        # Verify document in database (mocked)
        document = await app.state.pool.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
        assert document is not None
        assert document["id"] == document_id

    @pytest.mark.asyncio
    async def test_lambda_integration(self, test_client):
        # Test actual Lambda service interaction
        with patch("src.document.document_processor.trigger_lambda_task") as mock_trigger_lambda:
            mock_trigger_lambda.return_value = {"results": "mocked_data"}
            response = await process_document("test_document_id")
            assert response == {"results": "mocked_data"}
            await mock_trigger_lambda.assert_called_once_with("test_document_id")

    @pytest.mark.asyncio
    async def test_multi_document_workflow(self, test_client, test_token):
        # Test handling multiple documents
        upload_url = "/api/v1/documents/upload"
        status_url = "/api/v1/documents/status/{document_id}"
        
        document_ids = []
        for i in range(3):
            response = await test_client.post(
                upload_url,
                headers={"Authorization": f"Bearer {test_token}"},
                files={"file": (f"test_{i}.pdf", b"test content", "application/pdf")}
            )
            assert response.status_code == 201
            document_ids.append(response.json()["document_id"])
        
        for document_id in document_ids:
            response = await test_client.get(
                status_url.format(document_id=document_id),
                headers={"Authorization": f"Bearer {test_token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] in ["Pending", "Completed", "Failed"]

# Add route validation helper
async def validate_routes(client):
    """Validate that all required routes are registered"""
    routes = [
        "/documents/upload",
        "/documents/status/{document_id}",
        "/documents/health"
    ]
    logger.debug("Validating routes...")
    for route in routes:
        response = await client.get(route.replace("{document_id}", "test"))
        logger.debug(f"Route {route} status: {response.status_code}")
        assert response.status_code != 404, f"Route {route} not found"

@pytest.mark.asyncio
async def test_route_validation(test_client):
    await validate_routes(test_client)

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