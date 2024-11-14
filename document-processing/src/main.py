from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from api.routes import claims, documents, institutions
import asyncpg
import uuid
import logging
from pydantic import BaseSettings
import os
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "t")

settings = Settings()

app = FastAPI(
    title="Kenko Document Processing API",
    description="API for processing documents and managing claims, documents, and institutions.",
    version="1.0.0",
    contact={
        "name": "Support Team",
        "email": "support@example.com",
    },
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request and response logging middleware with correlation ID tracking
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    logging.info(f"Request ID: {request_id} - {request.method} {request.url}")
    
    response = await call_next(request)
    
    logging.info(f"Request ID: {request_id} - Status code: {response.status_code}")
    response.headers["X-Request-ID"] = request_id
    return response

@app.on_event("startup")
async def startup():
    try:
        app.state.pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            max_inactive_connection_lifetime=300
        )
        FastAPICache.init(InMemoryBackend())
        logging.info("Database pool created successfully.")
    except Exception as e:
        logging.error(f"Error creating database pool: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    await app.state.pool.close()

@app.get("/health", tags=["health"])
@cache(expire=60)
async def health_check():
    try:
        async with app.state.pool.acquire(timeout=5) as connection:
            await connection.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = request.state.request_id
    return JSONResponse(
        status_code=500,
        content={
            "message": "An unexpected error occurred.",
            "details": str(exc),
            "request_id": request_id,
        },
    )

app.include_router(claims.router, prefix="/api/v1/claims", tags=["claims"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(institutions.router, prefix="/api/v1/institutions", tags=["institutions"])

# Add any additional middleware or event handlers if needed