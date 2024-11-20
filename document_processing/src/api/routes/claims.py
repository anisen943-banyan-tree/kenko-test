import os
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
from typing import Dict, List, Optional, Annotated, Literal
import httpx
import asyncpg
import structlog
from datetime import datetime, timedelta
import jwt
from pydantic import BaseModel, Field, validator, ValidationError, field_validator  # Updated import
import logging
import uuid
from pytz import UTC
from redis.asyncio import Redis  # Use redis-py instead of aioredis
from src.api.routes import claims
from contextlib import asynccontextmanager

# Initialize logging with additional context
logger = structlog.get_logger()
app = FastAPI(title="Claims API Gateway")
security = HTTPBearer()
# API Router for v1
v1_router = APIRouter(prefix="/v1")

# Middleware for request tracing
@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response

# CORS configuration
origins = ["https://trusted-domain.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs from environment
DOCUMENT_SERVICE_URL = os.getenv("DOCUMENT_SERVICE_URL", "http://processor.claims-processing.internal:8000")
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "claims-db.internal"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "claimsdb"),
    "user": os.getenv("DB_USER", "claimsuser"),
    "password": os.getenv("DB_PASSWORD", "Claims2024#Secure!")  # Use environment variable in production
}

# Database configuration for testing
TEST_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "claimsdb_test",
    "user": "claimsuser",
    "password": "Claims2024#Secure!"
}

class ClaimRequest(BaseModel):
    """Claim creation request model"""
    claim_type: str
    member_id: str = Field(..., example="12345")
    hospital_id: str = Field(..., example="67890")
    admission_date: Optional[datetime]
    discharge_date: Optional[datetime]
    total_amount: float
    documents: List[str]  # List of document IDs

    @field_validator('total_amount', mode='before')
    @classmethod
    def validate_total_amount(cls, value):
        if value is None or value < 0:
            raise ValueError('Total amount must be non-negative')
        return value

    @field_validator('discharge_date', mode='before')
    @classmethod
    def validate_dates(cls, discharge_date, values):
        admission_date = values.get('admission_date')
        if admission_date and discharge_date and discharge_date < admission_date:
            raise ValueError('Discharge date cannot be before admission date')
        return discharge_date

class ClaimResponse(BaseModel):
    """Claim response model"""
    claim_id: str
    status: str
    created_at: datetime
    documents: List[Dict]
    processing_details: Optional[Dict]

# Error handling
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled error: {exc}", extra={"trace_id": request.state.trace_id})
    return JSONResponse(
        status_code=500,
        content={"status": "error", "error": "Internal Server Error", "trace_id": request.state.trace_id}
    )

@app.exception_handler(asyncpg.exceptions.DataError)
async def data_error_handler(request: Request, exc: asyncpg.exceptions.DataError):
    logging.error(f"Database error: {exc}", extra={"trace_id": request.state.trace_id})
    return JSONResponse(
        status_code=400,
        content={"status": "error", "error": "Invalid data", "trace_id": request.state.trace_id}
    )

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    logging.error(f"Validation error: {exc}", extra={"trace_id": request.state.trace_id})
    return JSONResponse(
        status_code=422,
        content={"status": "error", "error": exc.errors(), "trace_id": request.state.trace_id}
    )

# Enhanced database pool management
async def get_db_pool() -> asyncpg.Pool:
    if not hasattr(app.state, "pool"):
        app.state.pool = await asyncpg.create_pool(**DB_CONFIG)
    return app.state.pool

# Enhanced JWT verification with RBAC
async def verify_token(
    token: HTTPAuthorizationCredentials = Depends(security),
    required_role: Optional[str] = None
) -> Dict:
    """Verify JWT token and check role if required"""
    try:
        payload = jwt.decode(
            token.credentials,
            os.getenv("JWT_SECRET_KEY", "your-secret-key"),
            algorithms=["HS256"]
        )
        
        # Check role if required
        if required_role and payload.get('role') != required_role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
            
        return payload
    except jwt.InvalidTokenError as e:
        logger.error("token_validation_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid authentication token")

