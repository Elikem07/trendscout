"""Authentication: Clerk issued JWT verification.

The web app attaches a Clerk session token (RS256) to API requests. We
verify signature against Clerk's JWKS, issuer, and expiry, then resolve
the local user row by the token's sub (Clerk user id).

Provisioning is webhook first (see routers/webhooks.py). If a valid token
arrives for an unprovisioned user and the token carries an email claim
(custom JWT template), we provision just in time; otherwise 403 with a
clear message, which almost always means the Clerk webhook is not
configured.
"""

from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(get_settings().clerk_jwks_url, cache_keys=True)


def _get_signing_key(token: str) -> Any:
    """Resolve the public key for a token via JWKS. Patched in tests."""
    return _jwks_client().get_signing_key_from_jwt(token).key


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            _get_signing_key(token),
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"require": ["exp", "iat", "sub"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    allowed = settings.clerk_authorized_party_list
    if allowed and claims.get("azp") not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: azp not authorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_token(auth_header.removeprefix("Bearer "))
    clerk_id = str(claims["sub"])

    user = db.scalar(select(User).where(User.clerk_id == clerk_id))
    if user is not None:
        return user

    email = claims.get("email")
    if email:  # JIT provisioning when a custom JWT template includes email
        user = User(clerk_id=clerk_id, email=str(email))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Authenticated but not provisioned. Configure the Clerk webhook "
            "(user.created) to point at /webhooks/clerk."
        ),
    )


CurrentUser = Annotated[User, Depends(get_current_user)]
