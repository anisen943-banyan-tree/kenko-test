import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, validator
from pydantic_settings import BaseSettings  # Updated import
from datetime import datetime
import asyncpg
import structlog
from enum import Enum
import jwt
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Load environment variables
load_dotenv()

# Define settings using Pydantic's BaseSettings
class Settings(BaseSettings):
    jwt_secret_key: str
    database_dsn: str
    environment: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()

# Initialize structured logger with environment-specific configuration
if settings.environment == "production":
    structlog.configure(
        processors=[
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
else:
    structlog.configure(
        processors=[
            structlog.processors.KeyValueRenderer(key_order=['event', 'institution_id', 'user_id'])
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger()

# Initialize APIRouter with prefix and tags
router = APIRouter(prefix="/admin/institutions", tags=["admin"])

# Initialize HTTPBearer security scheme
security = HTTPBearer()

# JWT Secret Key from settings
SECRET_KEY = settings.jwt_secret_key

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
    """Base model for Institution."""
    name: str
    code: str
    contact_email: EmailStr
    contact_phone: str
    subscription_tier: SubscriptionTier

    @validator('code')
    def validate_code(cls, v):
        """Ensure the institution code is alphanumeric and uppercase."""
        if not v.isalnum():
            raise ValueError('Code must be alphanumeric')
        return v.upper()

class InstitutionCreate(InstitutionBase):
    """Model for creating a new Institution."""
    pass

class InstitutionUpdate(InstitutionBase):
    """Model for updating an existing Institution."""
    status: Optional[str]

class Institution(InstitutionBase):
    """Full model for Institution including metadata."""
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

class UserBase(BaseModel):
    """Base model for User."""
    full_name: str
    email: EmailStr
    role: UserRole
    access_level: AccessLevel

class UserCreate(UserBase):
    """Model for creating a new User."""
    pass

class User(UserBase):
    """Full model for User including metadata."""
    id: int
    is_active: bool
    created_at: datetime

# Initialize Rate Limiter
limiter = Limiter(key_func=get_remote_address)

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Verify that the user has a valid admin JWT token.

    Args:
        credentials (HTTPAuthorizationCredentials): JWT credentials.

    Returns:
        dict: JWT payload if verification is successful.

    Raises:
        HTTPException: If token is invalid or user is not an admin.
    """
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        if payload.get("role") != "ADMIN":
            logger.warning("Unauthorized access attempt", user_id=payload.get("user_id"))
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions"
            )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expired", user_id=payload.get("user_id") if 'payload' in locals() else "Unknown")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        logger.warning("Invalid JWT", user_id=payload.get("user_id") if 'payload' in locals() else "Unknown")
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_db_pool() -> asyncpg.Pool:
    """
    Retrieve the database connection pool.

    Returns:
        asyncpg.Pool: The database connection pool.

    Raises:
        HTTPException: If the database pool is not initialized.
    """
    try:
        pool = getattr(router, 'db_pool', None)
        if pool is None:
            raise RuntimeError("Database pool not initialized.")
        return pool
    except RuntimeError as e:
        logger.error("Database connection pool initialization failed", error=str(e))
        raise HTTPException(status_code=500, detail="Database connection error")

async def fetch_institution(pool: asyncpg.Pool, institution_id: int) -> asyncpg.Record:
    """
    Fetch an institution by its ID.

    Args:
        pool (asyncpg.Pool): The database connection pool.
        institution_id (int): The ID of the institution.

    Returns:
        asyncpg.Record: The institution record.

    Raises:
        HTTPException: If the institution is not found.
    """
    institution = await pool.fetchrow(
        "SELECT * FROM institutions WHERE id = $1",
        institution_id
    )
    if not institution:
        logger.info("Institution not found", institution_id=institution_id)
        raise HTTPException(status_code=404, detail="Institution not found")
    return institution

async def create_user_institution_mapping(
    pool: asyncpg.Pool,
    institution_id: int,
    user_id: int,
    role: UserRole,
    access_level: AccessLevel,
    created_by: int
):
    """
    Create a mapping between a user and an institution.

    Args:
        pool (asyncpg.Pool): The database connection pool.
        institution_id (int): The ID of the institution.
        user_id (int): The ID of the user.
        role (UserRole): The role of the user.
        access_level (AccessLevel): The access level of the user.
        created_by (int): The ID of the admin creating the user.
    """
    await pool.execute("""
        INSERT INTO institution_users (
            institution_id, user_id, role, 
            access_level, created_by
        )
        VALUES ($1, $2, $3, $4, $5)
    """, institution_id, user_id, role, access_level, created_by)

@router.get("/", response_model=List[Institution])
@limiter.limit("5/minute")
async def list_institutions(
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    List all institutions.

    Args:
        admin (dict): Admin user payload.
        pool (asyncpg.Pool): Database connection pool.

    Returns:
        List[Institution]: A list of all institutions.
    """
    try:
        manager = InstitutionManager(pool)
        institutions = await manager.list_institutions()
        logger.info("Listed all institutions", count=len(institutions))
        return institutions
    except Exception as e:
        logger.error("Error listing institutions", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving institutions")

@router.post("/", response_model=Institution)
@limiter.limit("5/minute")
async def create_institution(
    institution: InstitutionCreate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Create a new institution.

    Args:
        institution (InstitutionCreate): The institution data.
        admin (dict): Admin user payload.
        pool (asyncpg.Pool): Database connection pool.

    Returns:
        Institution: The created institution.
    """
    try:
        manager = InstitutionManager(pool)
        new_institution = await manager.create_institution(institution)
        logger.info("Created new institution", institution_id=new_institution.id)
        return new_institution
    except asyncpg.UniqueViolationError:
        logger.warning("Institution code already exists", code=institution.code)
        raise HTTPException(
            status_code=400,
            detail="Institution with this code already exists"
        )
    except Exception as e:
        logger.error("Error creating institution", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Error creating institution")

@router.put("/{institution_id}", response_model=Institution)
@limiter.limit("5/minute")
async def update_institution(
    institution_id: int,
    institution: InstitutionUpdate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Update an existing institution.

    Args:
        institution_id (int): The ID of the institution to update.
        institution (InstitutionUpdate): The updated institution data.
        admin (dict): Admin user payload.
        pool (asyncpg.Pool): Database connection pool.

    Returns:
        Institution: The updated institution.
    """
    try:
        manager = InstitutionManager(pool)
        updated_institution = await manager.update_institution(institution_id, institution)
        if not updated_institution:
            logger.info("Institution not found for update", institution_id=institution_id)
            raise HTTPException(status_code=404, detail="Institution not found")
        logger.info("Updated institution", institution_id=institution_id)
        return updated_institution
    except Exception as e:
        logger.error("Error updating institution", error=str(e), institution_id=institution_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Error updating institution")

@router.post("/{institution_id}/users", response_model=User)
@limiter.limit("5/minute")
async def create_institution_user(
    institution_id: int,
    user: UserCreate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    Create a new user for an institution.

    Args:
        institution_id (int): The ID of the institution.
        user (UserCreate): The user data.
        admin (dict): Admin user payload.
        pool (asyncpg.Pool): Database connection pool.

    Returns:
        User: The created user.
    """
    try:
        # Fetch and validate institution
        institution = await fetch_institution(pool, institution_id)
        if institution['status'] != 'ACTIVE':
            logger.warning("Attempt to add user to inactive institution", institution_id=institution_id)
            raise HTTPException(
                status_code=400,
                detail="Cannot create users for inactive institution"
            )

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Create user
                created_user = await conn.fetchrow("""
                    INSERT INTO users (
                        full_name, email, institution_id, 
                        is_active, created_by, created_at
                    )
                    VALUES ($1, $2, $3, true, $4, NOW())
                    RETURNING *
                """, user.full_name, user.email, institution_id, admin.get('user_id'))

                # Create institution user mapping
                await create_user_institution_mapping(
                    pool=pool,
                    institution_id=institution_id,
                    user_id=created_user['id'],
                    role=user.role,
                    access_level=user.access_level,
                    created_by=admin.get('user_id')
                )

                logger.info("Created new user for institution", user_id=created_user['id'], institution_id=institution_id)
                return User(**created_user)
    except asyncpg.UniqueViolationError:
        logger.warning("User with this email already exists", email=user.email)
        raise HTTPException(
            status_code=400,
            detail="User with this email already exists"
        )
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error("Error creating institution user", error=str(e), institution_id=institution_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Error creating user")

@router.get("/{institution_id}/users", response_model=List[UserBase])
@limiter.limit("5/minute")
async def list_institution_users(
    institution_id: int,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """
    List all users for a specific institution.

    Args:
        institution_id (int): The ID of the institution.
        admin (dict): Admin user payload.
        pool (asyncpg.Pool): Database connection pool.

    Returns:
        List[UserBase]: A list of users associated with the institution.
    """
    try:
        # Verify institution exists
        await fetch_institution(pool, institution_id)

        async with pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT u.id, u.full_name, u.email, iu.role, iu.access_level, u.is_active, u.created_at
                FROM users u
                JOIN institution_users iu ON u.id = iu.user_id
                WHERE iu.institution_id = $1
                ORDER BY u.full_name
            """, institution_id)
            logger.info("Listed users for institution", institution_id=institution_id, user_count=len(users))
            return [UserBase(**user) for user in users]
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error("Error listing institution users", error=str(e), institution_id=institution_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving users")

import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from src.api.routes import institutions
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "https://yourdomain.com",
    "http://localhost",
]

@pytest.fixture
async def async_client():
    app = FastAPI()
    app.include_router(institutions.router)
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(429, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
@limiter.limit("5/minute")
async def test_list_institutions(async_client):
    response = await async_client.get("/admin/institutions/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