async def common_parameters(q: Optional[str] = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

# Enhanced claim endpoints with improved logging and validation
@v1_router.post("/claims", response_model=ClaimResponse, 
               dependencies=[Depends(RateLimiter(times=5, seconds=60))],
               summary="Create a new claim",
               description="Create a claim with the specified details and documents.")
@FastAPILimiter.times(10, seconds=60)
async def create_claim(
    request: Request,
    claim_request: ClaimRequest,
    token_payload: Dict = Depends(verify_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Create a new claim with enhanced logging"""
    trace_id = request.state.trace_id
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                claim_id = await conn.fetchval(
                    """
                    INSERT INTO claims (
                        claim_type,
                        member_id,
                        hospital_id,
                        admission_date,
                        discharge_date,
                        total_amount,
                        status,
                        created_by
                    ) VALUES ($1, $2, $3, $4, $5, $6, 'PENDING', $7)
                    RETURNING claim_id
                """, 
                claim_request.claim_type,
                claim_request.member_id,
                claim_request.hospital_id,
                claim_request.admission_date,
                claim_request.discharge_date,
                claim_request.total_amount,
                token_payload['user_id']
                )
                
                # Link documents
                await conn.executemany("""
                    INSERT INTO claim_documents (claim_id, document_id)
                    VALUES ($1, $2)
                """, [(claim_id, doc_id) for doc_id in claim_request.documents])
                
                # Get complete claim data
                claim_data = await get_claim_details(claim_id, conn)
                
                logger.info("claim_creation_initiated",
                          trace_id=trace_id,
                          user_id=token_payload['user_id'],
                          claim_id=claim_id)
                return ClaimResponse(**claim_data)

    except asyncpg.exceptions.DataError as e:
        logger.error("claim_creation_failed",
                    trace_id=trace_id,
                    error=str(e),
                    user_id=token_payload.get('user_id'))
        raise HTTPException(status_code=400, detail="Invalid data", headers={"X-Trace-ID": trace_id})
    except Exception as e:
        logger.error("claim_creation_failed",
                    trace_id=trace_id,
                    error=str(e),
                    user_id=token_payload.get('user_id'))
        raise HTTPException(status_code=500, detail="Failed to create claim", headers={"X-Trace-ID": trace_id})

@v1_router.get("/claims/{claim_id}", response_model=ClaimResponse,
               summary="Get claim details",
               description="Retrieve the details of a specific claim by its ID.")
async def get_claim(
    claim_id: str,
    commons: Annotated[dict, Depends(common_parameters)],
    token_payload: Dict = Depends(verify_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Get claim details"""
    trace_id = request.state.trace_id
    try:
        async with pool.acquire() as conn:
            claim_data = await get_claim_details(claim_id, conn)
            
            if not claim_data:
                raise HTTPException(status_code=404, detail="Claim not found", headers={"X-Trace-ID": trace_id})
                
            return ClaimResponse(**claim_data)
            
    except HTTPException:
        raise
    except asyncpg.exceptions.DataError as e:
        logger.error("get_claim_failed", error=str(e), claim_id=claim_id, trace_id=trace_id)
        raise HTTPException(status_code=400, detail="Invalid data", headers={"X-Trace-ID": trace_id})
    except Exception as e:
        logger.error("get_claim_failed", error=str(e), claim_id=claim_id, trace_id=trace_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve claim", headers={"X-Trace-ID": trace_id})

@v1_router.get("/claims", response_model=List[ClaimResponse],
               summary="List claims",
               description="List all claims with optional filters for status and member ID.")
async def list_claims(
    commons: Annotated[dict, Depends(common_parameters)],
    status: Optional[str] = None,
    member_id: Optional[str] = None,
    token_payload: Dict = Depends(verify_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """List claims with optional filters"""
    trace_id = request.state.trace_id
    try:
        query = ["SELECT * FROM claims WHERE 1=1"]
        params = []
        
        if status:
            query.append("AND status = $" + str(len(params) + 1))
            params.append(status)
            
        if member_id:
            query.append("AND member_id = $" + str(len(params) + 1))
            params.append(member_id)
            
        query.append("ORDER BY created_at DESC")
        
        async with pool.acquire() as conn:
            claims = await conn.fetch(" ".join(query), *params)
            
            results = []
            for claim in claims:
                claim_details = await get_claim_details(claim['claim_id'], conn)
                results.append(ClaimResponse(**claim_details))
                
            return results
            
    except Exception as e:
        logger.error("list_claims_failed", error=str(e), trace_id=trace_id)
        raise HTTPException(status_code=500, detail="Failed to list claims", headers={"X-Trace-ID": trace_id})

@v1_router.post("/claims/{claim_id}/adjudicate",
                summary="Adjudicate a claim",
                description="Trigger the adjudication process for a specific claim.")
async def adjudicate_claim(
    claim_id: str,
    background_tasks: BackgroundTasks,
    commons: Annotated[dict, Depends(common_parameters)],
    token_payload: Dict = Depends(verify_token),
    pool: asyncpg.Pool = Depends(get_db_pool)
):
    """Trigger claim adjudication"""
    trace_id = request.state.trace_id
    try:
        async with pool.acquire() as conn:
            # Verify claim status
            current_status = await conn.fetchval(
                "SELECT status FROM claims WHERE claim_id = $1",
                claim_id
            )
            
            if not current_status:
                raise HTTPException(status_code=404, detail="Claim not found", headers={"X-Trace-ID": trace_id})
                
            if current_status != 'PENDING':
                raise HTTPException(
                    status_code=400,
                    detail=f"Claim cannot be adjudicated in {current_status} status",
                    headers={"X-Trace-ID": trace_id}
                )
            
            # Update status
            await conn.execute("""
                UPDATE claims 
                SET status = 'PROCESSING',
                    adjudication_started_at = NOW()
                WHERE claim_id = $1
            """, claim_id)
            
            # Trigger adjudication process in background
            background_tasks.add_task(trigger_adjudication, claim_id)
            
            return JSONResponse(
                content={
                    "message": "Adjudication started",
                    "claim_id": claim_id
                },
                headers={"X-Trace-ID": trace_id}
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("adjudicate_claim_failed", error=str(e), claim_id=claim_id, trace_id=trace_id)
        raise HTTPException(status_code=500, detail="Failed to start adjudication", headers={"X-Trace-ID": trace_id})

async def trigger_adjudication(claim_id: str):
    """
    Trigger the adjudication process for a claim
    
    This background task initiates the claim adjudication process. It can:
    - Send a message to a message queue (e.g., RabbitMQ, Redis)
    - Call an external adjudication service
    - Update claim status based on adjudication results
    
    Args:
        claim_id (str): The unique identifier of the claim to be adjudicated
        
    Note:
        This is an async operation that should be handled by a background worker
        to prevent blocking the main application thread
    """
    try:
        logger.info("adjudication_triggered", claim_id=claim_id)
        # Implementation details here
    except Exception as e:
        logger.error("adjudication_failed", 
                    error=str(e),
                    claim_id=claim_id)

async def get_claim_details(claim_id: str, conn: asyncpg.Connection) -> Dict:
    """Get complete claim details including documents"""
    claim = await conn.fetchrow(
        "SELECT * FROM claims WHERE claim_id = $1",
        claim_id
    )
    
    if not claim:
        return None
        
    # Get linked documents
    documents = await conn.fetch("""
        SELECT d.* 
        FROM documents d
        JOIN claim_documents cd ON d.document_id = cd.document_id
        WHERE cd.claim_id = $1
    """, claim_id)
    
    # Get processing details if available
    processing = await conn.fetchrow("""
        SELECT * FROM claim_processing 
        WHERE claim_id = $1
        ORDER BY created_at DESC 
        LIMIT 1
    """, claim_id)
    
    return {
        "claim_id": claim['claim_id'],
        "status": claim['status'],
        "created_at": claim['created_at'],
        "documents": [dict(doc) for doc in documents],
        "processing_details": dict(processing) if processing else None
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context for startup and shutdown events"""
    # Replace startup logic
    app.state.pool = await asyncpg.create_pool(**DB_CONFIG)
    app.state.http_client = httpx.AsyncClient()
    redis = await Redis.from_url("redis://localhost")
    FastAPILimiter.init(redis)
    yield
    # Replace shutdown logic
    await app.state.pool.close()
    await app.state.http_client.aclose()

app.lifespan = lifespan

# Include routers
app.include_router(v1_router)

# Alias for the v1_router
router = v1_router

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
