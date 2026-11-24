import os
import logging
from typing import Optional
from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from app.schemas import UserProfile

logger = logging.getLogger(__name__)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "skyreserve")
DISABLE_AUTH = os.getenv("DISABLE_AUTH", "true").lower() in ("true", "1", "yes")

# Default mock user for Phase 1 local development and testing
DEFAULT_MOCK_USER = UserProfile(
    user_id="user-darren-001",
    name="Darren Chai",
    email="darren@group8.se",
    role="passenger"
)

def get_current_user(authorization: Optional[str] = Header(None)) -> UserProfile:
    """
    Decoupled Auth Dependency:
    - If Keycloak is not configured or DISABLE_AUTH=true, returns default mock passenger.
    - If Bearer token is provided, attempts decoding.
    - Gracefully falls back so development and automated tests run smoothly.
    """
    if not authorization or not authorization.startswith("Bearer "):
        if DISABLE_AUTH:
            return DEFAULT_MOCK_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ")[1]

    # In Phase 1 local dev or when Keycloak is not yet online:
    # If token matches simple dev headers or unverified payload:
    try:
        # If Keycloak public key or verification is not configured yet, decode claims
        claims = jwt.get_unverified_claims(token)
        return UserProfile(
            user_id=claims.get("sub", DEFAULT_MOCK_USER.user_id),
            name=claims.get("name", claims.get("preferred_username", DEFAULT_MOCK_USER.name)),
            email=claims.get("email", DEFAULT_MOCK_USER.email),
            role="passenger"
        )
    except JWTError:
        if DISABLE_AUTH:
            return DEFAULT_MOCK_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )
