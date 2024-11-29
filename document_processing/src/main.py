from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from api.routes import claims, documents, institutions
import asyncpg
import uuid
import logging
from pydantic_settings import BaseSettings
import os
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from src.config.settings import settings
from src.api.routes.documents import router as documents_router
from fastapi_limiter import FastAPILimiter
import redis.asyncio as redis
from src.document.document_processor import DocumentProcessor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis_conn = await redis.from_url(
        settings.REDIS_URL,
        encoding="utf8",
        decode_responses=True
    )
    await FastAPILimiter.init(redis_conn)
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    
    try:
        assert settings.database_url, "Database URL is not configured."
        app.state.pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            max_inactive_connection_lifetime=300
        )
        app.state.document_processor = DocumentProcessor()
        logging.info("Database pool, DocumentProcessor, and FastAPICache initialized successfully.")
    except Exception as e:
        logging.error(f"Error during startup: {e}")
        raise
    
    yield
    
    # Shutdown
    await app.state.pool.close()
    await FastAPICache.clear()

app = FastAPI(
    title="Kenko Document Processing API",
    description="API for processing documents and managing claims, documents, and institutions.",
    version="1.0.0",
    lifespan=lifespan,
    contact={
        "name": "Support Team",
        "email": "support@example.com",
    },
)

@app.on_event("startup")
async def on_startup():
    FastAPICache.init(InMemoryBackend())

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
    try:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        logging.info(f"Request ID: {request_id} - {request.method} {request.url}")
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        logging.error(f"Error in log_requests middleware: {e}")
        raise

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
app.include_router(documents_router, prefix="/documents")

# Debugging: Print all registered routes
for route in app.routes:
    print(f"Route: {route.path} - Methods: {route.methods}")

# Add any additional middleware or event handlers if needed