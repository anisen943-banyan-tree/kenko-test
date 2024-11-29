import pytest
import asyncpg
from datetime import date

# Database configuration
TEST_DB_CONFIG = {
    "user": "claimsuser",
    "password": "default_password",
    "database": "claimsdb_test",
    "host": "localhost",
    "port": 5432,
    "min_size": 1,
    "max_size": 5,  # Reduced pool size
}

# Fixture to set up and clean the database
@pytest.fixture
async def db_pool():
    """Create and clean test database."""
    pool = await asyncpg.create_pool(**TEST_DB_CONFIG, max_size=5)  # Limit pool size
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id SERIAL PRIMARY KEY,
                claim_amount NUMERIC,
                claim_type TEXT,
                admission_date DATE,
                discharge_date DATE,
                status TEXT
            )
            """
        )
    yield pool
    await pool.close()  # Close pool after tests


# Test cases
@pytest.mark.asyncio
async def test_claim_creation(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO claims (claim_type, claim_amount) VALUES ($1, $2)",
            "Medical",
            1000,
        )
        result = await conn.fetch("SELECT * FROM claims WHERE claim_type = $1", "Medical")
        assert len(result) == 1
        # Cleanup
        await conn.execute("DELETE FROM claims WHERE claim_type = $1", "Medical")
    await conn.close()  # Close connection


@pytest.mark.asyncio
async def test_claim_update_status(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO claims (claim_type, claim_amount, status) VALUES ($1, $2, $3)",
            "Medical",
            1000,
            "Pending",
        )
        await conn.execute(
            "UPDATE claims SET status = $1 WHERE claim_type = $2",
            "Approved",
            "Medical",
        )
        result = await conn.fetchrow(
            "SELECT status FROM claims WHERE claim_type = $1", "Medical"
        )
        assert result["status"] == "Approved"
        # Cleanup
        await conn.execute("DELETE FROM claims WHERE claim_type = $1", "Medical")
    await conn.close()  # Close connection


@pytest.mark.asyncio
async def test_claim_amount_validation(db_pool):
    async with db_pool.acquire() as conn:
        with pytest.raises(asyncpg.exceptions.NumericValueOutOfRangeError):
            await conn.execute(
                "INSERT INTO claims (claim_type, claim_amount) VALUES ($1, $2)",
                "Medical",
                1e10,  # Exceeds NUMERIC(10, 2)
            )
    await conn.close()  # Close connection


@pytest.mark.asyncio
async def test_future_admission_date(db_pool):
    async with db_pool.acquire() as conn:
        future_date = date.today().replace(year=date.today().year + 1)
        await conn.execute(
            "INSERT INTO claims (claim_type, claim_amount, admission_date) VALUES ($1, $2, $3)",
            "Medical",
            1000,
            future_date,
        )
        result = await conn.fetchrow(
            "SELECT admission_date FROM claims WHERE claim_type = $1", "Medical"
        )
        assert result["admission_date"] == future_date
        # Cleanup
        await conn.execute("DELETE FROM claims WHERE claim_type = $1", "Medical")
    await conn.close()  # Close connection
