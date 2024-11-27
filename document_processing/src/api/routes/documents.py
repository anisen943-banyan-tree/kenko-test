import pytest
from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, APIRouter, Request
from asyncio import Lock
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
import structlog
import asyncio
import jwt
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from httpx import AsyncClient

try:
    from src.document.document_processor import (
        DocumentProcessor,
        ProcessorConfig,
        DocumentMetadata,
        DocumentType,
        VerificationStatus
    )
except ImportError as e:
    raise ImportError("Ensure 'document_processor' module is available in the project.") from e

from src.config.settings import Settings
from src.db import get_db_pool

logger = structlog.get_logger()

security = HTTPBearer()
router = APIRouter()

class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    upload_timestamp: datetime
    message: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "12345",
                "status": "Pending",
                "upload_timestamp": "2023-10-01T12:34:56",
                "message": "Document uploaded successfully"
            }
        }

class DocumentStatusResponse(BaseModel):
    document_id: str
    claim_id: str
    status: str
    confidence_scores: Optional[dict] = None
    verification_notes: Optional[str] = None
    last_updated: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "12345",
                "claim_id": "67890",
                "status": "Verified",
                "confidence_scores": {"field1": 0.95, "field2": 0.85},
                "verification_notes": "Verified by admin",
                "last_updated": "2023-10-01T12:34:56"
            }
        }

class Document(BaseModel):
    title: str
    content: str

lock = Lock()

async def startup_event():
    settings = Settings()
    db_pool = await get_db_pool(settings.database_url)
    processor_config = ProcessorConfig()
    router.state.document_processor = DocumentProcessor(pool=db_pool, config=processor_config)

async def get_document_processor() -> DocumentProcessor:
    """Dependency to get document processor instance."""
    processor = getattr(router.state, 'document_processor', None)
    if not processor:
        raise HTTPException(status_code=500, detail="Document processor not initialized")
    return processor

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, "your-secret-key", algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def check_processing_status(
    document_id: str,
    timeout: int = 60
) -> bool:
    """Check document processing status."""
    elapsed = 0
    interval = 5
    
    while elapsed < timeout:
        status = await get_lambda_task_status(document_id)
        if status == "COMPLETED":
            return True
        elif status == "FAILED":
            raise RuntimeError("Processing failed")
            
        await asyncio.sleep(interval)
        elapsed += interval
        
    raise TimeoutError("Processing timed out")

async def update_processing_status(
    document_id: str,
    status: str,
    db
) -> None:
    """Update document processing status in database."""
    async with db.acquire() as conn:
        try:
            await conn.execute(
                """
                UPDATE documents 
                SET status = $1 
                WHERE id = $2
                """,
                status,
                document_id
            )
        except Exception as e:
            logger.error("Failed to update status", error=str(e))
            raise HTTPException(
                status_code=500,
                detail="Database update failed"
            )

# Dependency to get the document processor from app state
def get_document_processor(request: Request) -> DocumentProcessor:
    processor = getattr(request.app.state, "document_processor", None)
    if not processor:
        raise HTTPException(status_code=500, detail="DocumentProcessor not initialized")
    return processor

@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    verify_jwt_token(credentials)
    if file.content_type not in ["application/pdf", "image/jpeg"]:
        raise HTTPException(status_code=400, detail="Invalid file type")
    try:
        document_id = processor.process(file)
        await update_processing_status(document_id, "Pending", processor.pool)
        try:
            status = await check_processing_status(document_id, timeout=60)
        except TimeoutError:
            logger.error(f"Lambda processing timed out for document: {document_id}")
            raise
        response = DocumentUploadResponse(
            document_id=document_id,
            status="Pending",
            upload_timestamp=datetime.utcnow()
        )
        logger.info("Document uploaded", document_id=document_id)
        return JSONResponse(status_code=201, content=response.dict())
    except Exception as e:
        logger.error("Error uploading document", error=str(e))
        raise HTTPException(status_code=400, detail="Error uploading document")

@router.get("/status/{document_id}", response_model=DocumentStatusResponse)
async def get_status(
    document_id: str,
    processor: DocumentProcessor = Depends(get_document_processor)
) -> DocumentStatusResponse:
    """
    Get the status of a document.
    
    Args:
        document_id: The ID of the document
        processor: Document processor instance
    
    Returns:
        DocumentStatusResponse: The document status
    """
    try:
        document = await processor.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
            
        response = DocumentStatusResponse(
            document_id=document_id,
            claim_id=document.claim_id,
            status=document.verification_status.value,
            confidence_scores=document.confidence_scores,
            verification_notes=document.verification_notes,
            last_updated=document.upload_timestamp
        )
        logger.info("Document status retrieved", document_id=document_id)
        return response
        
    except Exception as e:
        logger.error("Error retrieving document status", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Unexpected error encountered"
        )

