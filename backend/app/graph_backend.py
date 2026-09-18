"""
graph_backend.py
----------------
One entry point for graph retrieval, whichever graph is configured:
Neo4j when NEO4J_URI is set, otherwise the cached in-process NetworkX
graph. The agent only talks to this module.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.config import settings
from app.graph_builder import entity_summary as nx_summary
from app.graph_builder import find_by_attributes as nx_find
from app.graph_cache import get_graph


def _nx(session):
    return get_graph(session.session_id, len(session.versions) - 1, session.current_df)


def entity_summary(session, value: str) -> dict | None:
    if settings.use_neo4j:
        from app import neo4j_graph
        return neo4j_graph.entity_summary(session.session_id, value)
    return nx_summary(_nx(session), value)


def find_by_attributes(session, criteria: dict[str, str]) -> list[str]:
    if not criteria:
        return []
    if settings.use_neo4j:
        from app import neo4j_graph
        return neo4j_graph.find_by_attributes(session.session_id, criteria)
    return nx_find(_nx(session), criteria)


def resolve_entity(session, text: str, entity_type: str | None = None, limit: int = 5) -> list[dict]:
    if settings.use_neo4j:
        from app import neo4j_graph
        return neo4j_graph.resolve_entity(session.session_id, text, entity_type, limit)

    needle = text.strip().lower()
    scored = []
    for _, attrs in _nx(session).nodes(data=True):
        kind = attrs.get("type")
        if entity_type and kind != entity_type:
            continue
        name = str(attrs.get("name", ""))
        low = name.lower()
        score = 1.0 if needle == low else (0.9 if needle in low else SequenceMatcher(None, needle, low).ratio())
        if score >= 0.6:
            scored.append({"name": name, "type": kind, "column": attrs.get("column"), "score": round(score, 3)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]
