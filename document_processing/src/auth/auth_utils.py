import jwt
from fastapi import HTTPException, status
from src.config.settings import settings

def verify_jwt_token(token: str) -> dict:
    """Decode and validate JWT token."""
    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith("Bearer "):
            token = token[len("Bearer "):]

        # Decode token using secret key and algorithm
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        
        # Optionally verify additional claims (e.g., expiration)
        if "role" not in payload:
            raise jwt.InvalidTokenError("Missing role in token.")
        
        return payload  # Return payload for downstream use
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token."
        )

def generate_test_token(role: str) -> str:
    """Generate a JWT token for testing purposes with a specified role."""
    payload = {
        "role": role,
        # Add other claims as necessary
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    return token

def validate_token(token: str) -> dict:
    """Validate the JWT token and return the payload."""
    return verify_jwt_token(token)

def setup_auth_middleware(app):
    """Setup authentication middleware for FastAPI app."""
    from fastapi.middleware import Middleware
    from fastapi.middleware.authentication import AuthenticationMiddleware

    def auth_middleware(request, call_next):
        token = request.headers.get("Authorization")
        if token:
            try:
                request.state.user = validate_token(token)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        return call_next(request)

    app.add_middleware(Middleware(AuthenticationMiddleware, backend=auth_middleware))