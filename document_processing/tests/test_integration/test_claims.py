import pytest
import pytest_asyncio
import asyncio
import os
from httpx import AsyncClient
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
import jwt
import logging
import asyncpg
from unittest.mock import AsyncMock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "claimsdb_test",
    "user": "claimsuser",
    "password": os.getenv("RDS_PASSWORD", "default_password")
}

from src.app_factory import create_app  # Corrected import path

app = create_app()

@pytest.fixture
async def db_pool():
    """Create and clean test database"""
    pool = await asyncpg.create_pool(**TEST_DB_CONFIG)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE claims, claim_documents, claim_processing CASCADE")
    yield pool
    await pool.close()

@pytest_asyncio.fixture
async def test_client():
    """Create test client for FastAPI app."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def test_token():
    """Generate test JWT token."""
    payload = {
        "user_id": "test_user",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    return jwt.encode(payload, "your-secret-key", algorithm="HS256")

@pytest.fixture
def sample_claim_data():
    """Sample data for a claim with realistic fields."""
    current_time = datetime.now(timezone.utc)
    return {
        "claim_type": "medical",
        "member_id": "12345",
        "hospital_id": "67890",
        "admission_date": current_time.isoformat(),
        "discharge_date": (current_time + timedelta(days=1)).isoformat(),
        "total_amount": 1000.0,
        "documents": [{"id": "doc1", "type": "report"}]
    }

@pytest.fixture
async def mock_async_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client

@pytest.mark.parametrize("amount, expected_status", [
    (1000, 200),
    (0, 400),
    (-100, 400),
    (None, 400)
])
@pytest.mark.asyncio
async def test_claim_amount_validation(test_client: AsyncClient, amount: float, expected_status: int):
    """Test validation of claim amount. Ensures that invalid amounts result in the appropriate HTTP status."""
    logger.info("Testing claim amount validation with amount: %s", amount)
    claim_data = {
        "claim_type": "medical",
        "member_id": "12345",
        "hospital_id": "67890",
        "admission_date": datetime.now(timezone.utc).isoformat(),
        "discharge_date": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "total_amount": amount,
        "documents": [{"id": "doc1", "type": "report"}]
    }
    response = await test_client.post("/create_claim", json=claim_data)
    assert response.status_code == expected_status, f"Unexpected status code for amount {amount}"

@pytest.mark.asyncio
async def test_claim_creation(test_client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a new claim."""
    logger.info("Testing claim creation with data: %s", sample_claim_data)
    headers = {"Authorization": f"Bearer {test_token}"}
    response = await test_client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 201, "Expected claim creation to return status 201"
    response_data = response.json()
    assert "claim_id" in response_data, "Response should contain 'claim_id'"
    assert response_data.get("claim_id"), "Claim ID should be returned in response"

@pytest.mark.asyncio
async def test_claim_retrieval(test_client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test retrieval of a claim."""
    logger.info("Testing claim retrieval")
    headers = {"Authorization": f"Bearer {test_token}"}
    create_response = await test_client.post("/create_claim", json=sample_claim_data, headers=headers)
    claim_id = create_response.json().get("claim_id")
    
    response = await test_client.get(f"/claims/{claim_id}", headers=headers)
    assert response.status_code == 200, "Expected claim retrieval to return status 200"
    response_data = response.json()
    assert response_data.get("claim_id") == claim_id, "Claim ID mismatch in retrieval"

@pytest.mark.asyncio
async def test_claim_update_status(test_client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test updating the status of a claim."""
    logger.info("Testing claim status update")
    headers = {"Authorization": f"Bearer {test_token}"}
    create_response = await test_client.post("/create_claim", json=sample_claim_data, headers=headers)
    claim_id = create_response.json().get("claim_id")
    
    update_data = {"status": "PROCESSING"}
    response = await test_client.put(f"/claims/{claim_id}/status", json=update_data, headers=headers)
    assert response.status_code == 200, "Expected claim status update to return status 200"
    response_data = response.json()
    assert response_data.get("status") == "PROCESSING", "Claim status mismatch after update"

@pytest.mark.asyncio
async def test_invalid_claim_type(test_client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a claim with an invalid claim type."""
    logger.info("Testing claim creation with invalid claim type")
    headers = {"Authorization": f"Bearer {test_token}"}
    sample_claim_data["claim_type"] = "invalid_type"
    response = await test_client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 400, f"Expected status 400 for invalid claim type, but got {response.status_code}"

@pytest.mark.asyncio
async def test_future_admission_date(test_client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a claim with a future admission date."""
    logger.info("Testing claim creation with future admission date")
    headers = {"Authorization": f"Bearer {test_token}"}
    sample_claim_data["admission_date"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = await test_client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 400, f"Expected status 400 for future admission date, but got {response.status_code}"

@pytest.mark.asyncio
async def test_unauthorized_claim_creation(test_client: AsyncClient, sample_claim_data: Dict[str, Any]):
    """Test unauthorized claim creation."""
    logger.info("Testing unauthorized claim creation")
    response = await test_client.post("/create_claim", json=sample_claim_data)
    assert response.status_code == 401, f"Expected status 401 for unauthorized claim creation, but got {response.status_code}"

# Example test case
@pytest.mark.asyncio
async def test_example(test_client, test_token):
    response = await test_client.get(
        "/some-endpoint", 
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200