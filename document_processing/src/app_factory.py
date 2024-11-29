from fastapi import FastAPI, Request, Depends, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_limiter.depends import RateLimiter
from fastapi_limiter import FastAPILimiter
import redis.asyncio as redis
import uuid
from contextlib import asynccontextmanager
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache

from src.config.settings import settings
from src.config.routers import claims_router, documents_router, institutions_router
from src.auth.auth_utils import verify_jwt_token
from src.document.document_processor import DocumentProcessor, ProcessorConfig

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_conn = await redis.from_url(
        settings.REDIS_URL,
        encoding="utf8",
        decode_responses=True
    )
    await FastAPILimiter.init(redis_conn)
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")

    # Initialize and attach document processor to app state
    config = ProcessorConfig(
        redis_url=settings.REDIS_URL,
        max_retries=3,
        timeout=10
    )

    yield

    await FastAPICache.clear()
    await redis_conn.close()

def create_app() -> FastAPI:
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

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust as needed
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Authorization
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        # Bypass authentication for specific routes
        if request.url.path in ["/api/v1/documents/health"]:
            return await call_next(request)

        # Normal authentication flow
        token = request.headers.get("Authorization")
        if not token:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            verify_jwt_token(token)  # Use the centralized function
            response = await call_next(request)
            return response
        except HTTPException as e:
            return JSONResponse({"error": e.detail}, status_code=e.status_code)

    # Middleware: Add Request ID
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Health check route
    @app.get("/health")
    @cache(expire=60)
    async def health_check(response: Response):
        """Health check endpoint that verifies critical service connectivity."""
        try:
            # Check Redis
            redis_conn = await redis.from_url(
                settings.REDIS_URL,
                encoding="utf8",
                decode_responses=True
            )
            await redis_conn.ping()
            
            # Check DB Pool
            if hasattr(app.state, "pool"):
                async with app.state.pool.acquire() as conn:
                    await conn.execute("SELECT 1")
            
            return {"status": "ok"}
        except Exception as e:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "error",
                "detail": str(e)
            }

    # Example rate-limited route
    @app.get("/your-route", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
    async def your_route():
        return {"message": "Rate-limited route accessed"}

    # Include routers
    app.include_router(claims_router)
    app.include_router(documents_router)
    app.include_router(institutions_router)

    return app