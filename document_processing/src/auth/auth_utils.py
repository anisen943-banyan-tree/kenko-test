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