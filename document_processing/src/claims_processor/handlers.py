from typing import Dict, List, Optional, Any
import asyncpg
import structlog
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ValidationError, field_validator  # Updated import
from fastapi import HTTPException
from enum import Enum
from functools import wraps

# ...existing code...

from src.claims_processor.handlers import ClaimStatus, ClaimsProcessingError, DatabaseConnectionError, ClaimData, db_error_handler, ClaimHandler

# ...existing code...

logger = structlog.get_logger()

class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class ClaimsProcessingError(Exception):
    """Custom exception for claims processing errors"""
    pass

class DatabaseConnectionError(Exception):
    """Custom exception for database connection errors"""
    pass

class ClaimData(BaseModel):
    claim_type: str
    member_id: str
    hospital_id: str
    admission_date: datetime
    discharge_date: datetime
    total_amount: float
    documents: Optional[List[Dict[str, Any]]] = []

    @field_validator('total_amount')
    def validate_total_amount(cls, value):
        if value < 0:
            raise ValueError('Total amount must be non-negative')
        return value

    @field_validator('discharge_date')
    def validate_dates(cls, discharge_date, values):
        admission_date = values.get('admission_date')
        if admission_date and discharge_date and discharge_date < admission_date:
            raise ValueError('Discharge date cannot be before admission date')
        return discharge_date

def db_error_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except asyncpg.exceptions.PostgresError as e:
            logger.error("Database operation failed", error=str(e))
            raise DatabaseConnectionError("Database operation failed")
        except Exception as e:
            logger.error("Unexpected error in database operation", error=str(e))
            raise HTTPException(status_code=500, detail="Unexpected database error")
    return wrapper

