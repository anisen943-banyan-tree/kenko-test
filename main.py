from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_limiter.depends import RateLimiter
import redis.asyncio as redis
import uuid
from src.config.settings import settings
from src.api.routes import claims, documents, institutions
from src.api.routes.documents import router as documents_router
from src.app_factory import create_app
from src.document.document_processor import DocumentProcessor, ProcessorConfig

app = create_app()

@app.on_event("startup")
async def startup_event():
    try:
        app.state.pool = await asyncpg.create_pool(dsn=settings.database_url)
        app.state.document_processor = DocumentProcessor(
            config=ProcessorConfig(redis_url=settings.REDIS_URL)
        )
    except Exception as e:
        raise RuntimeError(f"Failed to initialize app: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.pool.close()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = request.headers.get("Authorization")
    if not token:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        verify_jwt_token(token)
    except HTTPException as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    response = await call_next(request)
    return response

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

@app.get("/health")
async def health_check():
    try:
        async with app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/your-route", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def your_route():
    # Your code here

# Include your routers
app.include_router(claims.router)
app.include_router(documents_router, prefix="/api/v1/documents")
app.include_router(institutions.router)