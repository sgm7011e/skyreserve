import os
import time
import logging
from typing import Optional, Dict, Any
import httpx
from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from app.schemas import UserProfile

logger = logging.getLogger(__name__)

# Public URL matches the token's `iss` claim; internal URL reaches Keycloak inside Docker/K3s.
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8180").rstrip("/")
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", KEYCLOAK_URL).rstrip("/")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "skyreserve")
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "skyreserve-api")
DISABLE_AUTH = os.getenv("DISABLE_AUTH", "true").lower() in ("true", "1", "yes")
INSECURE = os.getenv("INSECURE", "true").lower() in ("true", "1", "yes")

KEYCLOAK_ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_CERTS_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

# Cache JWKS public keys for 5 minutes; refresh once on unknown kid (matching Tutorial 12).
_public_keys_cache: Optional[Dict[str, Any]] = None
_public_keys_fetched_at: float = 0.0

DEFAULT_MOCK_USER = UserProfile(
    user_id="user-darren-001",
    name="Darren Chai",
    email="darren@group8.se",
    role="passenger",
)


def _get_public_keys(force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch Keycloak realm JWKS public keys for RS256 verification."""
    global _public_keys_cache, _public_keys_fetched_at

    if force_refresh or _public_keys_cache is None or (time.monotonic() - _public_keys_fetched_at > 300):
        try:
            response = httpx.get(KEYCLOAK_CERTS_URL, timeout=10, verify=not INSECURE)
            response.raise_for_status()
            _public_keys_cache = response.json()
            _public_keys_fetched_at = time.monotonic()
            logger.info("Fetched JWKS public keys from %s", KEYCLOAK_CERTS_URL)
        except Exception as exc:
            logger.error("Failed to fetch Keycloak public keys from %s: %s", KEYCLOAK_CERTS_URL, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable",
            )

    return _public_keys_cache


def _verify_token(token: str) -> Dict[str, Any]:
    """Verify RS256 signature, expiration, issuer, and audience against Keycloak JWKS."""
    keys = _get_public_keys()
    unverified_header = jwt.get_unverified_header(token)
    key_id = unverified_header.get("kid")
    if not key_id:
        raise JWTError("Token missing key ID (kid)")

    key = next((k for k in keys.get("keys", []) if k.get("kid") == key_id), None)
    if key is None:
        keys = _get_public_keys(force_refresh=True)
        key = next((k for k in keys.get("keys", []) if k.get("kid") == key_id), None)
    if key is None:
        raise JWTError("Unknown signing key")

    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=KEYCLOAK_AUDIENCE,
        issuer=KEYCLOAK_ISSUER,
        options={
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iss": True,
            "verify_aud": True,
            "require_exp": True,
        },
    )

    for required_claim in ("sub", "iss", "aud", "exp"):
        if not claims.get(required_claim):
            raise JWTError(f"Token missing required claim: {required_claim}")

    return claims


def _profile_from_claims(claims: Dict[str, Any]) -> UserProfile:
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    role = "admin" if "admin" in realm_roles else "passenger"
    display_name = (
        claims.get("name")
        or claims.get("preferred_username")
        or DEFAULT_MOCK_USER.name
    )
    return UserProfile(
        user_id=claims.get("sub", DEFAULT_MOCK_USER.user_id),
        name=display_name,
        email=claims.get("email", DEFAULT_MOCK_USER.email),
        role=role,
    )


def get_current_user(authorization: Optional[str] = Header(None)) -> UserProfile:
    """
    FastAPI Auth Dependency:
    - When DISABLE_AUTH=false (Keycloak enabled): verifies RS256 Bearer JWT via JWKS.
    - When DISABLE_AUTH=true (offline/unit-test mode): falls back to DEFAULT_MOCK_USER.
    """
    if not authorization or not authorization.startswith("Bearer "):
        if DISABLE_AUTH:
            return DEFAULT_MOCK_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()

    if DISABLE_AUTH:
        try:
            claims = jwt.get_unverified_claims(token)
            return _profile_from_claims(claims)
        except JWTError:
            return DEFAULT_MOCK_USER

    try:
        claims = _verify_token(token)
        return _profile_from_claims(claims)
    except HTTPException:
        raise
    except JWTError as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
