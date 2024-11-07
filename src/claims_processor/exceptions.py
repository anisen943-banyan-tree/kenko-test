from typing import Optional

class ProcessingError(Exception):
    """Base exception for processing errors."""
    pass

class ValidationError(ProcessingError):
    """Exception raised for validation errors."""
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.field = field
