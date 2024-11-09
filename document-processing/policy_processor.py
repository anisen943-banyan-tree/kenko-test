from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import asyncpg
import os

class PolicyType(str, Enum):
    INDIVIDUAL = "individual"
    GROUP = "group"
    CORPORATE = "corporate"

class CoverageType(str, Enum):
    IPD = "ipd"
    OPD = "opd"
    COMPREHENSIVE = "comprehensive"

@dataclass
class PolicyBenefit:
    """Policy benefit details"""
    benefit_id: str
    benefit_type: str
    coverage_limit: float
    sub_limits: Dict[str, float]
    waiting_period: Optional[int] = None
    exclusions: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.coverage_limit < 0:
            raise ValueError("Coverage limit must be non-negative")
        for sub_limit in self.sub_limits.values():
            if sub_limit < 0:
                raise ValueError("Sub-limits must be non-negative")

@dataclass
class PolicyTerms:
    """Policy terms and conditions"""
    policy_id: str
    policy_type: PolicyType
    coverage_type: CoverageType
    start_date: datetime
    end_date: datetime
    premium_amount: float
    benefits: List[PolicyBenefit]
    philhealth_integrated: bool
    max_coverage: float
    deductible: Optional[float] = None

    def __post_init__(self):
        if self.premium_amount < 0:
            raise ValueError("Premium amount must be non-negative")
        if self.max_coverage < 0:
            raise ValueError("Max coverage must be non-negative")
        if self.deductible is not None and self.deductible < 0:
            raise ValueError("Deductible must be non-negative")
        if self.start_date >= self.end_date:
            raise ValueError("Start date must be before end date")

