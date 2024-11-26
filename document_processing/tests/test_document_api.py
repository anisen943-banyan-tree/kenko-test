import pytest
import pytest_asyncio
import logging
from httpx import AsyncClient
from fastapi import FastAPI
from unittest.mock import patch, AsyncMock, MagicMock
from redis.asyncio import Redis
from fastapi_limiter.depends import RateLimiter
from fastapi_limiter import FastAPILimiter
from src.app_factory import create_app
from src.api.routes import documents
from factory import Factory, Faker

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create app instance
app = create_app()
app.include_router(documents.router, prefix="/api/v1/documents")
@pytest.fixture(scope="session", autouse=True)
async def setup_limiter():
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
        await redis.close()

@pytest_asyncio.fixture
async def test_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture(autouse=True)
async def mock_dependencies():
    try:
        app.state.pool = AsyncMock()
    except Exception as e:
        logger.error(f"Error mocking dependencies: {e}")
    yield

@pytest.fixture
def patch_trigger_lambda_task():
    with patch("src.document.document_processor.trigger_lambda_task", new_callable=AsyncMock) as mock_task:
        mock_task.return_value = "Task triggered successfully"
        yield mock_task

@pytest.fixture
def mock_document_id():
    return "mock-document-id"
class BaseTestCase:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_and_teardown(self):
        async with AsyncClient(app=app, base_url="http://test") as client:
            self.client = client
            yield

    @staticmethod 
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
class TestDocumentAPI(BaseTestCase):
    async def test_upload_document(self, test_client, test_token):
        url = "/api/v1/documents/upload"
        logger.debug(f"Testing upload endpoint: {url}")
        response = await test_client.post(
            url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        logger.debug(f"Upload response: {response.status_code} - {response.text}")
        assert response.status_code == 201
        assert "document_id" in response.json()
        assert response.json()["status"] == "Pending"

    async def test_unauthorized_access(self, test_client):
        response = await test_client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_document_status(self, test_client, test_token, mock_document_id):
        url = f"/api/v1/documents/status/{mock_document_id}"
        logger.debug(f"Testing status endpoint: {url}")
        response = await test_client.get(
            url,
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        response_data = response.json()
        assert "status" in response_data
        assert response_data["status"] in ["Pending", "Completed", "Failed"]

    async def test_invalid_document_type(self, test_client, test_token):
        response = await test_client.post(
            "/api/v1/documents/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.txt", b"test content", "text/plain")}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_health_check(self, test_client):
        url = "/api/v1/documents/health"
        logger.debug(f"Testing health endpoint: {url}")

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(url)
            logger.debug(f"Health check response: {response.status_code} - {response.text}")

            assert response.status_code == 200, f"Health check failed: {response.text}"
            assert response.json() == {"status": "ok"}  # Changed from 'healthy' to 'ok'}

    async def test_document_route(self, test_client):
        response = await test_client.post("/documents", json={"data": "test"})
        assert response.status_code == 200
        assert response.json() == {"message": "Document processed successfully"}

    @patch("src.document.document_processor.trigger_lambda_task")
    @pytest.mark.asyncio
    async def test_lambda_service_mock(self, mock_trigger_lambda, test_client):
        mock_trigger_lambda.side_effect = AsyncMock(return_value={"results": "mocked_data"})
        response = await self.process_document("test_document_id")
        assert response == {"results": "mocked_data"}
        await mock_trigger_lambda.assert_called_once_with("test_document_id")

    @patch("src.document.document_processor.trigger_lambda_task")
    @pytest.mark.asyncio
    async def test_lambda_task_failure(self, mock_trigger_lambda, test_client):
        mock_trigger_lambda.side_effect = AsyncMock(side_effect=RuntimeError("Lambda task failed."))
        with pytest.raises(RuntimeError) as exc_info:
            await self.process_document("test_document_id")
        assert str(exc_info.value) == "Lambda task failed."

    @pytest.fixture(autouse=True)
    async def cleanup_lambda_artifacts(self):
        yield
        if hasattr(document_processor, '_mock_data'):
            document_processor._mock_data = {}

    async def process_document(self, document_id: str):
        """Mock implementation for testing"""
        return {"status": "processed", "document_id": document_id}

    async def test_upload_document_validation(self, test_client, test_token):
        # Test input validation
        url = "/api/v1/documents/upload"
        response = await test_client.post(
            url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("", b"", "application/pdf")}
        )
        assert response.status_code == 422  # Unprocessable Entity

        # Test file type validation
        response = await test_client.post(
            url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.txt", b"test content", "text/plain")}
        )
        assert response.status_code == 400  # Bad Request

        # Test file size limits
        large_content = b"a" * (10 * 1024 * 1024 + 1)  # 10MB + 1 byte
        response = await test_client.post(
            url,
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("large_test.pdf", large_content, "application/pdf")}
        )
        assert response.status_code == 413  # Payload Too Large

    async def test_document_status_transitions(self, test_client, test_token):
        # Test status state machine
        document_id = "mock-document-id"
        url = f"/api/v1/documents/status/{document_id}"
        response = await test_client.get(
            url,
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["status"] in ["Pending", "Completed", "Failed"]

        # Test status updates
        # Assuming there's an endpoint to update status for testing purposes
        update_url = f"/api/v1/documents/status/{document_id}/update"
        for status in ["Pending", "Completed", "Failed"]:
            response = await test_client.post(
                update_url,
                headers={"Authorization": f"Bearer {test_token}"},
                json={"status": status}
            )
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["status"] == status

    async def test_health_check_unit(self, test_client):
        # Basic health check response format
        url = "/api/v1/documents/health"
        response = await test_client.get(url)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_authorization_logic(self, test_client):
        # Test auth token validation
        url = "/api/v1/documents/upload"
        response = await test_client.post(
            url,
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 401  # Unauthorized

        # Test permission checks
        # Assuming there's a role-based access control
        response = await test_client.post(
            url,
            headers={"Authorization": "Bearer invalid_token"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 403  # Forbidden

class DocumentFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    name = Faker('file_name')
    type = Faker('file_extension')
    created_at = Faker('iso8601')