async def get_document_status(
    document_id: str,
    token: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    """Get document processing status."""
    try:
        document = await processor.get_document(document_id)
        if not document:
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        return DocumentStatusResponse(
            document_id=document_id,
            claim_id=document.claim_id,
            status=document.verification_status.value,
            confidence_scores=document.confidence_scores,
            verification_notes=document.verification_notes,
            last_updated=document.upload_timestamp
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "document_status_check_failed",
            error=str(e),
            document_id=document_id
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve document status"
        )

@router.get("/documents/claim/{claim_id}", response_model=List[DocumentStatusResponse])
async def get_claim_documents(
    claim_id: str,
    token: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    """Get all documents for a claim."""
    try:
        documents = await processor.get_documents_batch(claim_id=claim_id)
        
        return [
            DocumentStatusResponse(
                document_id=doc.document_id,
                claim_id=doc.claim_id,
                status=doc.verification_status.value,
                confidence_scores=doc.confidence_scores,
                verification_notes=doc.verification_notes,
                last_updated=doc.upload_timestamp
            )
            for doc in documents
        ]

    except Exception as e:
        logger.error(
            "claim_documents_fetch_failed",
            error=str(e),
            claim_id=claim_id
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve claim documents"
        )

@router.post("/documents/{document_id}/verify")
async def verify_document(
    document_id: str,
    verification_notes: str,
    token: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    """Manually verify a document."""
    try:
        updated = await processor.update_document_status(
            document_id=document_id,
            status=VerificationStatus.VERIFIED,
            verification_notes=verification_notes,
            verified_by=token.credentials  # In practice, extract user ID from token
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        return JSONResponse(
            content={
                "message": "Document verified successfully",
                "document_id": document_id
            },
            status_code=200
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "document_verification_failed",
            error=str(e),
            document_id=document_id
        )
        raise HTTPException(
            status_code=500,
            detail="Document verification failed"
        )

@router.post("/documents")
async def process_document(doc: Document):
    try:
        validated_doc = Document(**doc.dict())
    except ValidationError as e:
        return {"error": str(e)}
    # ...existing code...

@router.get("/documents/processor")
async def get_processor(request: Request):
    processor = request.app.state.document_processor
    return {"processor_status": processor.status()}

def get_document_processor(request: Request):
    return request.app.state.document_processor

@router.get("/health")
async def health_check():
    try:
        async with router.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@router.get("/documents/health", tags=["health"])
async def check_health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy"}

# Export the router
__all__ = ["router"]

@pytest.fixture(autouse=True)
async def mock_dependencies():
    yield

@pytest.mark.asyncio
async def test_upload_document():
    response = await client.post("/documents", json={"key": "value"})
    assert response.status_code == 200
    # ...additional assertions...

import asyncio
import uuid
from fastapi import FastAPI, HTTPException
from unittest.mock import patch, AsyncMock
from src.api.routes import documents  # Adjusted import
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from fastapi.middleware.cors import CORSMiddleware
from asyncpg import UniqueViolationError
from factory import Factory, Faker, SubFactory
from factory.alchemy import SQLAlchemyModelFactory
from datetime import datetime, timedelta
import jwt
import os
import asyncpg  # Added import
from src.api.models import DocumentCreate, DocumentUpdate  # Adjusted import

try:
    from pydantic_settings import BaseSettings  # Updated import
except ImportError:
    raise ImportError("Ensure 'pydantic_settings' module is installed.")

# Local import since test file is in the same directory
try:
    from src.document.document_processor import (
        DocumentProcessor,
        ProcessorConfig,
        DocumentMetadata,
        DocumentType,
        VerificationStatus
    )
except ImportError as e:
    raise ImportError("Ensure 'document_processor' module is available in the project.") from e

# Factory for Document
class DocumentFactory(Factory):
    class Meta:
        model = dict

    id = Faker('random_int', min=1, max=100)
    name = Faker('file_name')
    type = Faker('file_extension')
    created_at = Faker('iso8601')

@pytest.fixture
async def processor_config():
    """Test configuration fixture."""
    return ProcessorConfig(
        document_bucket="test-bucket",
        confidence_threshold=0.8,
        batch_size=5,
        max_connections=5,
        min_connections=2,
        cleanup_batch_size=100,
    )

@pytest.fixture
async def document_processor(processor_config):
    """Fixture for document processor."""
    processor = DocumentProcessor(config=processor_config)
    yield processor
    await processor.close()

class TestDocumentVersioning:
    """Test suite for document versioning functionality."""
    
    @pytest.mark.asyncio
    async def test_create_version(self, document_processor):
        """Test creating a new document version."""
        # Setup
        document_id = str(uuid.uuid4())
        changes = {
            "field_updated": "status",
            "old_value": "pending",
            "new_value": "verified"
        }
        
        # Execute
        version_id = await document_processor.create_version(document_id, changes)
        
        # Verify
        assert version_id is not None, "Version ID should not be None"

# Example function with try-except block
def example_function():
    try:
        # Some code that might raise an exception
        result = some_potentially_failing_operation()
    except Exception as e:
        # Handle the exception
        print(f"An error occurred: {e}")
        result = None
    return result
