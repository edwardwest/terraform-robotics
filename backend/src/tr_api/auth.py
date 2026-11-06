"""Clerk authentication: verify the session token on each request and map it to a local user row.

The web app's server-side proxy forwards `Authorization: Bearer <Clerk session token>`. Tokens are RS256 JWTs.
Verification is networkless when CLERK_JWT_KEY (the PEM "JWT public key" from the Clerk dashboard) is set;
otherwise keys come from CLERK_JWKS_URL (https://<frontend-api>/.well-known/jwks.json).

Users are created on first sight from the token's `sub`; `email` and `name` come from custom session-token
claims ({"email": "{{user.primary_email_address}}", "name": "{{user.full_name}}"}) when configured.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException

from .config import get_settings
from .db import fetch_one

DEV_USER_SUB = "dev_local_user"


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str) -> dict:
    """Return the token's claims, or raise HTTPException(401)."""
    s = get_settings()
    try:
        if s.clerk_jwt_key:
            key = s.clerk_jwt_key.replace("\\n", "\n")
        elif s.clerk_jwks_url:
            key = _jwks_client(s.clerk_jwks_url).get_signing_key_from_jwt(token).key
        else:
            raise HTTPException(500, "Authentication is not configured: set CLERK_JWT_KEY or CLERK_JWKS_URL")
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            leeway=5,
            options={"require": ["sub", "exp", "iat"], "verify_aud": False},
        )
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid session token: {exc}") from exc

    parties = [p.strip() for p in s.clerk_authorized_parties.split(",") if p.strip()]
    if parties and claims.get("azp") and claims["azp"] not in parties:
        raise HTTPException(401, "Session token was issued for a different site")
    return claims


def _upsert_user(sub: str, email: str | None, name: str | None) -> dict:
    return fetch_one(
        """INSERT INTO users (clerk_user_id, email, name)
           VALUES (:sub, :email, :name)
           ON CONFLICT (clerk_user_id) DO UPDATE
           SET email = COALESCE(EXCLUDED.email, users.email),
               name = COALESCE(EXCLUDED.name, users.name),
               last_seen_at = now()
           RETURNING id, clerk_user_id, email, name, created_at""",
        sub=sub,
        email=email,
        name=name,
    )


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    s = get_settings()
    if s.auth_disabled:  # local development only; never set in production
        return _upsert_user(DEV_USER_SUB, "dev@localhost", "Local developer")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    claims = verify_token(authorization.split(" ", 1)[1].strip())
    email = claims.get("email") or None
    name = (claims.get("name") or "").strip() or None
    return _upsert_user(claims["sub"], email, name)


CurrentUser = Annotated[dict, Depends(current_user)]
