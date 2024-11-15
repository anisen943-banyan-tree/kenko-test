import pytest
from httpx import AsyncClient
from document_processing.src.api.main import app
from document_processing.src.api.limiter import FastAPILimiter, RateLimiter, get_remote_address
import aioredis

@pytest.fixture(scope="module", autouse=True)
async def setup_rate_limiter():
    try:
        redis = await aioredis.create_redis_pool("redis://localhost")
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
            app.dependency_overrides[RateLimiter] = lambda: None
            self.client = client
            yield
            await self.client.aclose()

@pytest.mark.asyncio
class TestDocumentAPI(BaseTestCase):
    async def test_upload_document(self, test_token):
        response = await self.client.post(
            "/upload",
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

    async def test_health_check(self):
        response = await self.client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}