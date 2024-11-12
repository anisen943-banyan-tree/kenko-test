import pytest
from datetime import datetime
from typing import Dict, Optional
from claims_processor.processor import ClaimsProcessor  # Adjusted import statement

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
