from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
import os
import asyncpg
import redis
from fastapi import FastAPI
from contextlib import asynccontextmanager

# Create SQLAlchemy base class
Base = declarative_base()

# Create database URL
DB_URL = URL.create(
    drivername="postgresql+asyncpg",
    username=os.getenv("DB_USER", "claimsuser"),
    password=os.getenv("DB_PASSWORD", "Claims2024#Secure!"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", 5432),
    database=os.getenv("DB_NAME", "claimsdb")
)

# Create engine and session factory
engine = create_engine(str(DB_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Initialize models
def init_models():
    Base.metadata.create_all(bind=engine)

# Create asyncpg pool
pool = None

async def init_db_pool():
    global pool
    pool = await asyncpg.create_pool(
        dsn="your_dsn",
        min_size=5,
        max_size=50,
        max_inactive_connection_lifetime=300
    )

# Create Redis cache
cache = redis.StrictRedis(host="localhost", port=6379, db=0)

def get_cached_query_result(key: str, query: str, db):
    result = cache.get(key)
    if not result:
        result = db.execute(query)
        cache.setex(key, 300, result)
    return result

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    yield
    if pool:
        await pool.close()

app = FastAPI(lifespan=lifespan)