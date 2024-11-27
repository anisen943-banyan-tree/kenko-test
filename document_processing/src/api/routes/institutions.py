import os
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Security, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, field_validator
from pydantic_settings import BaseSettings
from datetime import datetime
import asyncpg
import structlog
from enum import Enum
import jwt
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.config.settings import settings
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from fastapi_cache.backends.redis import RedisBackend
from unittest.mock import AsyncMock
import pytest

# Load environment variables
load_dotenv()

# Initialize structured logger
logger = structlog.get_logger()

# Initialize APIRouter with prefix and tags
router = APIRouter(prefix="/admin/institutions", tags=["Institutions"])
security = HTTPBearer()

class SubscriptionTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STANDARD = "STANDARD"

class AccessLevel(str, Enum):
    STANDARD = "STANDARD"
    ADMIN = "ADMIN"
    RESTRICTED = "RESTRICTED"

class InstitutionBase(BaseModel):
    name: str
    code: str
    contact_email: EmailStr
    contact_phone: str
    subscription_tier: SubscriptionTier

    @field_validator('code')
    def validate_code(cls, v):
        if not v.isalnum():
            raise ValueError('Code must be alphanumeric')
        return v.upper()

class InstitutionCreate(InstitutionBase):
    pass

class InstitutionUpdate(InstitutionBase):
    status: Optional[str]

class Institution(InstitutionBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

CACHE_NAMESPACE = "institutions"

def handle_database_error(action: str):
    async def wrapper(func):
        async def inner(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error during {action}: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to {action}: {str(e)}")
        return inner
    return wrapper

async def clear_cache(namespace: str):
    try:
        await FastAPICache.clear(namespace=namespace)
    except Exception as e:
        logger.warning(f"Failed to clear cache for namespace {namespace}: {str(e)}")

def invalidate_cache(key_pattern):
    keys = cache.keys(key_pattern)
    for key in keys:
        cache.delete(key)

class InstitutionManager:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.logger = structlog.get_logger()

    @handle_database_error("list institutions")
    async def list_institutions(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT * FROM institutions ORDER BY name")
            return [dict(record) for record in records]

    @handle_database_error("create institution")
    async def create_institution(self, institution: InstitutionCreate, admin_id: int) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                record = await conn.fetchrow(
                    """
                    INSERT INTO institutions (name, code, contact_email, contact_phone, subscription_tier, status, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, 'ACTIVE', NOW(), NOW())
                    RETURNING *
                    """,
                    institution.name,
                    institution.code,
                    institution.contact_email,
                    institution.contact_phone,
                    institution.subscription_tier,
                )
                await clear_cache(CACHE_NAMESPACE)
                return dict(record)

    @handle_database_error("update institution")
    async def update_institution(self, institution_id: int, institution: InstitutionUpdate, admin_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow("""
                UPDATE institutions 
                SET name = $1, code = $2, contact_email = $3,
                    contact_phone = $4, subscription_tier = $5,
                    status = $6, updated_at = NOW()
                WHERE id = $7
                RETURNING *
            """,
                institution.name,
                institution.code,
                institution.contact_email,
                institution.contact_phone,
                institution.subscription_tier,
                institution.status,
                institution_id
            )
            
            if record:
                # Invalidate cache after update
                await FastAPICache.clear(namespace=CACHE_NAMESPACE)
                return dict(record)
            return None

# Rate limiter factory for test/prod environments
def rate_limiter_factory():
    if settings.environment == "test":
        logger.info("Rate limiter disabled for test environment.")
        class NoOpLimiter:
            def limit(self, limit_string: str):
                def decorator(func):
                    return func
                return decorator
        return NoOpLimiter()
    logger.info("Rate limiter enabled for production.")
    return Limiter(key_func=get_remote_address)

limiter = rate_limiter_factory()

async def validate_token(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    payload = await validate_token(credentials)
    if payload.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return payload

async def get_db_pool() -> asyncpg.Pool:
    try:
        if not hasattr(router, "db_pool"):
            raise RuntimeError("Database pool not initialized")
        return router.db_pool
    except Exception as e:
        logger.error("Database pool error", error=str(e))
        raise HTTPException(status_code=500, detail="Database connection error")

def truncate_partition(partition_name):
    execute_sql(f"TRUNCATE TABLE {partition_name}")

def delete_institution(institution_id):
    execute_sql(f"DELETE FROM institutions WHERE id = {institution_id} CASCADE")

async def handle_institution_operation():
    async with transaction_scope():
        perform_operation()

def role_check(user_role: str) -> bool:
    """Verify if the user role has the required permissions."""
    allowed_roles = ["admin", "user"]  # Adjust based on your application logic
    return user_role in allowed_roles

@router.get("/", response_model=List[Institution])
@limiter.limit("5/minute")
@cache(namespace=CACHE_NAMESPACE, expire=300)  # Cache for 5 minutes
async def list_institutions(
    request: Request,
    admin: Dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    manager = InstitutionManager(pool)
    institutions = await manager.list_institutions()
    return institutions

@router.post("/", response_model=Institution)
@limiter.limit("5/minute")
async def create_institution(
    request: Request,
    institution: InstitutionCreate,
    admin: Dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Create a new institution."""
    try:
        manager = InstitutionManager(pool)
        result = await manager.create_institution(institution, admin["user_id"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create institution", error=str(e))
        raise HTTPException(status_code=500, detail="Error creating institution")

@router.put("/{institution_id}", response_model=Institution)
@limiter.limit("5/minute")
async def update_institution(
    request: Request,
    institution_id: int,
    institution: InstitutionUpdate,
    admin: Dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Update an existing institution."""
    try:
        manager = InstitutionManager(pool)
        result = await manager.update_institution(institution_id, institution, admin["user_id"])
        if not result:
            raise HTTPException(status_code=404, detail="Institution not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update institution", error=str(e))
        raise HTTPException(status_code=500, detail="Error updating institution")

@router.get("/health")
async def health_check():
    try:
        async with router.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@pytest.fixture(autouse=True)
async def mock_dependencies():
    app.state.pool = AsyncMock()  # Mock database pool
    yield