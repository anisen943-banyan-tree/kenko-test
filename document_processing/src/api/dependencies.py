# src/api/dependencies.py
import asyncpg
from contextlib import asynccontextmanager
import redis
from retrying import retry
import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.config.settings import settings
import time

# Initialize HTTPBearer security scheme
security = HTTPBearer()

# Database pool management
@asynccontextmanager
async def get_db_pool():
    pool = await asyncpg.create_pool(dsn=settings.database_dsn, min_size=1, max_size=10)
    try:
        yield pool
    finally:
        await pool.close()

# JWT token verification
def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, key=settings.jwt_secret_key, algorithms=["HS256"])
        if payload['exp'] < time.time():
            raise HTTPException(status_code=401, detail="Token expired")
        if "scope" not in payload or not validate_scope(payload['scope']):
            raise HTTPException(status_code=403, detail="Invalid scope")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    payload = verify_jwt_token(credentials.credentials)
    if payload['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload

# Environment-aware configuration
if settings.test_environment == "test":  # Corrected check
    @asynccontextmanager
    async def get_db_pool():
        pool = await asyncpg.create_pool(dsn=settings.test_database_url, min_size=1, max_size=10)
        try:
            yield pool
        finally:
            await pool.close()

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def connect_to_redis():
    return redis.StrictRedis(host='localhost', port=6379, db=0)

redis_client = connect_to_redis()