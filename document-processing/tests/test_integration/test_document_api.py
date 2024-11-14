import pytest
from httpx import AsyncClient
from main import app  # Correct import path

@pytest.fixture
def mock_document_id():
    # This would be a mock or fixture to represent an existing document ID for testing
    return "mock-document-id"

@pytest.mark.asyncio
async def test_upload_document(test_client, test_token):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files={"file": ("test.pdf", b"test content", "application/pdf")}
        )
    assert response.status_code == 201
    assert "document_id" in response.json()
    assert response.json()["status"] == "Pending"

@pytest.mark.asyncio
async def test_get_document_status(test_client, test_token, mock_document_id):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get(
            f"/status/{mock_document_id}",
            headers={"Authorization": f"Bearer {test_token}"}
        )
    assert response.status_code == 200
    assert "status" in response.json()
    assert response.json()["status"] in ["Pending", "Completed", "Failed"]

@pytest.mark.asyncio
async def test_unauthorized_access(test_client):
    response = await test_client.post(
        "/upload",
        files={"file": ("test.pdf", b"test content", "application/pdf")}
    )
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_invalid_document_type(test_client, test_token):
    response = await test_client.post(
        "/upload",
        headers={"Authorization": f"Bearer {test_token}"},
        files={"file": ("test.txt", b"test content", "text/plain")}
    )
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_non_existent_document_id(test_client, test_token):
    non_existent_document_id = "non-existent-document-id"
    response = await test_client.get(
        f"/status/{non_existent_document_id}", 
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 404