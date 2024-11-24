from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_limiter.depends import RateLimiter
from fastapi_limiter import FastAPILimiter
import redis.asyncio as redis
import uuid
from contextlib import asynccontextmanager
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from src.config.settings import settings
from src.config.routers import claims_router, documents_router, institutions_router
from src.auth.auth_utils import verify_jwt_token
from src.document.document_processor import DocumentProcessor

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_conn = await redis.from_url(
        settings.REDIS_URL,
        encoding="utf8",
        decode_responses=True
    )
    await FastAPILimiter.init(redis_conn)
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    yield
    await FastAPICache.clear()

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

    # Initialize and attach document processor to app state
    async def init_document_processor():
        # Replace 'dsn' and 'config' with actual parameters or settings
        dsn = settings.database_dsn
        config = ProcessorConfig()
        app.state.document_processor = await DocumentProcessor.create(dsn=dsn, config=config)

    @app.on_event("startup")
    async def on_startup():
        await init_document_processor()

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
    async def health_check():
        try:
            async with redis.client() as conn:
                await conn.ping()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    # Example rate-limited route
    @app.get("/your-route", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
    async def your_route():
        return {"message": "Rate-limited route accessed"}

    # Include routers
    app.include_router(claims_router)
    app.include_router(documents_router)
    app.include_router(institutions_router)

    return app