from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
import asyncpg
import structlog
from enum import Enum
import jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/institutions", tags=["admin"])
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

    @validator('code')
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

class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole
    access_level: AccessLevel

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Verify that the user is an admin"""
    try:
        payload = jwt.decode(credentials.credentials, "your-secret-key", algorithms=["HS256"])
        if payload.get("role") != "ADMIN":
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions"
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_db_pool() -> asyncpg.Pool:
    """Get database connection pool"""
    # In practice, this would be properly initialized and managed
    return getattr(router, 'db_pool', None)

@router.get("/", response_model=List[Institution])
async def list_institutions(
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """List all institutions"""
    try:
        async with pool.acquire() as conn:
            institutions = await conn.fetch("""
                SELECT i.*, 
                       COUNT(DISTINCT u.user_id) as user_count,
                       COUNT(DISTINCT c.claim_id) as claim_count
                FROM institutions i
                LEFT JOIN institution_users u ON i.id = u.institution_id
                LEFT JOIN claims c ON i.id = c.institution_id
                GROUP BY i.id
                ORDER BY i.name
            """)
            return [dict(inst) for inst in institutions]
    except Exception as e:
        logger.error("Error listing institutions", error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving institutions")

@router.post("/", response_model=Institution, status_code=201)
async def create_institution(
    institution: InstitutionCreate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Create a new institution"""
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check for duplicate code
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM institutions WHERE code = $1)",
                    institution.code
                )
                if exists:
                    raise HTTPException(
                        status_code=400,
                        detail="Institution code already exists"
                    )

                # Create institution
                created = await conn.fetchrow("""
                    INSERT INTO institutions (
                        name, code, contact_email, contact_phone, 
                        subscription_tier, status
                    )
                    VALUES ($1, $2, $3, $4, $5, 'ACTIVE')
                    RETURNING *
                """, 
                    institution.name,
                    institution.code,
                    institution.contact_email,
                    institution.contact_phone,
                    institution.subscription_tier
                )

                # Log creation
                await conn.execute("""
                    INSERT INTO audit_logs (
                        action, table_name, record_id, 
                        executed_by, reason_code
                    )
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    'CREATE',
                    'institutions',
                    created['id'],
                    admin['user_id'],
                    'INSTITUTION_CREATION'
                )

                return dict(created)
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=400,
            detail="Institution with this code already exists"
        )
    except Exception as e:
        logger.error("Error creating institution", error=str(e))
        raise HTTPException(status_code=500, detail="Error creating institution")

@router.get("/{institution_id}", response_model=Institution)
async def get_institution(
    institution_id: int,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Get institution details"""
    try:
        async with pool.acquire() as conn:
            institution = await conn.fetchrow("""
                SELECT i.*, 
                       COUNT(DISTINCT u.user_id) as user_count,
                       COUNT(DISTINCT c.claim_id) as claim_count
                FROM institutions i
                LEFT JOIN institution_users u ON i.id = u.institution_id
                LEFT JOIN claims c ON i.id = c.institution_id
                WHERE i.id = $1
                GROUP BY i.id
            """, institution_id)
            
            if not institution:
                raise HTTPException(
                    status_code=404,
                    detail="Institution not found"
                )
                
            return dict(institution)
    except Exception as e:
        logger.error("Error retrieving institution", error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving institution")

@router.put("/{institution_id}", response_model=Institution)
async def update_institution(
    institution_id: int,
    institution: InstitutionUpdate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Update institution details"""
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Verify existence
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM institutions WHERE id = $1)",
                    institution_id
                )
                if not exists:
                    raise HTTPException(
                        status_code=404,
                        detail="Institution not found"
                    )

                # Update institution
                updated = await conn.fetchrow("""
                    UPDATE institutions 
                    SET name = $1, 
                        contact_email = $2,
                        contact_phone = $3,
                        subscription_tier = $4,
                        status = $5,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $6
                    RETURNING *
                """,
                    institution.name,
                    institution.contact_email,
                    institution.contact_phone,
                    institution.subscription_tier,
                    institution.status,
                    institution_id
                )

                # Log update
                await conn.execute("""
                    INSERT INTO audit_logs (
                        action, table_name, record_id, 
                        executed_by, reason_code
                    )
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    'UPDATE',
                    'institutions',
                    institution_id,
                    admin['user_id'],
                    'INSTITUTION_UPDATE'
                )

                return dict(updated)
    except Exception as e:
        logger.error("Error updating institution", error=str(e))
        raise HTTPException(status_code=500, detail="Error updating institution")

@router.post("/{institution_id}/users", response_model=User)
async def create_institution_user(
    institution_id: int,
    user: UserCreate,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Create a new user for an institution"""
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check institution exists and is active
                institution = await conn.fetchrow(
                    "SELECT * FROM institutions WHERE id = $1",
                    institution_id
                )
                if not institution:
                    raise HTTPException(
                        status_code=404,
                        detail="Institution not found"
                    )
                if institution['status'] != 'ACTIVE':
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot create users for inactive institution"
                    )

                # Create user
                created_user = await conn.fetchrow("""
                    INSERT INTO users (
                        full_name, email, institution_id, 
                        is_active, created_by
                    )
                    VALUES ($1, $2, $3, true, $4)
                    RETURNING *
                """,
                    user.full_name,
                    user.email,
                    institution_id,
                    admin['user_id']
                )

                # Create institution user mapping
                await conn.execute("""
                    INSERT INTO institution_users (
                        institution_id, user_id, role, 
                        access_level, created_by
                    )
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    institution_id,
                    created_user['user_id'],
                    user.role,
                    user.access_level,
                    admin['user_id']
                )

                return dict(created_user)
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=400,
            detail="User with this email already exists"
        )
    except Exception as e:
        logger.error("Error creating institution user", error=str(e))
        raise HTTPException(status_code=500, detail="Error creating user")

@router.get("/{institution_id}/users", response_model=List[User])
async def list_institution_users(
    institution_id: int,
    admin: dict = Depends(verify_admin_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """List all users for an institution"""
    try:
        async with pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT u.*, iu.role, iu.access_level
                FROM users u
                JOIN institution_users iu ON u.user_id = iu.user_id
                WHERE iu.institution_id = $1
                ORDER BY u.full_name
            """, institution_id)
            return [dict(user) for user in users]
    except Exception as e:
        logger.error("Error listing institution users", error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving users")

