import asyncio
import asyncpg
import uuid
import os
from datetime import datetime, timedelta
from enum import Enum
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Dict, List, Optional, Union, Tuple, Any, TypedDict
from dataclasses import dataclass, field

# Type definitions - single source of truth
class DocumentVersion(TypedDict):
    """Document version tracking information"""
    version_id: str
    document_id: str
    created_at: datetime
    status: str
    storage_path: Optional[str]
    changes: Optional[Dict[str, Any]]

class ProcessingResult(TypedDict):
    document: Dict[str, Any]
    versions: List[DocumentVersion]

class DocumentProcessingHistory(TypedDict):
    total_versions: int
    last_updated: datetime
    processing_duration: float

class DocumentResult(TypedDict):
    document: Dict[str, Any]
    processing_history: DocumentProcessingHistory
    versions: Optional[List[DocumentVersion]]

# Enums
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

class PriorityLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"

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
    cleanup_batch_interval: int = 1  # 1 second
    partition_prefix: str = "documents_partition"
    index_rebuild_threshold: int = 1000000000  # 1GB
    partition_interval: str = "yearly"  # or "monthly"
    storage_path: str = "/path/to/documents"  # Default storage path
    priority: PriorityLevel = PriorityLevel.MEDIUM

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
    priority_level: PriorityLevel = PriorityLevel.MEDIUM

