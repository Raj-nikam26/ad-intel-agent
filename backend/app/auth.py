"""
auth.py
-------
Sign-in with Clerk.

Clerk runs the sign-in UI and issues a short-lived session token (a JWT
signed with Clerk's RS256 key). The browser sends it on every request as
`Authorization: Bearer <token>`. This module verifies it against Clerk's
published signing keys (JWKS) - signature, expiry, issuer, and `azp`,
the origin the token was issued to - and never calls Clerk per request:
the keys are fetched once and cached.

Only the publishable key is required. It encodes the Clerk frontend API
domain, from which the JWKS URL and the expected issuer are derived, so
there is no second value to keep in sync.

AUTH_ENABLED=false (the default) leaves every route open and
`current_user` returns None. That is how the public demo runs, so a
recruiter opening the link meets no login wall. The ownership checks are
the same code either way.
"""

from __future__ import annotations

import base64
import logging
import threading
import time

import jwt
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.data_store import session_store

logger = logging.getLogger("ad_intel.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_jwks_client = None
_lock = threading.Lock()
# Clerk user id -> (our user record, cached at). Avoids a database write on
# every request while still refreshing name and email now and then.
_users: dict[str, tuple[dict, float]] = {}
_USER_TTL = 300


def clerk_domain() -> str:
    """The Clerk frontend API host, decoded from the publishable key
    (pk_test_<base64 of "host$">)."""
    key = settings.clerk_publishable_key
    if not key or "_" not in key:
        return ""
    encoded = key.split("_", 2)[-1]
    try:
        return base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    except Exception:  # noqa: BLE001
        return ""


def _issuer() -> str:
    return settings.clerk_issuer or (f"https://{clerk_domain()}" if clerk_domain() else "")


def _jwks():
    global _jwks_client
    with _lock:
        if _jwks_client is None:
            url = settings.clerk_jwks_url or (f"{_issuer()}/.well-known/jwks.json" if _issuer() else "")
            if not url:
                raise HTTPException(status_code=503, detail="Sign-in is not configured on this server.")
            _jwks_client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
        return _jwks_client


def verify_token(token: str) -> dict:
    """Returns the token's claims, or raises jwt.PyJWTError."""
    signing_key = _jwks().get_signing_key_from_jwt(token).key
    issuer = _issuer()
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        issuer=issuer or None,
        options={"require": ["exp", "iat", "sub"], "verify_iss": bool(issuer)},
        leeway=5,
    )
    # azp is the origin the token was issued for. Checking it stops a token
    # minted for some other site on the same Clerk instance being replayed here.
    parties = settings.clerk_authorized_parties or settings.cors_allow_origins
    if claims.get("azp") and parties and claims["azp"] not in parties:
        raise jwt.InvalidTokenError(f"Token issued for {claims['azp']}, not this app.")
    return claims


def _user_from_claims(claims: dict) -> dict:
    clerk_id = claims["sub"]
    cached = _users.get(clerk_id)
    if cached and time.time() - cached[1] < _USER_TTL:
        return cached[0]
    email = claims.get("email") or ""
    user = session_store.upsert_user(
        provider_id=f"clerk:{clerk_id}",
        email=email,
        name=claims.get("name") or email or clerk_id,
        picture=claims.get("picture") or "",
    )
    user["clerk_id"] = clerk_id  # matched against RATE_LIMIT_EXEMPT
    _users[clerk_id] = (user, time.time())
    return user


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def current_user(request: Request) -> dict | None:
    """The signed-in user, or None when auth is switched off."""
    if not settings.auth_enabled:
        return None
    token = _bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        return _user_from_claims(verify_token(token))
    except jwt.PyJWTError as e:
        logger.info("Rejected token: %s", e)
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from e


def optional_user(request: Request) -> dict | None:
    """Never rejects. For routes that work signed out, such as /health."""
    if not settings.auth_enabled or not _bearer(request):
        return None
    try:
        return current_user(request)
    except HTTPException:
        return None


def owns(session, user: dict | None) -> bool:
    """Whether this user may see this session. Sessions created while
    sign-in was off have no owner and stay readable."""
    if not settings.auth_enabled:
        return True
    owner = getattr(session, "owner_id", None)
    return owner is None or (user is not None and owner == user["id"])


@router.get("/me")
def me(request: Request):
    return {"auth_enabled": settings.auth_enabled, "user": optional_user(request)}
