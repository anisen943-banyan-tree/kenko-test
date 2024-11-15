from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog
from src.document_processor import (
    DocumentProcessor,
    DocumentType,
    VerificationStatus,
    DocumentMetadata
)
import jwt

logger = structlog.get_logger()
app = FastAPI(title="Claims Document Management API")
security = HTTPBearer()

class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    upload_timestamp: datetime
    message: Optional[str] = None

class DocumentStatusResponse(BaseModel):
    document_id: str
    claim_id: str
    status: str
    confidence_scores: Optional[dict] = None
    verification_notes: Optional[str] = None
    last_updated: datetime

@app.on_event("startup")
async def startup_event():
    app.state.document_processor = DocumentProcessor()

async def get_document_processor() -> DocumentProcessor:
    """Dependency to get document processor instance."""
    processor = getattr(app.state, 'document_processor', None)
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

@app.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    verify_jwt_token(credentials)
    try:
        document_id = processor.process(file)
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

@app.get("/status/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    processor: DocumentProcessor = Depends(get_document_processor)
):
    verify_jwt_token(credentials)
    try:
        status = processor.get_status(document_id)
        response = DocumentStatusResponse(
            document_id=document_id,
            claim_id=status.claim_id,
            status=status.status,
            confidence_scores=status.confidence_scores,
            verification_notes=status.verification_notes,
            last_updated=status.last_updated
        )
        logger.info("Document status retrieved", document_id=document_id)
        return JSONResponse(status_code=200, content=response.dict())
    except Exception as e:
        logger.error("Error retrieving document status", error=str(e))
        raise HTTPException(status_code=404, detail="Document not found")

@app.get("/documents/{document_id}", response_model=DocumentStatusResponse)
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

@app.get("/documents/claim/{claim_id}", response_model=List[DocumentStatusResponse])
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

@app.post("/documents/{document_id}/verify")
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