@dataclass
class PoolHealthMetrics:
    active_connections: int
    idle_connections: int
    total_connections: int
    waited_count: int
    waited_duration: float

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

                CREATE TABLE IF NOT EXISTS document_versions (
                    version_id UUID PRIMARY KEY,
                    document_id BIGINT NOT NULL,
                    storage_path TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    changes JSONB NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES documents(document_id)
                );

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
            await asyncio.gather(*[self._create_partition(year) for year in years_to_create])

    async def _create_partition(self, year: int):
        """Create a partition for a specific year if it doesn't exist."""
        partition_name = f'{self.config.partition_prefix}_year_{year}'
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

    async def _ensure_partition_exists(self, timestamp: datetime):
        """Ensure partition exists for a given timestamp."""
        year = timestamp.year
        async with self._partition_lock:
            await self._create_partition(year)

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
        await self._ensure_partition_exists(document.upload_timestamp)
        
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

    async def store_documents_batch(
        self,
        documents: List[DocumentMetadata],
        textract_results: List[Dict]
    ) -> List[str]:
        """Optimized batch document storage."""
        async with self.pool.acquire() as conn:
            records = [
                (doc.claim_id, doc.document_type.value, doc.upload_timestamp, doc.storage_path, doc.verification_status.value, result, doc.verified_by, doc.verification_notes, doc.metadata, doc.processing_stats)
                for doc, result in zip(documents, textract_results)
            ]
            await conn.copy_records_to_table(
                'documents',
                records=records,
                columns=['claim_id', 'document_type', 'upload_timestamp', 'storage_path', 'verification_status', 'textract_results', 'verified_by', 'verification_notes', 'metadata', 'processing_stats']
            )
            return [str(doc.document_id) for doc in documents]

    async def get_documents_batch(
        self,
        status: Optional[VerificationStatus] = None,
        claim_id: Optional[str] = None,
        batch_size: Optional[int] = None
    ) -> Tuple[List[DocumentMetadata], Dict[str, Union[int, float]]]:
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
        try:
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
        except Exception as e:
            self.logger.error("document_retrieval_failed", error=str(e))
            return [], {}

    async def get_documents_with_stats(
        self,
        claim_id: str
    ) -> Dict[str, Any]:
        """Get documents with materialized statistics."""
        async with self.pool.acquire() as conn:
            result = await conn.fetch("""
                WITH claim_stats AS MATERIALIZED (
                    SELECT 
                        count(*) as total_docs,
                        avg(extract(epoch from (updated_at - created_at))) as avg_processing_time
                    FROM documents 
                    WHERE claim_id = $1
                )
                SELECT d.*, cs.*
                FROM documents d
                CROSS JOIN claim_stats cs
                WHERE d.claim_id = $1
            """, claim_id)
            
            if not result:
                return {}
            
            document = result[0]
            processing_duration = document['updated_at'] - document['created_at']
            
            return {
                "document": dict(document),
                "processing_history": {
                    "total_versions": document["total_docs"],
                    "last_updated": document["avg_processing_time"],
                    "processing_duration": processing_duration.total_seconds()
                }
            }

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
                    
                    await asyncio.sleep(self.config.cleanup_batch_interval)  # Configurable delay
            
            self.logger.info(
                "cleanup_completed",
                total_archived=total_archived,
                duration=(datetime.now() - start_time).total_seconds(),
                batch_size=self.config.cleanup_batch_size
            )

    async def close(self):
        """Cleanup resources with enhanced error handling."""
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        await self._close_pool()

    async def _close_pool(self):
        if self.pool:
            for _ in range(3):  # Retry up to 3 times
                try:
                    await self.pool.close()
                    break
                except Exception as e:
                    self.logger.error("pool_close_error", error=str(e))
                    await asyncio.sleep(1)

    async def _start_maintenance_task(self):
        """Start and monitor the maintenance task."""
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def _maintenance_loop(self):
        while True:
            try:
                await self._perform_maintenance()
                await asyncio.sleep(self.config.maintenance_interval)
            except Exception as e:
                self.logger.error("maintenance_task_failed", error=str(e), task="perform_maintenance")
                await asyncio.sleep(60)  # Retry after delay

    async def _perform_maintenance(self):
        """Perform maintenance tasks such as cleanup and index rebuilding."""
        await asyncio.gather(
            self._safe_cleanup_old_documents(),
            self._safe_rebuild_indexes()
        )

    async def _safe_cleanup_old_documents(self):
        try:
            await self.cleanup_old_documents()
        except Exception as e:
            self.logger.error("cleanup_failed", error=str(e))

    async def _safe_rebuild_indexes(self):
        try:
            await self.rebuild_indexes()
        except Exception as e:
            self.logger.error("rebuild_indexes_failed", error=str(e))

    async def rebuild_indexes(self):
        """Rebuild indexes to optimize query performance."""
        async with self.pool.acquire() as conn:
            index_size = await conn.fetchval("""
                SELECT pg_total_relation_size('documents');
            """)
            if (index_size > self.config.index_rebuild_threshold):
                await conn.execute("""
                    REINDEX TABLE documents;
                """)
                self.logger.info("indexes_rebuilt", index_size=index_size)

    async def get_pool_health(self) -> PoolHealthMetrics:
        """Monitor connection pool health."""
        stats = self.pool.get_used()
        return PoolHealthMetrics(
            active_connections=stats,
            idle_connections=self.pool._idle_connections,
            total_connections=self.pool._max_size,
            waited_count=self.pool._waiting,
            waited_duration=0.0  # asyncpg doesn't provide duration
        )

    async def _acquire_lock_with_timeout(
        self,
        lock_type: str,
        timeout: int = 5000
    ) -> bool:
        """Acquire advisory lock with timeout."""
        async with self.pool.acquire() as conn:
            lock_acquired = await conn.fetchval("""
                SELECT pg_try_advisory_lock($1)
            """, hash(f"document_processor_{lock_type}"))
            return bool(lock_acquired)

    async def _manage_partitions(self):
        """Proactive partition management."""
        current_date = datetime.now()
        upcoming_months = [
            current_date + timedelta(days=30*i)
            for i in range(3)  # Next 3 months
        ]
        
        for date in upcoming_months:
            await self._ensure_partition_exists(date)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def safe_transaction(
        self,
        queries: List[str],
        params: List[Any]
    ) -> Any:
        """Execute queries in a retryable transaction."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                results = []
                for query, param in zip(queries, params):
                    results.append(await conn.fetch(query, *param))
                return results

    async def schedule_vacuum(self):
        """Schedule VACUUM ANALYZE during low traffic."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                VACUUM ANALYZE documents;
                VACUUM ANALYZE documents_archive;
            """)

    async def create_version(self, document_id: str, changes: Dict[str, Any]) -> str:
        """Create a new version of a document."""
        # Generate a unique version ID
        version_id = str(uuid.uuid4())
        
        # Define storage path and timestamp
        storage_path = f"/path/to/documents/{document_id}/{version_id}"
        created_at = datetime.now()
        
        # Create a DocumentVersion instance
        version = DocumentVersion(
            version_id=version_id,
            document_id=document_id,
            storage_path=storage_path,
            created_at=created_at,
            changes=changes
        )
        
        # Logic to store the version data in the database
        await self.save_version_to_db(version)
        
        # Return the version ID for reference
        return version_id

    async def save_version_to_db(self, version: DocumentVersion):
        """Save the document version to the database."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO document_versions (
                    version_id,
                    document_id,
                    storage_path,
                    created_at,
                    changes
                ) VALUES ($1, $2, $3, $4, $5)
            """, 
            version.version_id,
            version.document_id,
            version.storage_path,
            version.created_at,
            version.changes)

    async def get_document_history(
        self,
        document_id: str,
        include_versions: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Get complete document history including versions and processing stats.
        
        Args:
            document_id: The document identifier
            include_versions: Whether to include version history
            
        Returns:
            Dict containing document history and stats or None if not found
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get base document data
                document = await conn.fetchrow("""
                    SELECT d.*,
                           count(v.version_id) as total_versions,
                           max(v.created_at) as last_version_date
                    FROM documents d
                    LEFT JOIN document_versions v ON d.document_id = v.document_id
                    WHERE d.document_id = $1
                    GROUP BY d.document_id
                """, document_id)
                
                if not document:
                    return None
                
                processing_duration = document['updated_at'] - document['created_at']
                
                result = {
                    "document": dict(document),
                    "processing_history": {
                        "total_versions": document["total_versions"],
                        "last_updated": document["last_version_date"],
                        "processing_duration": processing_duration.total_seconds()
                    }
                }
                
                if include_versions:
                    versions = await conn.fetch("""
                        SELECT version_id, created_at, changes
                        FROM document_versions
                        WHERE document_id = $1
                        ORDER BY created_at DESC
                    """, document_id)
                    result["versions"] = [dict(v) for v in versions]
                
                return result

    async def reprocess_document(
        self,
        document_id: str,
        force: bool = False
    ) -> bool:
        """Reprocess a document with version tracking and validation."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Check if reprocessing is needed
                if not force:
                    last_processed = await conn.fetchval("""
                        SELECT last_processed_at
                        FROM documents
                        WHERE document_id = $1
                    """, document_id)
                    
                    if last_processed and datetime.now() - last_processed < timedelta(hours=24):
                        return False
                
                # Create new version before reprocessing
                previous_status = await conn.fetchval(
                    "SELECT verification_status FROM documents WHERE document_id = $1",
                    document_id
                )
                await self.create_version(document_id, {
                    "reason": "reprocess",
                    "forced": force,
                    "previous_status": previous_status
                })
                
                # Update document status
                await conn.execute("""
                    UPDATE documents
                    SET verification_status = 'Processing',
                        last_processed_at = CURRENT_TIMESTAMP
                    WHERE document_id = $1
                """, document_id)
                
                return True

    async def get_processing_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get comprehensive processing metrics for monitoring.
        
        Args:
            start_date: Optional start date for metrics
            end_date: Optional end date for metrics
            
        Returns:
            Dict containing processing metrics
        """
        async with self.pool.acquire() as conn:
            where_clause = ""
            params = []
            
            if start_date:
                where_clause += " AND upload_timestamp >= $1"
                params.append(start_date)
            if end_date:
                where_clause += f" AND upload_timestamp <= ${len(params) + 1}"
                params.append(end_date)
                
            metrics = await conn.fetch(f"""
                WITH processing_stats AS (
                    SELECT 
                        COUNT(*) as total_documents,
                        verification_status,
                        document_type,
                        AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_processing_time,
                        COUNT(*) FILTER (WHERE (textract_results->>'confidence_score')::float < 0.8) as low_confidence_count
                    FROM documents
                    WHERE TRUE {where_clause}
                    GROUP BY verification_status, document_type
                )
                SELECT *
                FROM processing_stats
            """, *params)
            
            summary = {}
            by_document_type = {}
            
            for m in metrics:
                status = m['verification_status']
                doc_type = m['document_type']
                
                if status not in summary:
                    summary[status] = {
                        "count": 0,
                        "avg_processing_time": 0.0
                    }
                summary[status]["count"] += 1
                summary[status]["avg_processing_time"] += m['avg_processing_time']
                
                if doc_type not in by_document_type:
                    by_document_type[doc_type] = {
                        "total": 0,
                        "low_confidence": 0
                    }
                by_document_type[doc_type]["total"] += 1
                by_document_type[doc_type]["low_confidence"] += m['low_confidence_count']
            
            # Calculate average processing time
            for status in summary:
                count = summary[status]["count"]
                total_time = summary[status]["avg_processing_time"]
                summary[status]["avg_processing_time"] = total_time / count if count > 0 else 0.0
            
            return {
                "summary": summary,
                "by_document_type": by_document_type
            }

    async def archive_document(
        self,
        document_id: str,
        archive_note: Optional[str] = None
    ) -> bool:
        """Archive a document with metadata and version tracking.
        
        Args:
            document_id: Document to archive
            archive_note: Optional note explaining archival reason
            
        Returns:
            bool indicating success
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Create version before archiving
                await self.create_version(document_id, {
                    "reason": "archive",
                    "note": archive_note,
                    "timestamp": datetime.now().isoformat()
                })
                
                # Update document status
                result = await conn.execute("""
                    UPDATE documents
                    SET verification_status = 'Archived',
                        metadata = jsonb_set(
                            metadata,
                            '{archived_info}',
                            $2::jsonb
                        )
                    WHERE document_id = $1
                    AND verification_status != 'Archived'
                """, document_id, {
                    "archived_at": datetime.now().isoformat(),
                    "archive_note": archive_note,
                    "archived_by": "system"  # Could be parameterized
                })
                
                return "UPDATE 1" in result

    async def validate_document_integrity(
        self,
        document_id: str
    ) -> Tuple[bool, List[str]]:
        """Validate document data integrity and consistency.
        
        Args:
            document_id: Document to validate
            
        Returns:
            Tuple of (is_valid, list of validation messages)
        """
        async with self.pool.acquire() as conn:
            messages = []
            
            # Get document data
            document = await conn.fetchrow("""
                SELECT *
                FROM documents
                WHERE document_id = $1
            """, document_id)
            
            if not document:
                return False, ["Document not found"]
                
            # Validate required fields
            required_fields = [
                "claim_id", "document_type", "storage_path",
                "verification_status"
            ]
            
            for field in required_fields:
                if not document.get(field):
                    messages.append(f"Missing required field: {field}")
            
            # Validate file existence
            if document.get("storage_path"):
                file_exists = self._check_file_exists(
                    document["storage_path"]
                )
                if not file_exists:
                    messages.append("Document file not found at storage path")
            
            # Validate version consistency
            versions = await conn.fetch("""
                SELECT COUNT(*) as version_count
                FROM document_versions
                WHERE document_id = $1
            """, document_id)
            
            if versions[0]["version_count"] == 0:
                messages.append("No version history found")
                
            return len(messages) == 0, messages

    def _check_file_exists(self, file_path: str) -> bool:
        """Check if a file exists at the given path."""
        return os.path.exists(file_path)

    async def process_claims(self, claims_data: Dict[str, Any]) -> bool:
        """
        Process a single claim.
        
        Args:
            claims_data (Dict[str, Any]): The data of the claim to process.
        
        Returns:
            bool: True if processed successfully, False otherwise.
        """
        try:
            self.logger.info("Processing claim...", claim_id=claims_data.get("id"))
            # Implement claim processing logic here
            await asyncio.sleep(1)  # Simulate processing delay
            self.logger.info("Claim processed successfully.", claim_id=claims_data.get("id"))
            return True
        except Exception as e:
            self.logger.error("Error processing claim.", claim_id=claims_data.get("id"), error=str(e))
            raise

    async def close_connection(self):
        """Close the database connection."""
        if self.pool:
            await self.pool.close()
            self.logger.info("Database connection closed.")

    async def get_document(self, document_id: str, include_versions: bool = False) -> Optional[DocumentResult]:
        async with self.pool.acquire() as conn:
            document = await conn.fetchrow("""
                SELECT d.*,
                       count(v.version_id) as total_versions,
                       max(v.created_at) as last_version_date
                FROM documents d
                LEFT JOIN document_versions v ON d.document_id = v.document_id
                WHERE d.document_id = $1
                GROUP BY d.document_id
            """, document_id)
            
            if not document:
                return None
            
            processing_duration = document['updated_at'] - document['created_at']
            
            result: DocumentResult = {
                "document": dict(document),
                "processing_history": {
                    "total_versions": document["total_versions"],
                    "last_updated": document["last_version_date"],
                    "processing_duration": processing_duration.total_seconds()
                },
                "versions": None
            }
            
            if include_versions:
                versions = await conn.fetch("""
                    SELECT * FROM document_versions 
                    WHERE document_id = $1
                    ORDER BY created_at DESC
                """, document_id)
                # Convert row to DocumentVersion type
                result["versions"] = [DocumentVersion(**dict(v)) for v in versions]
            
            return result

    # Rename to avoid duplicate definition
    async def trigger_reprocess(
        self,
        document_id: str,
        force: bool = False
    ) -> bool:
        """Reprocess a document with version tracking and validation."""
        try:
            async with self.pool.acquire() as conn:
                # Actual implementation
                await conn.execute(
                    "UPDATE documents SET status = $1 WHERE document_id = $2",
                    'PROCESSING',
                    document_id
                )
                return True
        except Exception as e:
            self.logger.error("Reprocess failed", error=str(e))
            return False

    async def get_document_versions(self, document_id: str) -> ProcessingResult:
        async with self.pool.acquire() as conn:
            result: ProcessingResult = {
                "document": {},
                "versions": []
            }
            
            versions = await conn.fetch("""
                SELECT * FROM document_versions 
                WHERE document_id = $1
                ORDER BY created_at DESC
            """, document_id)
            
            result["versions"] = [DocumentVersion(**dict(v)) for v in versions]
            return result

    async def process_document(self, document_id: str) -> bool:
        """Process document and return success status."""
        try:
            # Implementation
            return True
        except Exception as e:
            self.logger.error("Processing failed", error=str(e))
            return False