class PolicyProcessor:
    """Processor for handling policy operations"""

    def __init__(self, db_pool: asyncpg.Pool):
        self.pool = db_pool
        self.logger = structlog.get_logger()
        self.retry_attempts = int(os.getenv('RETRY_ATTEMPTS', 3))
        self.retry_multiplier = int(os.getenv('RETRY_MULTIPLIER', 1))
        self.retry_min = int(os.getenv('RETRY_MIN', 2))
        self.retry_max = int(os.getenv('RETRY_MAX', 10))

    @retry(stop=stop_after_attempt(self.retry_attempts), wait=wait_exponential(multiplier=self.retry_multiplier, min=self.retry_min, max=self.retry_max), retry=retry_if_exception_type(asyncpg.PostgresError))
    async def initialize_schema(self):
        """Initialize the database schema for policies"""
        try:
            async with self.pool.acquire() as connection:
                await connection.execute("""
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY,
                    policy_type TEXT,
                    coverage_type TEXT,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    premium_amount FLOAT,
                    philhealth_integrated BOOLEAN,
                    max_coverage FLOAT,
                    deductible FLOAT DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS benefits (
                    benefit_id TEXT PRIMARY KEY,
                    policy_id TEXT REFERENCES policies(policy_id) ON DELETE CASCADE,
                    benefit_type TEXT,
                    coverage_limit FLOAT,
                    sub_limits JSONB,
                    waiting_period INT DEFAULT 0,
                    exclusions TEXT[]
                );
                """)
                self.logger.info("Schema initialized successfully")
        except asyncpg.PostgresError as e:
            self.logger.error("Failed to initialize schema", error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error during schema initialization", error=str(e))
            raise

    async def add_policy(self, policy: PolicyTerms):
        """Add a new policy to the database"""
        try:
            async with self.pool.acquire() as connection:
                await connection.execute("""
                INSERT INTO policies (policy_id, policy_type, coverage_type, start_date, end_date, premium_amount, philhealth_integrated, max_coverage, deductible)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, policy.policy_id, policy.policy_type.value, policy.coverage_type.value, policy.start_date, policy.end_date, policy.premium_amount, policy.philhealth_integrated, policy.max_coverage, policy.deductible)
                
                benefits_data = [
                    (benefit.benefit_id, policy.policy_id, benefit.benefit_type, benefit.coverage_limit, benefit.sub_limits, benefit.waiting_period, benefit.exclusions)
                    for benefit in policy.benefits
                ]
                await connection.executemany("""
                INSERT INTO benefits (benefit_id, policy_id, benefit_type, coverage_limit, sub_limits, waiting_period, exclusions)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, benefits_data)
                
                self.logger.info("Policy added successfully", policy_id=policy.policy_id)
        except asyncpg.PostgresError as e:
            self.logger.error("Failed to add policy", policy_id=policy.policy_id, error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error during policy addition", policy_id=policy.policy_id, error=str(e))
            raise

    async def get_policy(self, policy_id: str) -> Optional[PolicyTerms]:
        """Retrieve a policy from the database by its ID"""
        try:
            async with self.pool.acquire() as connection:
                row = await connection.fetchrow("""
                SELECT p.*, COALESCE(json_agg(b.*) FILTER (WHERE b.benefit_id IS NOT NULL), '[]') AS benefits
                FROM policies p
                LEFT JOIN benefits b ON p.policy_id = b.policy_id
                WHERE p.policy_id = $1
                GROUP BY p.policy_id
                """, policy_id)
                if row:
                    benefits = [PolicyBenefit(**benefit) for benefit in row['benefits']]
                    policy = PolicyTerms(
                        policy_id=row['policy_id'],
                        policy_type=PolicyType(row['policy_type']),
                        coverage_type=CoverageType(row['coverage_type']),
                        start_date=row['start_date'],
                        end_date=row['end_date'],
                        premium_amount=row['premium_amount'],
                        benefits=benefits,
                        philhealth_integrated=row['philhealth_integrated'],
                        max_coverage=row['max_coverage'],
                        deductible=row['deductible']
                    )
                    self.logger.info("Policy retrieved successfully", policy_id=policy_id)
                    return policy
                else:
                    self.logger.warning("Policy not found", policy_id=policy_id)
                    return None
        except asyncpg.PostgresError as e:
            self.logger.error("Failed to retrieve policy", policy_id=policy_id, error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error during policy retrieval", policy_id=policy_id, error=str(e))
            raise

    async def update_policy(self, policy: PolicyTerms):
        """Update an existing policy in the database"""
        try:
            async with self.pool.acquire() as connection:
                await connection.execute("""
                UPDATE policies SET policy_type = $2, coverage_type = $3, start_date = $4, end_date = $5, premium_amount = $6, philhealth_integrated = $7, max_coverage = $8, deductible = $9
                WHERE policy_id = $1
                """, policy.policy_id, policy.policy_type.value, policy.coverage_type.value, policy.start_date, policy.end_date, policy.premium_amount, policy.philhealth_integrated, policy.max_coverage, policy.deductible)
                
                existing_benefits = await connection.fetch("""
                SELECT benefit_id FROM benefits WHERE policy_id = $1
                """, policy.policy_id)
                existing_benefit_ids = {benefit['benefit_id'] for benefit in existing_benefits}
                
                new_benefit_ids = {benefit.benefit_id for benefit in policy.benefits}
                
                benefits_to_delete = existing_benefit_ids - new_benefit_ids
                benefits_to_add = new_benefit_ids - existing_benefit_ids
                benefits_to_update = new_benefit_ids & existing_benefit_ids
                
                if benefits_to_delete:
                    await connection.executemany("""
                    DELETE FROM benefits WHERE benefit_id = $1
                    """, [(benefit_id,) for benefit_id in benefits_to_delete])
                
                if benefits_to_add:
                    benefits_data = [
                        (benefit.benefit_id, policy.policy_id, benefit.benefit_type, benefit.coverage_limit, benefit.sub_limits, benefit.waiting_period, benefit.exclusions)
                        for benefit in policy.benefits if benefit.benefit_id in benefits_to_add
                    ]
                    await connection.executemany("""
                    INSERT INTO benefits (benefit_id, policy_id, benefit_type, coverage_limit, sub_limits, waiting_period, exclusions)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """, benefits_data)
                
                for benefit in policy.benefits:
                    if benefit.benefit_id in benefits_to_update:
                        await connection.execute("""
                        UPDATE benefits SET benefit_type = $3, coverage_limit = $4, sub_limits = $5, waiting_period = $6, exclusions = $7
                        WHERE benefit_id = $1 AND policy_id = $2
                        """, benefit.benefit_id, policy.policy_id, benefit.benefit_type, benefit.coverage_limit, benefit.sub_limits, benefit.waiting_period, benefit.exclusions)
                
                self.logger.info("Policy updated successfully", policy_id=policy.policy_id, added=len(benefits_to_add), updated=len(benefits_to_update), deleted=len(benefits_to_delete))
        except asyncpg.PostgresError as e:
            self.logger.error("Failed to update policy", policy_id=policy.policy_id, error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error during policy update", policy_id=policy.policy_id, error=str(e))
            raise

    async def delete_policy(self, policy_id: str):
        """Delete a policy from the database by its ID"""
        try:
            async with self.pool.acquire() as connection:
                await connection.execute("""
                DELETE FROM benefits WHERE policy_id = $1
                """, policy_id)
                await connection.execute("""
                DELETE FROM policies WHERE policy_id = $1
                """, policy_id)
                self.logger.info("Policy deleted successfully", policy_id=policy_id)
        except asyncpg.PostgresError as e:
            self.logger.error("Failed to delete policy", policy_id=policy_id, error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error during policy deletion", policy_id=policy_id, error=str(e))
            raise
