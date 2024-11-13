import pytest
from httpx import AsyncClient
from fastapi import FastAPI, HTTPException
from unittest.mock import patch, AsyncMock
from document_processing.routers import institutions  # Adjusted import
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
from document_processing.models import InstitutionCreate, InstitutionUpdate  # Added import

# Define allowed origins for testing
origins = [
    "https://yourdomain.com",
    "http://localhost",
]

# Factory for Institution
class InstitutionFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    name = Faker('company')
    code = Faker('bothify', text='INST###')
    contact_email = Faker('company_email')
    contact_phone = Faker('phone_number')
    subscription_tier = Faker('random_element', elements=('STANDARD', 'PREMIUM', 'ENTERPRISE'))
    status = 'ACTIVE'
    created_at = Faker('iso8601')

# Factory for User
class UserFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    full_name = Faker('name')
    email = Faker('email')
    role = Faker('random_element', elements=('ADMIN', 'MANAGER', 'STANDARD'))
    access_level = Faker('random_element', elements=('ADMIN', 'STANDARD', 'RESTRICTED'))
    is_active = True
    created_at = Faker('iso8601')

@pytest.fixture
async def async_client():
    """
    Fixture to create an asynchronous HTTP client for testing.
    Sets up the FastAPI app with rate limiting and CORS middleware.
    """
    app = FastAPI()
    
    # Initialize Rate Limiter with adjustable rate limits via environment variables
    rate_limit = os.getenv('TEST_RATE_LIMIT', '10/minute')
    limiter = Limiter(key_func=get_remote_address, default_limits=[rate_limit])
    app.state.limiter = limiter
    app.add_exception_handler(429, _rate_limit_exceeded_handler)
    
    # Add CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(institutions.router)
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def mock_db_pool():
    """Mock database pool fixture."""
    return AsyncMock()

@pytest.mark.asyncio
async def test_list_institutions_success(async_client, mock_db_pool):
    """Test that the list of institutions is retrieved successfully."""
    with patch('src.api.routers.institutions.get_db_pool', return_value=mock_db_pool), \
         patch('src.api.routers.institutions.verify_admin_token') as mock_verify:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        with patch('routers.institutions.InstitutionManager.list_institutions', new_callable=AsyncMock) as mock_list:
            institutions_data = InstitutionFactory.create_batch(2)
            mock_list.return_value = institutions_data
            response = await async_client.get("/admin/institutions/")
            assert response.status_code == 200, "Expected status 200 for listing institutions"
            data = response.json()
            assert isinstance(data, list), "Response should be a list"
            assert len(data) == 2, "Expected two institutions in the response"
            assert data[0]["name"] == institutions_data[0]["name"], "First institution name mismatch"
            assert data[1]["name"] == institutions_data[1]["name"], "Second institution name mismatch"

@pytest.mark.asyncio
async def test_create_institution_success(async_client):
    """Test that a new institution can be created successfully."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.InstitutionManager.create_institution', new_callable=AsyncMock) as mock_create:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_create.return_value = InstitutionFactory()
        institution_data = {
            "name": "Test Institution",
            "code": "TEST123",
            "contact_email": "contact@test.com",
            "contact_phone": "123-456-7890",
            "subscription_tier": "STANDARD"
        }
        response = await async_client.post("/admin/institutions/", json=institution_data)
        assert response.status_code == 200, "Expected status 200 for institution creation"
        data = response.json()
        assert data["name"] == institution_data["name"], "Institution name mismatch"
        assert data["code"] == institution_data["code"], "Institution code mismatch"
        assert data["contact_email"] == institution_data["contact_email"], "Institution contact email mismatch"

@pytest.mark.asyncio
async def test_create_institution_duplicate_code(async_client):
    """Test that creating an institution with a duplicate code fails."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.InstitutionManager.create_institution', new_callable=AsyncMock) as mock_create:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_create.side_effect = UniqueViolationError("duplicate key value violates unique constraint")
        institution_data = {
            "name": "Duplicate Institution",
            "code": "DUPLICATE123",
            "contact_email": "contact@duplicate.com",
            "contact_phone": "098-765-4321",
            "subscription_tier": "PREMIUM"
        }
        response = await async_client.post("/admin/institutions/", json=institution_data)
        assert response.status_code == 400, "Expected status 400 for duplicate institution code"
        assert response.json()["detail"] == "Institution with this code already exists", "Duplicate code error message mismatch"

