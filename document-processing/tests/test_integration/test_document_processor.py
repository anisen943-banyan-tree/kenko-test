import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import uuid

# Local import since test file is in the same directory
from src.document.document_processor import (
    DocumentProcessor,
    ProcessorConfig,
    DocumentMetadata,
    DocumentType,
    VerificationStatus
)

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
        archive_after_days=30
    )

@pytest.fixture
async def mock_pool():
    """Mock database pool fixture."""
    pool = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = AsyncMock()
    return pool

@pytest.fixture
async def document_processor(mock_pool, processor_config):
    """Document processor fixture with mocked dependencies."""
    processor = DocumentProcessor(mock_pool, processor_config)
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