class ClaimHandler:
    """Handles core claim processing logic"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.logger = structlog.get_logger().bind()

    @db_error_handler
    async def validate_claim_request(self, claim_data: ClaimData) -> None:
        """Validate claim request data"""
        self.logger = self.logger.bind(member_id=claim_data.member_id, hospital_id=claim_data.hospital_id)
        async with self.pool.acquire() as conn:
            # Verify member
            member_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM members WHERE member_id = $1
                )
            """, claim_data.member_id)
            
            if not member_exists:
                raise ClaimsProcessingError(f"Member ID {claim_data.member_id} does not exist")
            
            # Verify hospital
            hospital_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM hospitals WHERE hospital_id = $1
                )
            """, claim_data.hospital_id)
            
            if not hospital_exists:
                raise ClaimsProcessingError(f"Hospital ID {claim_data.hospital_id} does not exist")
            
            self.logger.info("Claim request validated")

    @db_error_handler
    async def create_claim(
        self,
        claim_data: ClaimData,
        user_id: str
    ) -> str:
        """Create new claim with validation"""
        self.logger = self.logger.bind(user_id=user_id)
        await self.validate_claim_request(claim_data)
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                claim_id = await conn.fetchval("""
                    INSERT INTO claims (
                        claim_type,
                        member_id,
                        hospital_id,
                        admission_date,
                        discharge_date,
                        total_amount,
                        status,
                        created_by,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING claim_id
                """,
                    claim_data.claim_type,
                    claim_data.member_id,
                    claim_data.hospital_id,
                    claim_data.admission_date,
                    claim_data.discharge_date,
                    claim_data.total_amount,
                    ClaimStatus.PENDING,
                    user_id,
                    datetime.now(timezone.utc)
                )
                
                # Create document links
                if claim_data.documents:
                    await conn.executemany("""
                        INSERT INTO claim_documents (
                            claim_id,
                            document_id,
                            document_type,
                            upload_timestamp
                        ) VALUES ($1, $2, $3, $4)
                    """, [
                        (claim_id, doc['id'], doc['type'], datetime.now(timezone.utc))
                        for doc in claim_data.documents
                    ])
                    
                # Initialize processing record
                await conn.execute("""
                    INSERT INTO claim_processing (
                        claim_id,
                        status,
                        created_at
                    ) VALUES ($1, $2, $3)
                """,
                    claim_id,
                    ClaimStatus.PENDING,
                    datetime.now(timezone.utc)
                )
                
                self.logger.info("Claim created", claim_id=claim_id)
                return claim_id

    @db_error_handler
    async def get_claim_details(
        self,
        claim_id: str,
        include_documents: bool = True,
        include_processing: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Get comprehensive claim details"""
        self.logger = self.logger.bind(claim_id=claim_id)
        async with self.pool.acquire() as conn:
            # Get base claim data
            claim = await conn.fetchrow("""
                SELECT 
                    c.*,
                    m.full_name as member_name,
                    p.provider_name as hospital_name
                FROM claims c
                JOIN members m ON c.member_id = m.member_id
                JOIN providers p ON c.hospital_id = p.provider_id
                WHERE c.claim_id = $1
            """, claim_id)
            
            if not claim:
                return None
                
            result = dict(claim)
            
            if include_documents:
                result['documents'] = await self._get_claim_documents(conn, claim_id)
            
            if include_processing:
                result['processing_history'] = await self._get_claim_processing_history(conn, claim_id)
            
            self.logger.info("Claim details retrieved")
            return result

    async def _get_claim_documents(self, conn: asyncpg.Connection, claim_id: str) -> List[Dict[str, Any]]:
        """Retrieve documents linked to a claim"""
        documents = await conn.fetch("""
            SELECT 
                d.*,
                cd.document_type,
                cd.upload_timestamp
            FROM documents d
            JOIN claim_documents cd ON d.document_id = cd.document_id
            WHERE cd.claim_id = $1
            ORDER BY cd.upload_timestamp DESC
        """, claim_id)
        return [dict(doc) for doc in documents]

    async def _get_claim_processing_history(self, conn: asyncpg.Connection, claim_id: str) -> List[Dict[str, Any]]:
        """Retrieve processing history of a claim"""
        processing = await conn.fetch("""
            SELECT *
            FROM claim_processing
            WHERE claim_id = $1
            ORDER BY created_at DESC
        """, claim_id)
        return [dict(proc) for proc in processing]

    @db_error_handler
    async def update_claim_status(
        self,
        claim_id: str,
        new_status: ClaimStatus,
        user_id: str,
        notes: Optional[str] = None
    ) -> bool:
        """Update claim status with validation"""
        self.logger = self.logger.bind(claim_id=claim_id, user_id=user_id)
        async with self.pool.acquire() as conn:
            # Verify claim exists and check current status
            current_status = await conn.fetchval("""
                SELECT status
                FROM claims
                WHERE claim_id = $1
            """, claim_id)
            
            if not current_status:
                return False
                
            # Validate status transition
            if not self._is_valid_status_transition(
                ClaimStatus(current_status),
                new_status
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status transition from {current_status} to {new_status}"
                )
            
            async with conn.transaction():
                # Update claim status
                await conn.execute("""
                    UPDATE claims
                    SET status = $1,
                        updated_at = $2,
                        updated_by = $3
                    WHERE claim_id = $4
                """,
                    new_status,
                    datetime.now(timezone.utc),
                    user_id,
                    claim_id
                )
                
                # Create processing record
                await conn.execute("""
                    INSERT INTO claim_processing (
                        claim_id,
                        status,
                        notes,
                        created_by,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5)
                """,
                    claim_id,
                    new_status,
                    notes,
                    user_id,
                    datetime.now(timezone.utc)
                )
                
                self.logger.info("Claim status updated", new_status=new_status)
                return True

    def _is_valid_status_transition(
        self,
        current: ClaimStatus,
        new: ClaimStatus
    ) -> bool:
        """Validate claim status transition"""
        # Define valid transitions
        valid_transitions = {
            ClaimStatus.PENDING: {
                ClaimStatus.PROCESSING,
                ClaimStatus.CANCELLED
            },
            ClaimStatus.PROCESSING: {
                ClaimStatus.APPROVED,
                ClaimStatus.REJECTED
            },
            ClaimStatus.APPROVED: set(),  # Terminal state
            ClaimStatus.REJECTED: set(),  # Terminal state
            ClaimStatus.CANCELLED: set()  # Terminal state
        }
        
        return new in valid_transitions.get(current, set())
