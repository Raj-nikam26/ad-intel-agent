"""
graph_worker.py
---------------
Applies queued graph changes to Neo4j.

    cd backend
    python -m app.graph_worker

Reads the dataframe for the queued version from the session store
(PostgreSQL + object storage), so it can run on a different machine
from the API.
"""

from __future__ import annotations

import json
import logging
import time

import redis

from app.config import settings
from app.data_store import session_store
from app.graph_sync import QUEUE, apply

logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("ad_intel.graph_worker")


def main() -> None:
    if not (settings.use_neo4j and settings.redis_url):
        raise SystemExit("Set NEO4J_URI and REDIS_URL in backend/.env to run the graph worker.")
    # socket_timeout must exceed the blpop wait, or the client aborts the
    # (perfectly normal) idle wait as a read error.
    r = redis.from_url(settings.redis_url, socket_timeout=30)
    logger.info("Graph worker listening on %s", QUEUE)
    while True:
        # A short block rather than an indefinite one: the client applies its
        # own socket timeout, which would otherwise abort the wait as an error.
        try:
            item = r.blpop(QUEUE, timeout=5)
        except redis.exceptions.TimeoutError:
            continue  # nothing queued; keep waiting
        except redis.exceptions.ConnectionError as e:
            # Redis restarting (or Docker with it) should pause the worker,
            # not kill it. Jobs stay queued in Redis until it is back.
            logger.warning("Redis unavailable (%s); retrying in 5s", e)
            time.sleep(5)
            continue
        if item is None:
            continue
        _, raw = item
        job = json.loads(raw)
        try:
            session = session_store.get(job["session_id"])
            if session is None or job["version"] >= len(session.versions):
                # Created by another API process this worker has not cached yet.
                session_store._cache.pop(job["session_id"], None)
                session = session_store.get(job["session_id"])
            if session is None:
                logger.error("Session %s not found; dropping job", job["session_id"])
                continue
            apply(job["session_id"], job["version"], job["rows"], session.versions[job["version"]])
        except Exception:  # noqa: BLE001 - keep the worker alive; retry by re-queueing
            logger.exception("Graph sync failed for %s; retrying in 5s", job)
            time.sleep(5)
            r.rpush(QUEUE, raw)


if __name__ == "__main__":
    main()
