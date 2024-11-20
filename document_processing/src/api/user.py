from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from enum import Enum
from datetime import datetime


# Define user roles as an Enum
class UserRole(str, Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STANDARD = "STANDARD"


# Base User model
class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole
    is_active: bool = True  # Default to active


# Model for creating a new user
class UserCreate(UserBase):
    password: str

    @field_validator("password", mode='before')
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


# Model for updating a user
class UserUpdate(BaseModel):
    full_name: Optional[str]
    email: Optional[EmailStr]
    role: Optional[UserRole]
    is_active: Optional[bool]


# Model for the full user data, including metadata
class User(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime