from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import asyncio
import json
import traceback
import structlog
import redis.asyncio as redis
from enum import Enum
from collections import defaultdict
import uuid
from contextlib import asynccontextmanager

class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass

class ClaimErrorCategory(Enum):
    """Error categories for claim processing."""
    VALIDATION = "validation"
    TRANSLATION = "translation"
    CACHE = "cache"
    REDIS = "redis"
    AIRTABLE = "airtable"
    PHILHEALTH = "philhealth"
    PROCESSING = "processing"
    UNKNOWN = "unknown"

@dataclass
class ProcessingMetrics:
    """Comprehensive processing metrics."""
    processing_times: List[float] = field(default_factory=list)
    error_counts: Dict[ClaimErrorCategory, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    translation_confidence_scores: List[float] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    total_claims: int = 0
    manual_reviews: int = 0

class ProductionCache:
    """Placeholder for the ProductionCache class."""
    async def get(self, key: str, correlation_id: str) -> Optional[Dict]:
        return None

    async def _update_local(self, key: str, value: Dict):
        pass

class IntegratedClaimsProcessor:
    """Production-ready integrated claims processor."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        airtable_client: Any,
        code_translator: Any,
        cache: ProductionCache,
        logger: Optional[structlog.BoundLogger] = None,
        **config
    ):
        """
        Initialize claims processor with all components.

        Args:
            redis_client: Redis client for caching
            airtable_client: Airtable client for storage
            code_translator: Code translation service
            cache: Enhanced cache implementation
            logger: Optional structured logger
            **config: Configuration including thresholds and settings
        """
        self.redis = redis_client
        self.airtable = airtable_client
        self.translator = code_translator
        self.cache = cache
        self.logger = logger or structlog.get_logger()
        self.config = {
            'manual_review_threshold': 100000,
            'translation_confidence_threshold': 0.8,
            'max_retries': 3,
            'batch_size': 50,
            'alert_thresholds': {
                'error_rate': 0.1,
                'processing_time': 30,
                'low_confidence_rate': 0.2
            },
            **config
        }
        
        self.metrics = ProcessingMetrics()
        self._lock = asyncio.Lock()

    async def process_claim(
        self,
        claim_data: Dict,
        documents: Dict[str, Any],
        user_id: str,
        correlation_id: Optional[str] = None
    ) -> Dict:
        """
        Process claim with comprehensive error handling and monitoring.

        Args:
            claim_data: Claim details and codes
            documents: Supporting documents
            user_id: Processing user ID
            correlation_id: Optional correlation ID for tracking

        Returns:
            Processed claim result

        Raises:
            ValidationError: If claim validation fails
            TranslationError: If code translation fails
            ProcessingError: If claim processing fails
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        logger = self.logger.bind(
            correlation_id=correlation_id,
            claim_id=claim_data.get('claim_id'),
            user_id=user_id
        )
        
        start_time = datetime.utcnow()
        
        try:
            logger.info("claim_processing_started")
            
            # Validate claim data
            await self._validate_claim(claim_data, logger)
            
            # Try cache first
            cache_key = f"claim:{claim_data.get('claim_id')}"
            cached_result = await self.cache.get(
                cache_key,
                correlation_id
            )
            
            if cached_result:
                self.metrics.cache_hits += 1
                logger.info("cache_hit_returning_result")
                return cached_result

            self.metrics.cache_misses += 1
            
            # Translate codes
            translated_claim = await self._translate_codes(
                claim_data,
                logger
            )
            
            # Process documents
            doc_results = await self._process_documents(
                claim_data.get('claim_id'),
                documents,
                translated_claim,
                logger
            )
            
            # Calculate benefits
            benefits = await self._calculate_benefits(
                translated_claim,
                doc_results,
                logger
            )
            
            # Determine if manual review is needed
            requires_review = await self._check_review_required(
                translated_claim,
                benefits,
                logger
            )
            
            if requires_review:
                self.metrics.manual_reviews += 1
                logger.info("manual_review_required")
                result = await self._manual_adjudication_flow(
                    translated_claim,
                    benefits,
                    logger
                )
            else:
                result = await self._auto_adjudication_flow(
                    translated_claim,
                    benefits,
                    logger
                )
            
            # Store result in cache
            await self.cache._update_local(cache_key, result)
            
            # Record metrics
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.metrics.processing_times.append(duration)
            self.metrics.total_claims += 1
            
            # Check alerts
            await self._check_processing_alerts(logger)
            
            logger.info("claim_processing_completed",
                duration=duration,
                requires_review=requires_review
            )
            
            return result

        except Exception as e:
            error_category = self._categorize_error(e)
            self.metrics.error_counts[error_category] += 1
            self.metrics.last_error_time = datetime.utcnow()
            
            logger.error("claim_processing_failed",
                error=str(e),
                error_category=error_category.value,
                stack_trace=traceback.format_exc()
            )
            
            raise

    async def _validate_claim(
        self,
        claim_data: Dict,
        logger: structlog.BoundLogger
    ):
        """Validate claim data with detailed checks."""
        try:
            # Basic field validation
            required_fields = [
                'claim_id', 'member_id', 'diagnosis_codes',
                'claim_type', 'admission_date'
            ]
            
            missing_fields = [
                field for field in required_fields
                if field not in claim_data
            ]
            
            if missing_fields:
                raise ValidationError(
                    f"Missing required fields: {missing_fields}"
                )
            
            # Validate SNOMED codes
            invalid_codes = []
            for code in claim_data['diagnosis_codes']:
                if not self._is_valid_snomed_format(code):
                    invalid_codes.append(code)
            
            if invalid_codes:
                raise ValidationError(
                    "Invalid SNOMED codes",
                    {'invalid_codes': invalid_codes}
                )

        except Exception as e:
            logger.error("claim_validation_failed",
                error=str(e),
                claim_data=claim_data
            )
            raise

    async def _translate_codes(
        self,
        claim_data: Dict,
        logger: structlog.BoundLogger
    ) -> Dict:
        """Translate codes with confidence tracking."""
        try:
            translations = await self.translator.translate_batch(
                claim_data['diagnosis_codes']
            )
            
            # Track confidence scores
            confidence_scores = [
                t['confidence'] for t in translations.values()
            ]
            self.metrics.translation_confidence_scores.extend(
                confidence_scores
            )
            
            # Check confidence thresholds
            low_confidence = [
                code for code, trans in translations.items()
                if trans['confidence'] < self.config['translation_confidence_threshold']
            ]
            
            if low_confidence:
                logger.warning("low_confidence_translations",
                    codes=low_confidence
                )
            
            return {
                **claim_data,
                'translations': translations,
                'low_confidence_codes': low_confidence
            }

        except Exception as e:
            logger.error("code_translation_failed",
                error=str(e),
                codes=claim_data['diagnosis_codes']
            )
            raise

    async def _check_processing_alerts(
        self,
        logger: structlog.BoundLogger
    ):
        """Check and log processing alerts."""
        if not self.metrics.total_claims:
            return
            
        # Check error rate
        error_rate = sum(self.metrics.error_counts.values()) / self.metrics.total_claims
        if error_rate > self.config['alert_thresholds']['error_rate']:
            logger.warning("high_error_rate_alert",
                error_rate=error_rate,
                error_distribution=dict(self.metrics.error_counts)
            )
        
        # Check processing times
        if self.metrics.processing_times:
            p95_time = sorted(self.metrics.processing_times)[int(len(self.metrics.processing_times) * 0.95)]
            if p95_time > self.config['alert_thresholds']['processing_time']:
                logger.warning("slow_processing_alert",
                    p95_processing_time=p95_time
                )
        
        # Check translation confidence
        if self.metrics.translation_confidence_scores:
            low_confidence_rate = sum(
                1 for score in self.metrics.translation_confidence_scores
                if score < self.config['translation_confidence_threshold']
            ) / len(self.metrics.translation_confidence_scores)
            
            if low_confidence_rate > self.config['alert_thresholds']['low_confidence_rate']:
                logger.warning("low_confidence_rate_alert",
                    low_confidence_rate=low_confidence_rate
                )

    def _categorize_error(self, error: Exception) -> ClaimErrorCategory:
        """Categorize error for metrics and handling."""
        error_type = type(error).__name__
        
        if 'Validation' in error_type:
            return ClaimErrorCategory.VALIDATION
        elif 'Translation' in error_type:
            return ClaimErrorCategory.TRANSLATION
        elif 'Redis' in error_type:
            return ClaimErrorCategory.REDIS
        elif 'Airtable' in error_type:
            return ClaimErrorCategory.AIRTABLE
        elif 'PhilHealth' in error_type:
            return ClaimErrorCategory.PHILHEALTH
        elif 'Processing' in error_type:
            return ClaimErrorCategory.PROCESSING
        
        return ClaimErrorCategory.UNKNOWN

    async def get_processing_metrics(self) -> Dict[str, Any]:
        """Get comprehensive processing metrics."""
        if not self.metrics.processing_times:
            return {
                'total_claims': 0,
                'error_rate': 0,
                'average_processing_time': 0,
                'cache_hit_rate': 0
            }

        total_errors = sum(self.metrics.error_counts.values())
        total_claims = self.metrics.total_claims or 1  # Avoid division by zero
        processing_times = self.metrics.processing_times
        translation_confidence_scores = self.metrics.translation_confidence_scores

        return {
            'total_claims': self.metrics.total_claims,
            'error_rate': total_errors / total_claims,
            'error_distribution': dict(self.metrics.error_counts),
            'average_processing_time': sum(processing_times) / len(processing_times),
            'p95_processing_time': sorted(processing_times)[int(len(processing_times) * 0.95)],
            'cache_hit_rate': self.metrics.cache_hits / (self.metrics.cache_hits + self.metrics.cache_misses),
            'manual_review_rate': self.metrics.manual_reviews / total_claims,
            'translation_confidence': {
                'average': sum(translation_confidence_scores) / len(translation_confidence_scores),
                'low_confidence_rate': sum(1 for score in translation_confidence_scores if score < self.config['translation_confidence_threshold']) / len(translation_confidence_scores)
            }
        }

# Example usage
if __name__ == "__main__":
    import asyncio
    import structlog
    import redis.asyncio as redis

    async def main():
        redis_client = redis.Redis()
        airtable_client = None  # Replace with actual Airtable client
        code_translator = None  # Replace with actual code translator
        cache = ProductionCache()
        logger = structlog.get_logger()

        processor = IntegratedClaimsProcessor(
            redis_client=redis_client,
            airtable_client=airtable_client,
            code_translator=code_translator,
            cache=cache,
            logger=logger
        )
        metrics = await processor.get_processing_metrics()
        print(metrics)

    asyncio.run(main())