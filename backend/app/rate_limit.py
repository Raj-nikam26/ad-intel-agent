"""
rate_limit.py
-------------
Per-user limits on the two expensive actions: assistant messages (each
one is a paid language-model call) and file loads (each one parses a
workbook and builds a graph).

Limits apply per signed-in user, or per client address when sign-in is
off. Accounts listed in RATE_LIMIT_EXEMPT - by Clerk user id or email -
are never limited, so a live demonstration cannot be cut short.

Counts are kept in the API process. That is correct for a single
instance; with several instances each would count separately, and the
counters would need to move to Redis.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings

HOUR = 3600
DAY = 86400

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


def _rules(action: str) -> list[tuple[int, int, str]]:
    """(limit, window seconds, description) for an action."""
    if action == "chat":
        return [
            (settings.rate_limit_chat_per_hour, HOUR, "assistant messages per hour"),
            (settings.rate_limit_chat_per_day, DAY, "assistant messages per day"),
        ]
    if action == "upload":
        return [(settings.rate_limit_uploads_per_hour, HOUR, "file loads per hour")]
    return []


def _exempt(user: dict | None) -> bool:
    allowed = {x.strip().lower() for x in settings.rate_limit_exempt.split(",") if x.strip()}
    if not allowed or not user:
        return False
    ids = {str(user.get(k, "")).lower() for k in ("id", "clerk_id", "email")}
    return bool(ids & allowed)


def _client_key(request: Request, user: dict | None) -> str:
    if user:
        return f"user:{user['id']}"
    # Behind Render and Vercel the real address is the first forwarded one.
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def _wait_text(seconds: float) -> str:
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = math.ceil(minutes / 60)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def check(action: str, request: Request, user: dict | None) -> None:
    """Records one use of `action`, or raises 429 if a limit is reached."""
    if not settings.rate_limit_enabled or _exempt(user):
        return

    key = _client_key(request, user)
    now = time.time()
    with _lock:
        for limit, window, what in _rules(action):
            if limit <= 0:
                continue
            hits = _hits[(key, f"{action}:{window}")]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                retry = hits[0] + window - now
                raise HTTPException(
                    status_code=429,
                    detail=f"You've reached the limit of {limit} {what}. "
                           f"Please try again in {_wait_text(retry)}.",
                    headers={"Retry-After": str(int(retry) + 1)},
                )
        for _limit, window, _what in _rules(action):
            _hits[(key, f"{action}:{window}")].append(now)


def reset() -> None:
    """Clears all counters. Used by tests."""
    with _lock:
        _hits.clear()
