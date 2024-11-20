import asyncpg
from typing import Any

async def get_db_pool(database_url: str) -> Any:
    """Create a database connection pool."""
    try:
        return await asyncpg.create_pool(dsn=database_url)
    except Exception as e:
        # Add logging or error handling
        print(f"Error creating database pool: {e}")
        raise

