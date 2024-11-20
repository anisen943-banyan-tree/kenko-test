from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from src.db.base import Base

class SubscriptionTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ENTERPRISE = "ENTERPRISE"

class InstitutionCreate(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "Institution Name"})
    code: str = Field(..., json_schema_extra={"example": "INST123"})
    contact_email: EmailStr = Field(..., json_schema_extra={"example": "contact@institution.com"})
    contact_phone: str = Field(..., json_schema_extra={"example": "+1234567890"})
    subscription_tier: SubscriptionTier = Field(..., json_schema_extra={"example": "STANDARD"})

    @field_validator('code', mode='before')
    def validate_code(cls, v):
        if not v.isalnum():
            raise ValueError('Code must be alphanumeric')
        return v.upper()

class InstitutionUpdate(InstitutionCreate):
    status: Optional[str]

class Institution(Base):
    __tablename__ = 'institutions'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    code = Column(String, unique=True, index=True)
    contact_email = Column(String, index=True)
    contact_phone = Column(String)
    subscription_tier = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    documents = relationship("Document", back_populates="institution")

class DocumentType(str, Enum):
    DISCHARGE_SUMMARY = "DischargeNote"
    BILL = "Bill"
    LAB_REPORT = "LabReport"
    PRESCRIPTION = "Prescription"

class DocumentCreate(BaseModel):
    claim_id: str = Field(..., json_schema_extra={"example": "CLAIM123"})
    document_type: DocumentType = Field(..., json_schema_extra={"example": "DischargeNote"})
    storage_path: str = Field(..., json_schema_extra={"example": "/path/to/document"})

class DocumentUpdate(BaseModel):
    verification_status: Optional[str]
    verified_by: Optional[str]
    verification_notes: Optional[str]

class Document(Base):
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(String, index=True)
    document_type = Column(String)
    storage_path = Column(String)
    institution_id = Column(Integer, ForeignKey('institutions.id'))
    institution = relationship("Institution", back_populates="documents")
    upload_timestamp = Column(DateTime, default=datetime.utcnow)
    verification_status = Column(String)
    confidence_scores = Column(JSON, nullable=True)