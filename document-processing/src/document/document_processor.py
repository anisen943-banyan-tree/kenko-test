import asyncio
import asyncpg
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from document_processing.src.claims_processor import VerificationStatus, DocumentType, ProcessorConfig, DocumentMetadata

class VerificationStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    VERIFIED = "Verified"
    REJECTED = "Rejected"
    ARCHIVED = "Archived"

class DocumentType(str, Enum):
    DISCHARGE_SUMMARY = "DischargeNote"
    BILL = "Bill"
    LAB_REPORT = "LabReport"
    PRESCRIPTION = "Prescription"
    PHILHEALTH_CLAIM = "PhilHealthClaim"

@dataclass
class ProcessorConfig:
    """Configuration for document processor with enhanced settings."""
    document_bucket: str
    confidence_threshold: float = 0.8
    batch_size: int = 10
    max_connections: int = 20
    min_connections: int = 5
    connection_timeout: int = 10
    cleanup_batch_size: int = 1000
    archive_after_days: int = 365
    index_rebuild_interval: int = 7
    maintenance_interval: int = 86400  # 24 hours
    statement_timeout: int = 30000  # 30 seconds
    idle_timeout: int = 300  # 5 minutes

@dataclass
class DocumentMetadata:
    """Document metadata with enhanced tracking fields."""
    document_id: str
    claim_id: str
    document_type: DocumentType
    upload_timestamp: datetime
    storage_path: str
    verification_status: VerificationStatus
    confidence_scores: Dict[str, float]
    verified_by: Optional[str] = None
    verification_notes: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    processing_stats: Dict = field(default_factory=dict)