@pytest.mark.asyncio
async def test_update_institution_success(async_client):
    """Test that an existing institution can be updated successfully."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.InstitutionManager.update_institution', new_callable=AsyncMock) as mock_update:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_update.return_value = InstitutionFactory()
        update_data = {
            "name": "Updated Institution",
            "code": "TEST123",
            "contact_email": "updated@test.com",
            "contact_phone": "123-456-7890",
            "subscription_tier": "PREMIUM",
            "status": "ACTIVE"
        }
        response = await async_client.put("/admin/institutions/1", json=update_data)
        assert response.status_code == 200, "Expected status 200 for institution update"
        data = response.json()
        assert data["name"] == update_data["name"], "Updated institution name mismatch"
        assert data["contact_email"] == update_data["contact_email"], "Updated contact email mismatch"

@pytest.mark.asyncio
async def test_create_institution_user_success(async_client):
    """Test that a new user can be created for an institution successfully."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.fetch_institution', new_callable=AsyncMock) as mock_fetch, \
         patch('routers.institutions.create_user_institution_mapping', new_callable=AsyncMock) as mock_mapping, \
         patch('routers.institutions.InstitutionManager.conn.fetchrow', new_callable=AsyncMock) as mock_fetchrow:
        
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_fetch.return_value = InstitutionFactory(status="ACTIVE")
        mock_fetchrow.return_value = UserFactory()
        user_data = {
            "full_name": "New User",
            "email": "newuser@test.com",
            "role": "MANAGER",
            "access_level": "ADMIN"
        }
        response = await async_client.post("/admin/institutions/1/users", json=user_data)
        assert response.status_code == 200, "Expected status 200 for creating institution user"
        data = response.json()
        assert data["full_name"] == user_data["full_name"], "User full name mismatch"
        assert data["email"] == user_data["email"], "User email mismatch"

@pytest.mark.asyncio
async def test_list_institution_users_success(async_client):
    """Test that the list of users for an institution is retrieved successfully."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.fetch_institution', new_callable=AsyncMock) as mock_fetch, \
         patch('routers.institutions.InstitutionManager.conn.fetch', new_callable=AsyncMock) as mock_fetch_users:
        
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_fetch.return_value = InstitutionFactory(status="ACTIVE")
        users = [UserFactory(), UserFactory()]
        mock_fetch_users.return_value = users
        response = await async_client.get("/admin/institutions/1/users")
        assert response.status_code == 200, "Expected status 200 for listing institution users"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        assert len(data) == 2, "Expected two users in the response"
        assert data[0]["full_name"] == "User One", "First user full name mismatch"
        assert data[1]["full_name"] == "User Two", "Second user full name mismatch"

@pytest.mark.asyncio
async def test_rate_limiting(async_client):
    """Test that rate limiting is enforced on the list_institutions endpoint."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        # Perform 10 allowed requests
        for _ in range(10):
            response = await async_client.get("/admin/institutions/")
            assert response.status_code == 200, "Expected status 200 for listing institutions within rate limit"
        # 11th request should be rate limited
        response = await async_client.get("/admin/institutions/")
        assert response.status_code == 429, "Expected status 429 for exceeding rate limit"
        assert response.json()["detail"] == "Rate limit exceeded: 10 per minute", "Rate limit error message mismatch"

@pytest.mark.asyncio
async def test_create_institution_invalid_data(async_client):
    """Test that creating an institution with invalid data fails."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        invalid_institution_data = {
            "name": "",  # Missing name
            "code": "INV@LID",  # Invalid code (non-alphanumeric)
            "contact_email": "invalid-email",  # Invalid email format
            "contact_phone": "123",  # Invalid phone format
            "subscription_tier": "UNKNOWN"  # Invalid subscription tier
        }
        response = await async_client.post("/admin/institutions/", json=invalid_institution_data)
        assert response.status_code == 422, "Expected status 422 for invalid institution data"
        errors = response.json()["detail"]
        assert len(errors) >= 4, "Expected multiple validation errors for invalid data"

@pytest.mark.asyncio
async def test_unauthorized_access_no_token(async_client):
    """Test that accessing endpoints without a JWT token is unauthorized."""
    response = await async_client.get("/admin/institutions/")
    assert response.status_code == 403, "Expected status 403 for unauthorized access without token"
    assert response.json()["detail"] == "Not authenticated", "Unauthorized access error message mismatch"

@pytest.mark.asyncio
async def test_unauthorized_access_invalid_token(async_client):
    """Test that accessing endpoints with an invalid JWT token is unauthorized."""
    headers = {"Authorization": "Bearer invalid_token"}
    response = await async_client.get("/admin/institutions/", headers=headers)
    assert response.status_code == 401, "Expected status 401 for invalid JWT token"
    assert response.json()["detail"] == "Invalid token", "Invalid token error message mismatch"

@pytest.mark.asyncio
async def test_unauthorized_access_non_admin_role(async_client):
    """Test that accessing endpoints with a non-admin JWT token is forbidden."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify:
        mock_verify.side_effect = HTTPException(status_code=403, detail="Insufficient permissions")
        headers = {"Authorization": "Bearer non_admin_jwt_token"}
        response = await async_client.get("/admin/institutions/", headers=headers)
        assert response.status_code == 403, "Expected status 403 for non-admin role access"
        assert response.json()["detail"] == "Insufficient permissions", "Non-admin role error message mismatch"