# Renamed the local ClaimsProcessor to avoid conflict
class ClaimsProcessor:
    """Local ClaimsProcessor class handling specific processing tasks."""
    
    def __init__(self, config: ProcessorConfig):
        self.config = config
        self.logger = structlog.get_logger(__name__)
        # Initialize other necessary components here
        self.database = None  # Placeholder for database connection
        self.setup_database()
    
    def setup_database(self):
        """Initialize the database connection."""
        try:
            self.logger.info("Setting up database connection...")
            self.database = asyncio.run(asyncpg.create_pool(
                min_size=self.config.min_connections,
                max_size=self.config.max_connections,
                timeout=self.config.connection_timeout,
                database='your_database',
                user='your_user',
                password='your_password',
                host='localhost'
            ))
            self.logger.info("Database connection established.")
        except Exception as e:
            self.logger.error("Failed to connect to the database.", error=str(e))
            raise

    def _check_file_exists(self, file_path: str) -> bool:
        """Check if a file exists at the given path."""
        return os.path.exists(file_path)

    async def process_claims(self, claims_data: Dict[str, Any]) -> bool:
        """
        Process a single claim.
        
        Args:
            claims_data (Dict[str, Any]): The data of the claim to process.
        
        Returns:
            bool: True if processed successfully, False otherwise.
        """
        try:
            self.logger.info("Processing claim...", claim_id=claims_data.get("id"))
            # Implement claim processing logic here
            await asyncio.sleep(1)  # Simulate processing delay
            self.logger.info("Claim processed successfully.", claim_id=claims_data.get("id"))
            return True
        except Exception as e:
            self.logger.error("Error processing claim.", claim_id=claims_data.get("id"), error=str(e))
            raise