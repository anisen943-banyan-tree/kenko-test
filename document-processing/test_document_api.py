import pytest
from httpx import AsyncClient
from document_api import app

@pytest.fixture
def mock_document_id():
    # This would be a mock or fixture to represent an existing document ID for testing
    return "mock-document-id"

@pytest.mark.asyncio
async def test_upload_document():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/upload",
            headers={"Authorization": "Bearer testtoken"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 201
        assert "document_id" in response.json()
        assert response.json()["status"] == "Pending"

@pytest.mark.asyncio
async def test_get_document_status(mock_document_id):
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/status/{mock_document_id}", headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 200
        assert response.json()["document_id"] == mock_document_id

@pytest.mark.asyncio
async def test_unauthorized_access():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/upload",
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
        assert response.status_code == 401

@pytest.mark.asyncio
async def test_invalid_document_type():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/upload",
            headers={"Authorization": "Bearer testtoken"},
            files={"file": ("test.txt", b"test content", "text/plain")}
        )
        assert response.status_code == 400

@pytest.mark.asyncio
async def test_non_existent_document_id():
    non_existent_document_id = "non-existent-document-id"
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/status/{non_existent_document_id}", headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 404