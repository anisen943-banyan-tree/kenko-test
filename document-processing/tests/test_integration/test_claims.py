import pytest
import asyncio
import os
from httpx import AsyncClient
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
import jwt
import logging
import asyncpg

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "claimsdb_test",
    "user": "claimsuser",
    "password": "Claims2024#Secure!"
}

@pytest.fixture
async def db_pool():
    """Create and clean test database"""
    pool = await asyncpg.create_pool(**TEST_DB_CONFIG)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE claims, claim_documents, claim_processing CASCADE")
    yield pool
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE claims, claim_documents, claim_processing CASCADE")
    await pool.close()

@pytest.fixture
def test_token():
    """Generate a test JWT token."""
    secret_key = os.getenv("JWT_SECRET_KEY", "default-test-key")
    payload = {
        "user_id": "test_user",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token

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
async def client():
    """Create an AsyncClient for testing"""
    async with AsyncClient(app=gateway_app, base_url="http://test") as client:
        yield client

@pytest.mark.parametrize("amount, expected_status", [
    (1000, 200),
    (0, 400),
    (-100, 400),
    (None, 400)
])
async def test_claim_amount_validation(client: AsyncClient, amount: float, expected_status: int):
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
    response = await client.post("/create_claim", json=claim_data)
    assert response.status_code == expected_status, f"Unexpected status code for amount {amount}"

async def test_claim_creation(client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a new claim."""
    logger.info("Testing claim creation with data: %s", sample_claim_data)
    headers = {"Authorization": f"Bearer {test_token}"}
    response = await client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 201, "Expected claim creation to return status 201"
    response_data = response.json()
    assert "claim_id" in response_data, "Response should contain 'claim_id'"
    assert response_data.get("claim_id"), "Claim ID should be returned in response"

async def test_claim_retrieval(client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test retrieval of a claim."""
    logger.info("Testing claim retrieval")
    headers = {"Authorization": f"Bearer {test_token}"}
    create_response = await client.post("/create_claim", json=sample_claim_data, headers=headers)
    claim_id = create_response.json().get("claim_id")
    
    response = await client.get(f"/claims/{claim_id}", headers=headers)
    assert response.status_code == 200, "Expected claim retrieval to return status 200"
    response_data = response.json()
    assert response_data.get("claim_id") == claim_id, "Claim ID mismatch in retrieval"

async def test_claim_update_status(client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test updating the status of a claim."""
    logger.info("Testing claim status update")
    headers = {"Authorization": f"Bearer {test_token}"}
    create_response = await client.post("/create_claim", json=sample_claim_data, headers=headers)
    claim_id = create_response.json().get("claim_id")
    
    update_data = {"status": "PROCESSING"}
    response = await client.put(f"/claims/{claim_id}/status", json=update_data, headers=headers)
    assert response.status_code == 200, "Expected claim status update to return status 200"
    response_data = response.json()
    assert response_data.get("status") == "PROCESSING", "Claim status mismatch after update"

# Additional tests for enhanced coverage

async def test_invalid_claim_type(client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a claim with an invalid claim type."""
    logger.info("Testing claim creation with invalid claim type")
    headers = {"Authorization": f"Bearer {test_token}"}
    sample_claim_data["claim_type"] = "invalid_type"
    response = await client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 400, f"Expected status 400 for invalid claim type, but got {response.status_code}"

async def test_future_admission_date(client: AsyncClient, db_pool, sample_claim_data: Dict[str, Any], test_token: str):
    """Test creation of a claim with a future admission date."""
    logger.info("Testing claim creation with future admission date")
    headers = {"Authorization": f"Bearer {test_token}"}
    sample_claim_data["admission_date"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    response = await client.post("/create_claim", json=sample_claim_data, headers=headers)
    assert response.status_code == 400, f"Expected status 400 for future admission date, but got {response.status_code}"

async def test_unauthorized_claim_creation(client: AsyncClient, sample_claim_data: Dict[str, Any]):
    """Test unauthorized claim creation."""
    logger.info("Testing unauthorized claim creation")
    response = await client.post("/create_claim", json=sample_claim_data)
    assert response.status_code == 401, f"Expected status 401 for unauthorized claim creation, but got {response.status_code}"