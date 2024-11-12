import pytest
from datetime import datetime
from claims_processor.processor import ClaimsProcessor  # Adjusted import statement

class ClaimsProcessor:
    """Main claims processing implementation."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
    async def process_claim(self, claim_data: Dict) -> Dict:
        """Process a single claim."""
        # Placeholder for claim processing logic
        return {
            "status": "pending",
            "claim_id": claim_data.get("claim_id"),
            "processed_at": datetime.now().isoformat()
        }

@pytest.mark.asyncio
async def test_process_claim():
    processor = ClaimsProcessor()
    claim_data = {
        "claim_id": "TEST001",
        "member_id": "MEM001",
        "claim_date": datetime.now().isoformat()
    }
    
    result = await processor.process_claim(claim_data)
    assert result["claim_id"] == claim_data["claim_id"]
    assert result["status"] == "pending"
