"""
graph_cache.py
--------------
Memoizes the built graph per (session, version).

Why this exists now and didn't before: when the graph was only reachable
through an agent tool call, rebuilding it per call was acceptable - one
rebuild per conversational turn, hidden behind an LLM round-trip that
already takes seconds. The IDE changes that. The graph panel, the node
inspector and the neighborhood view all hit the graph directly, several
times per interaction, with no LLM latency to hide behind. Rebuilding
5,773 nodes / 55,651 edges from 11,275 rows on every panel click would
make the UI feel broken.

Keyed on version, not just session, because an edit creates a new
version of the dataframe - and an edit to AdvertiserName, Category or
SalesOffice genuinely changes the graph. Caching on session alone would
serve a stale graph immediately after a fix, which is exactly the moment
the user is looking at the graph to confirm the fix worked.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

import networkx as nx
import pandas as pd

from app.graph_builder import build_graph

logger = logging.getLogger("ad_intel.graph_cache")

# Small LRU. Each entry is a full graph over the dataset, so this is not
# free memory-wise; a handful of recent versions is the useful window
# (you compare against what you just changed, not against v0 from an hour ago).
MAX_ENTRIES = 6

_cache: "OrderedDict[tuple[str, int], nx.MultiDiGraph]" = OrderedDict()


def get_graph(session_id: str, version: int, df: pd.DataFrame) -> nx.MultiDiGraph:
    key = (session_id, version)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    logger.info("Graph cache miss for session=%s version=%s - building", session_id, version)
    g = build_graph(df)
    _cache[key] = g
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        evicted, _ = _cache.popitem(last=False)
        logger.info("Graph cache evicted %s", evicted)
    return g


def invalidate_session(session_id: str) -> None:
    """Drops every cached graph for a session - used on revert, which can
    truncate versions and make previously-cached version numbers refer to
    different data than they did before."""
    for key in [k for k in _cache if k[0] == session_id]:
        del _cache[key]