class DocumentProcessor:
    """Enhanced document processor with improved PostgreSQL optimizations."""
    
    def __init__(self, pool: asyncpg.Pool, config: ProcessorConfig):
        self.pool = pool
        self.config = config
        self.logger = structlog.get_logger()
        self._cleanup_lock = asyncio.Lock()
        self._maintenance_task = None
        self._partition_lock = asyncio.Lock()

    @classmethod
    async def create(cls, dsn: str, config: ProcessorConfig) -> 'DocumentProcessor':
        """Create processor with optimized connection pool and initialization."""
        pool = await asyncpg.create_pool(
            dsn,
            min_size=config.min_connections,
            max_size=config.max_connections,
            command_timeout=config.connection_timeout,
            server_settings={
                'jit': 'off',
                'timezone': 'UTC',
                'application_name': 'document_processor',
                'work_mem': '64MB',
                'maintenance_work_mem': '256MB',
                'statement_timeout': str(config.statement_timeout),
                'idle_in_transaction_session_timeout': str(config.idle_timeout * 1000)
            }
        )
        
        processor = cls(pool, config)
        await processor._initialize_schema()
        await processor._ensure_current_partitions()
        processor._start_maintenance_task()
        return processor

    async def _initialize_schema(self):
        """Initialize database schema with enhanced partitioning and indexing."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    document_id BIGSERIAL PRIMARY KEY,
                    claim_id VARCHAR(50) NOT NULL,
                    document_type VARCHAR(50) NOT NULL,
                    upload_timestamp TIMESTAMPTZ NOT NULL,
                    storage_path TEXT NOT NULL,
                    verification_status VARCHAR(20) NOT NULL,
                    verified_by VARCHAR(50),
                    verification_notes TEXT,
                    textract_results JSONB,
                    metadata JSONB DEFAULT '{}',
                    processing_stats JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    last_processed_at TIMESTAMPTZ,
                    CONSTRAINT valid_status CHECK (
                        verification_status IN (
                            'Pending', 'Processing', 'Verified', 
                            'Rejected', 'Archived'
                        )
                    )
                ) PARTITION BY RANGE (upload_timestamp);

                -- Enhanced indexes for common query patterns
                CREATE INDEX IF NOT EXISTS idx_documents_status_timestamp 
                    ON documents(verification_status, upload_timestamp DESC)
                    INCLUDE (claim_id, document_type);
                    
                CREATE INDEX IF NOT EXISTS idx_documents_claim_type 
                    ON documents(claim_id, document_type)
                    INCLUDE (verification_status);
                    
                CREATE INDEX IF NOT EXISTS idx_documents_textract 
                    ON documents USING GIN (textract_results)
                    WHERE verification_status != 'Archived';

                -- Trigger for updated_at and stats tracking
                CREATE OR REPLACE FUNCTION update_document_stats()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    NEW.processing_stats = jsonb_set(
                        COALESCE(NEW.processing_stats, '{}'::jsonb),
                        '{last_modified}',
                        to_jsonb(CURRENT_TIMESTAMP)
                    );
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                DROP TRIGGER IF EXISTS documents_stats_update ON documents;
                CREATE TRIGGER documents_stats_update
                    BEFORE UPDATE ON documents
                    FOR EACH ROW
                    EXECUTE FUNCTION update_document_stats();
            """)

    async def _ensure_current_partitions(self):
        """Ensure partitions exist for recent and upcoming periods."""
        current_year = datetime.now().year
        years_to_create = range(current_year - 1, current_year + 2)
        
        async with self._partition_lock:
            for year in years_to_create:
                await self._create_partition(year)

    async def _create_partition(self, year: int):
        """Create a partition for a specific year if it doesn't exist."""
        partition_name = f'documents_y{year}'
        start_date = f'{year}-01-01'
        end_date = f'{year + 1}-01-01'
        
        async with self.pool.acquire() as conn:
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM pg_class c 
                    JOIN pg_namespace n ON n.oid = c.relnamespace 
                    WHERE c.relname = $1
                )
            """, partition_name)
            
            if not exists:
                self.logger.info(
                    "creating_partition",
                    partition=partition_name,
                    year=year
                )
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {partition_name}
                    PARTITION OF documents
                    FOR VALUES FROM ('{start_date}') TO ('{end_date}');
                """)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def store_document(
        self,
        document: DocumentMetadata,
        textract_results: Dict
    ) -> str:
        """Store document with enhanced error handling and partition management."""
        # Ensure partition exists for document's timestamp
        document_year = document.upload_timestamp.year
        await self._ensure_partition_exists(document_year)
        
        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    start_time = datetime.now()
                    document_id = await conn.fetchval("""
                        INSERT INTO documents (
                            claim_id,
                            document_type,
                            upload_timestamp,
                            storage_path,
                            verification_status,
                            textract_results,
                            verified_by,
                            verification_notes,
                            metadata,
                            processing_stats
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        RETURNING document_id
                    """,
                        document.claim_id,
                        document.document_type.value,
                        document.upload_timestamp,
                        document.storage_path,
                        document.verification_status.value,
                        textract_results,
                        document.verified_by,
                        document.verification_notes,
                        document.metadata,
                        {
                            'created_at': datetime.now().isoformat(),
                            'processing_duration': (
                                datetime.now() - start_time
                            ).total_seconds()
                        }
                    )
                    
                    self.logger.info(
                        "document_stored",
                        document_id=document_id,
                        claim_id=document.claim_id,
                        duration=(datetime.now() - start_time).total_seconds()
                    )
                    
                    return str(document_id)
                    
            except Exception as e:
                self.logger.error(
                    "document_store_failed",
                    error=str(e),
                    claim_id=document.claim_id
                )
                raise

    async def _ensure_partition_exists(self, year: int):
        """Ensure partition exists for a given year."""
        async with self._partition_lock:
            await self._create_partition(year)

    async def get_documents_batch(
        self,
        status: Optional[VerificationStatus] = None,
        claim_id: Optional[str] = None,
        batch_size: Optional[int] = None
    ) -> Tuple[List[DocumentMetadata], Dict]:
        """Get documents batch with enhanced filtering and metrics."""
        params: List[Any] = []
        conditions: List[str] = []
        
        if status:
            conditions.append("verification_status = $1")
            params.append(status.value)
        
        if claim_id:
            conditions.append(f"claim_id = ${len(params) + 1}")
            params.append(claim_id)
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        start_time = datetime.now()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                records = await conn.fetch(f"""
                    SELECT *
                    FROM documents
                    WHERE {where_clause}
                    ORDER BY upload_timestamp DESC
                    LIMIT ${len(params) + 1}
                """, *params, batch_size or self.config.batch_size)
                
                metrics = {
                    'query_duration': (
                        datetime.now() - start_time
                    ).total_seconds(),
                    'records_fetched': len(records),
                    'batch_size': batch_size or self.config.batch_size
                }
                
                return (
                    [
                        DocumentMetadata(
                            document_id=str(r['document_id']),
                            claim_id=r['claim_id'],
                            document_type=DocumentType(r['document_type']),
                            upload_timestamp=r['upload_timestamp'],
                            storage_path=r['storage_path'],
                            verification_status=VerificationStatus(
                                r['verification_status']
                            ),
                            confidence_scores=r['textract_results'].get(
                                'confidence_scores',
                                {}
                            ),
                            verified_by=r['verified_by'],
                            verification_notes=r['verification_notes'],
                            metadata=r['metadata'],
                            processing_stats=r['processing_stats']
                        )
                        for r in records
                    ],
                    metrics
                )

    async def cleanup_old_documents(self):
        """Archive old documents with enhanced tracking."""
        cutoff_date = datetime.now() - timedelta(
            days=self.config.archive_after_days
        )
        
        async with self.pool.acquire() as conn:
            total_archived = 0
            start_time = datetime.now()
            
            while True:
                async with conn.transaction():
                    result = await conn.execute("""
                        WITH archived AS (
                            UPDATE documents 
                            SET verification_status = 'Archived',
                                metadata = jsonb_set(
                                    metadata,
                                    '{archived_at}',
                                    to_jsonb($1::text)
                                )
                            WHERE upload_timestamp < $2
                            AND verification_status != 'Archived'
                            LIMIT $3
                            RETURNING 1
                        )
                        SELECT count(*) FROM archived
                    """,
                        datetime.now().isoformat(),
                        cutoff_date,
                        self.config.cleanup_batch_size
                    )
                    
                    archived_count = int(result.split()[1])
                    total_archived += archived_count
                    
                    if archived_count < self.config.cleanup_batch_size:
                        break
                    
                    await asyncio.sleep(1)  # Prevent resource exhaustion
            
            self.logger.info(
                "cleanup_completed",
                total_archived=total_archived,
                duration=(datetime.now() - start_time).total_seconds()
            )

    async def close(self):
        """Cleanup resources with enhanced error handling."""
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            
        if self.pool:
            try:
                await self.pool.close()
            except Exception as e:
                self.logger.error(
                    "pool_close_error",
                    error=str(e)
                )