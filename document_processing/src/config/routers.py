# src/config/routers.py

from src.api.routes import claims, documents, institutions

# Export the routers
claims_router = claims.router
documents_router = documents.router
institutions_router = institutions.router