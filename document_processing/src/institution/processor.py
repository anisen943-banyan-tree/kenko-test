from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator  # Updated import
from datetime import datetime
import asyncpg
import structlog
from enum import Enum
from .database import get_db_pool

logger = structlog.get_logger(__name__)

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

class InstitutionManager:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.logger = logger

    async def list_institutions(self) -> List[Institution]:
        """List all institutions with stats"""
        async with self.pool.acquire() as conn:
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
            return [Institution(**dict(inst)) for inst in institutions]

    async def create_institution(
        self, 
        institution: InstitutionBase,
        admin_id: int
    ) -> Institution:
        """Create a new institution"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Check for duplicate code
                exists = await conn.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM institutions WHERE code = $1
                    )
                """, institution.code)
                
                if exists:
                    raise ValueError("Institution code already exists")

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
                    admin_id,
                    'INSTITUTION_CREATION'
                )

                return Institution(**dict(created))

    async def get_institution(self, institution_id: int) -> Optional[Institution]:
        """Get institution details"""
        async with self.pool.acquire() as conn:
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
            
            return Institution(**dict(institution)) if institution else None

    async def add_user(
        self,
        institution_id: int,
        user: UserBase,
        admin_id: int
    ) -> dict:
        """Add a user to an institution"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verify institution
                institution = await conn.fetchrow("""
                    SELECT * FROM institutions 
                    WHERE id = $1 AND status = 'ACTIVE'
                """, institution_id)
                
                if not institution:
                    raise ValueError("Invalid or inactive institution")

                # Create user
                user_id = await conn.fetchval("""
                    INSERT INTO users (
                        full_name, email, institution_id,
                        is_active, created_by
                    )
                    VALUES ($1, $2, $3, true, $4)
                    RETURNING user_id
                """,
                    user.full_name,
                    user.email,
                    institution_id,
                    admin_id
                )

                # Create role mapping
                await conn.execute("""
                    INSERT INTO institution_users (
                        institution_id, user_id,
                        role, access_level, created_by
                    )
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    institution_id,
                    user_id,
                    user.role,
                    user.access_level,
                    admin_id
                )

                return {
                    "user_id": user_id,
                    "institution_id": institution_id,
                    "role": user.role,
                    "access_level": user.access_level
                }

    async def list_users(
        self,
        institution_id: int
    ) -> List[dict]:
        """List users for an institution"""
        async with self.pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT 
                    u.user_id,
                    u.full_name,
                    u.email,
                    u.is_active,
                    iu.role,
                    iu.access_level,
                    u.created_at
                FROM users u
                JOIN institution_users iu ON u.user_id = iu.user_id
                WHERE iu.institution_id = $1
                ORDER BY u.full_name
            """, institution_id)
            
            return [dict(user) for user in users]
