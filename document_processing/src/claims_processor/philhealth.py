from typing import Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, ValidationError, Field
import asyncpg  # Assuming asyncpg is used for async database operations
from src.claims_processor.philhealth import MembershipStatus, PhilHealthBenefit, MembershipInfo, Claim, MembershipRetrievalError, BenefitCalculationError, PhilHealthService

class MembershipStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    SUSPENDED = "Suspended"

@dataclass
class PhilHealthBenefit:
    """PhilHealth benefit calculation result."""
    case_rate: float
    hospital_share: float
    professional_fee_share: float
    total_benefit: float
    calculation_timestamp: datetime

@dataclass
class MembershipInfo:
    """PhilHealth membership information."""
    membership_number: str
    status: MembershipStatus
    member_name: str
    coverage_valid: bool
    validation_timestamp: datetime

class Claim(BaseModel):
    """Claim model for validation."""
    membership_number: str = Field(..., min_length=5)
    case_rate: float = Field(..., gt=0)

class MembershipRetrievalError(Exception):
    """Custom exception for membership retrieval errors."""
    pass

class BenefitCalculationError(Exception):
    """Custom exception for benefit calculation errors."""
    pass

class PhilHealthService:
    """PhilHealth integration service for claims processing."""
    
    def __init__(self, db_pool, config: Dict):
        self.db = db_pool
        self.config = config
        self.logger = structlog.get_logger()
        self.HOSPITAL_SHARE_PERCENT = 0.80
        self.PF_SHARE_PERCENT = 0.20

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def calculate_benefit(self, case_rate: float) -> PhilHealthBenefit:
        """Calculate PhilHealth benefit based on case rate."""
        start_time = datetime.now()
        try:
            hospital_share = case_rate * self.HOSPITAL_SHARE_PERCENT
            professional_fee_share = case_rate * self.PF_SHARE_PERCENT
            benefit = PhilHealthBenefit(
                case_rate=case_rate,
                hospital_share=hospital_share,
                professional_fee_share=professional_fee_share,
                total_benefit=case_rate,
                calculation_timestamp=datetime.now()
            )
            self.logger.info("Benefit calculated successfully", case_rate=case_rate, benefit=benefit, start_time=start_time, end_time=datetime.now())
            return benefit
        except Exception as e:
            self.logger.error("Benefit calculation failed", case_rate=case_rate, error=str(e), start_time=start_time, end_time=datetime.now())
            raise BenefitCalculationError(f"Failed to calculate benefit for case rate {case_rate}") from e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def get_membership_info(self, membership_number: str) -> MembershipInfo:
        """Retrieve PhilHealth membership information."""
        start_time = datetime.now()
        try:
            # Replace this with actual database call
            async with self.db.acquire() as connection:
                query = "SELECT membership_number, status, member_name, coverage_valid FROM membership WHERE membership_number = $1"
                row = await connection.fetchrow(query, membership_number)
                if row:
                    membership_info = MembershipInfo(
                        membership_number=row['membership_number'],
                        status=MembershipStatus(row['status']),
                        member_name=row['member_name'],
                        coverage_valid=row['coverage_valid'],
                        validation_timestamp=datetime.now()
                    )
                    self.logger.info("Membership info retrieved", membership_number=membership_number, membership_info=membership_info, start_time=start_time, end_time=datetime.now())
                    return membership_info
                else:
                    raise MembershipRetrievalError(f"No membership info found for membership number {membership_number}")
        except asyncpg.PostgresError as e:
            self.logger.error("Database error retrieving membership info", membership_number=membership_number, error=str(e), start_time=start_time, end_time=datetime.now())
            raise MembershipRetrievalError(f"Database error retrieving info for membership number {membership_number}") from e
        except Exception as e:
            self.logger.error("Failed to retrieve membership info", membership_number=membership_number, error=str(e), start_time=start_time, end_time=datetime.now())
            raise MembershipRetrievalError(f"Failed to retrieve info for membership number {membership_number}") from e

    async def process_claim(self, claim: Dict) -> Dict:
        """Process a PhilHealth claim."""
        start_time = datetime.now()
        try:
            validated_claim = Claim(**claim)
            membership_info = await self.get_membership_info(validated_claim.membership_number)
            
            if membership_info.status != MembershipStatus.ACTIVE:
                self.logger.warning("Inactive membership detected", membership_info=membership_info, start_time=start_time, end_time=datetime.now())
                return {
                    "status": "error",
                    "message": "Inactive PhilHealth membership",
                    "membership_info": membership_info
                }

            benefit = await self.calculate_benefit(validated_claim.case_rate)
            self.logger.info("Claim processed successfully", membership_number=validated_claim.membership_number, case_rate=validated_claim.case_rate, start_time=start_time, end_time=datetime.now())
            return {
                "status": "success",
                "benefit": benefit,
                "membership_info": membership_info
            }
        except ValidationError as ve:
            self.logger.error("Claim validation error", error=ve.errors(), start_time=start_time, end_time=datetime.now())
            return {"status": "error", "message": "Invalid claim data", "error": ve.errors()}
        except MembershipRetrievalError as mre:
            self.logger.error("Membership retrieval error", error=str(mre), membership_number=claim.get("membership_number"), start_time=start_time, end_time=datetime.now())
            return {"status": "error", "message": "Failed to retrieve membership info", "error": str(mre)}
        except BenefitCalculationError as bce:
            self.logger.error("Benefit calculation error", error=str(bce), start_time=start_time, end_time=datetime.now())
            return {"status": "error", "message": "Failed to calculate benefit", "error": str(bce)}
        except Exception as e:
            self.logger.error("Unexpected error processing claim", error=str(e), start_time=start_time, end_time=datetime.now())
            return {"status": "error", "message": "Unexpected error processing claim", "error": str(e)}
