import pytest
import asyncio
from unittest.mock import AsyncMock
import uuid

# Local import since test file is in the same directory
try:
    from document_processing.src.document.document_processor import (
        DocumentProcessor,
        ProcessorConfig,
        DocumentMetadata,
        DocumentType,
        VerificationStatus
    )
except ImportError as e:
    raise ImportError("Ensure 'document_processor' module is available in the project.") from e

# Ensure the import path for app is correct
try:
    from document_processing.src.api.main import app
except ImportError as e:
    raise ImportError("Ensure 'api.main' module is available in the project.") from e

# Ensure the some_module is available in the project
try:
    from document_processing.src.claims_processor.processor import ProcessorConfig as ClaimsProcessorConfig
except ImportError as e:
    raise ImportError("Ensure 'claims_processor.processor' module is available in the project.") from e

@pytest.fixture
async def processor_config():
    """Test configuration fixture."""
    return ClaimsProcessorConfig(
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
    yield pool
    await pool.close()  # Ensure the pool is properly closed

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