@pytest.mark.asyncio
async def test_create_institution_expired_token(async_client):
    """Test that creating an institution with an expired JWT token is unauthorized."""
    jwt_secret = os.getenv("JWT_SECRET_KEY", "default_secret")
    expired_token = jwt.encode(
        {"user_id": 1, "role": "ADMIN", "exp": datetime.utcnow() - timedelta(hours=1)},
        jwt_secret,
        algorithm="HS256"
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    institution_data = {
        "name": "Expired Token Institution",
        "code": "EXPIRED123",
        "contact_email": "expired@test.com",
        "contact_phone": "321-654-0987",
        "subscription_tier": "STANDARD"
    }
    response = await async_client.post("/admin/institutions/", json=institution_data, headers=headers)
    assert response.status_code == 401, "Expected status 401 for expired JWT token"
    assert response.json()["detail"] == "Token has expired", "Expired token error message mismatch"

@pytest.mark.asyncio
async def test_create_institution_malformed_token(async_client):
    """Test that creating an institution with a malformed JWT token is unauthorized."""
    malformed_token = "malformed.token.parts"
    headers = {"Authorization": f"Bearer {malformed_token}"}
    institution_data = {
        "name": "Malformed Token Institution",
        "code": "MALFORMED123",
        "contact_email": "malformed@test.com",
        "contact_phone": "987-654-3210",
        "subscription_tier": "STANDARD"
    }
    response = await async_client.post("/admin/institutions/", json=institution_data, headers=headers)
    assert response.status_code == 401, "Expected status 401 for malformed JWT token"
    assert response.json()["detail"] == "Invalid token", "Malformed token error message mismatch"

@pytest.mark.asyncio
async def test_concurrent_create_institution(async_client):
    """Test creating institutions concurrently to detect race conditions."""
    with patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('routers.institutions.InstitutionManager.create_institution', new_callable=AsyncMock) as mock_create:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        # Simulate unique constraint violation on second concurrent request
        mock_create.side_effect = [
            InstitutionFactory(),
            UniqueViolationError("duplicate key value violates unique constraint")
        ]
        institution_data_1 = {
            "name": "Concurrent Institution 1",
            "code": "CONCUR1",
            "contact_email": "concur1@test.com",
            "contact_phone": "111-111-1111",
            "subscription_tier": "STANDARD"
        }
        institution_data_2 = {
            "name": "Concurrent Institution 2",
            "code": "CONCUR1",  # Same code to trigger duplicate
            "contact_email": "concur2@test.com",
            "contact_phone": "222-222-2222",
            "subscription_tier": "PREMIUM"
        }
        responses = await asyncio.gather(
            async_client.post("/admin/institutions/", json=institution_data_1),
            async_client.post("/admin/institutions/", json=institution_data_2)
        )
        assert responses[0].status_code == 200, "Expected status 200 for first concurrent institution creation"
        assert responses[1].status_code == 400, "Expected status 400 for duplicate institution code in concurrent creation"
        assert responses[1].json()["detail"] == "Institution with this code already exists", "Concurrent duplicate code error message mismatch"

@pytest.mark.asyncio
async def test_list_institutions_db_error(async_client, mock_db_pool):
    """Test handling of database errors when listing institutions."""
    with patch('src.api.routers.institutions.get_db_pool', return_value=mock_db_pool), \
         patch('src.api.routers.institutions.verify_admin_token') as mock_verify, \
         patch('src.api.routers.institutions.InstitutionManager.list_institutions') as mock_list:
        mock_verify.return_value = {"user_id": 1, "role": "ADMIN"}
        mock_list.side_effect = Exception("Database error")
        
        response = await async_client.get("/admin/institutions/")
        assert response.status_code == 500
        assert response.json()["detail"] == "Error retrieving institutions"

class InstitutionManager:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        
    async def list_institutions(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM institutions ORDER BY name")
            
    async def create_institution(self, institution: InstitutionCreate):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                INSERT INTO institutions (name, code, contact_email, contact_phone, subscription_tier, status)
                VALUES ($1, $2, $3, $4, $5, 'ACTIVE')
                RETURNING *
            """, institution.name, institution.code, institution.contact_email, 
                institution.contact_phone, institution.subscription_tier)

    async def update_institution(self, institution_id: int, institution: InstitutionUpdate):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                UPDATE institutions 
                SET name = $1, code = $2, contact_email = $3,
                    contact_phone = $4, subscription_tier = $5,
                    status = $6, updated_at = NOW()
                WHERE id = $7
                RETURNING *
            """, institution.name, institution.code, institution.contact_email,
                institution.contact_phone, institution.subscription_tier,
                institution.status, institution_id)