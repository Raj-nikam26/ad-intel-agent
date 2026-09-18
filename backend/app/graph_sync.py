"""
graph_sync.py
-------------
Keeps Neo4j in step with the data. Registered as a session-store
listener, so it runs after every new version is saved.

With REDIS_URL set, the change is pushed onto a Redis list and applied by
the separate worker process (python -m app.graph_worker), so a large sync
never holds up the request that made the edit. Without Redis it runs
inline.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from app.config import settings

logger = logging.getLogger("ad_intel.graph_sync")

QUEUE = "adintel:graph-sync"


def changed_rows(before: pd.DataFrame | None, after: pd.DataFrame) -> list[int] | None:
    """Rows whose values differ. None means "sync everything"."""
    if before is None or not before.index.equals(after.index):
        return None
    cols = [c for c in after.columns if c in before.columns]
    a = before[cols].astype(str).where(before[cols].notna(), "\0")
    b = after[cols].astype(str).where(after[cols].notna(), "\0")
    return [int(i) for i in after.index[(a != b).any(axis=1)]]


def apply(session_id: str, version: int, rows: list[int] | None, df: pd.DataFrame) -> None:
    from app import neo4j_graph

    if rows is None:
        neo4j_graph.sync_full(session_id, version, df)
    else:
        neo4j_graph.sync_rows(session_id, version, df, rows)


def on_new_version(session_id: str, version: int, before, after) -> None:
    if not settings.use_neo4j:
        return
    rows = changed_rows(before, after)
    if settings.redis_url:
        import redis

        redis.from_url(settings.redis_url).rpush(
            QUEUE, json.dumps({"session_id": session_id, "version": version, "rows": rows})
        )
        logger.info("Queued graph sync for %s v%s", session_id, version)
    else:
        apply(session_id, version, rows, after)
