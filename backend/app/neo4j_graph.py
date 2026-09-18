"""
neo4j_graph.py
--------------
The knowledge graph in Neo4j, built from whatever columns the uploaded
file has (see schema_profile.py).

Model - deliberately one node label and one relationship type, so any
file's columns fit without generating Cypher:

    (:Node {dataset, type, name, column})
        -[:LINKED {row, column, relation}]->
    (:Node {dataset, type, name, column})

`dataset` is the session id, so datasets never mix. `type` namespaces
values by column, keeping "Pune" the city and "Pune" the advertiser
apart. `relation` carries the readable name (RAN_AD, LOCATED_IN) for
display, while queries match on `column`.

Same construction rules as the in-process graph, so both backends answer
identically: one subject per row linked to that row's attribute values,
rows with no subject skipped, names matched exactly.

Why every relationship carries `row`: an edit changes specific rows. The
sync deletes the relationships those rows produced, recreates them from
the new data, and drops nodes left unconnected. No full rebuild after an
edit - which was the objection to a server graph for versioned data.

Name resolution uses a full-text (Lucene) index with fuzzy matching, so
"sakal" finds the exact stored name before any traversal. It needs no
embedding model and returns the same answer every time.
"""

from __future__ import annotations

import json
import logging
import re
import threading

import numpy as np
import pandas as pd

from app.config import settings
from app.schema_profile import infer_mapping, relation_name, type_name

logger = logging.getLogger("ad_intel.neo4j")

_BATCH = 2000
_driver = None
_driver_lock = threading.Lock()


def driver():
    global _driver
    with _driver_lock:
        if _driver is None:
            from neo4j import GraphDatabase

            _driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
            _driver.verify_connectivity()
            _ensure_schema(_driver)
        return _driver


def _ensure_schema(drv) -> None:
    with drv.session(database=settings.neo4j_database or None) as s:
        try:
            s.run("CREATE CONSTRAINT node_key IF NOT EXISTS "
                  "FOR (n:Node) REQUIRE (n.dataset, n.type, n.name) IS UNIQUE")
        except Exception:  # noqa: BLE001 - editions without composite constraints
            s.run("CREATE INDEX node_key IF NOT EXISTS FOR (n:Node) ON (n.dataset, n.type, n.name)")
        s.run("CREATE INDEX linked_row IF NOT EXISTS FOR ()-[r:LINKED]-() ON (r.row)")
        # Indexes from an earlier model would be kept by IF NOT EXISTS and
        # silently never match, so drop those first.
        for stale in ("entity_names", "advertiser_key", "publication_key", "category_key",
                      "subcategory_key", "location_key", "salesoffice_key", "ran_ad_row",
                      "located_in_row", "serviced_by_row", "has_category_row", "has_subcategory_row"):
            try:
                s.run(f"DROP INDEX {stale} IF EXISTS")
                s.run(f"DROP CONSTRAINT {stale} IF EXISTS")
            except Exception:  # noqa: BLE001
                pass
        s.run("CREATE FULLTEXT INDEX node_names IF NOT EXISTS FOR (n:Node) ON EACH [n.name]")
        s.run("CREATE CONSTRAINT dataset_id IF NOT EXISTS FOR (d:Dataset) REQUIRE d.id IS UNIQUE")


# ------------------------------------------------------------------ writing

def _clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v if isinstance(v, (int, float, str)) else str(v)


def _blank(v) -> bool:
    return _clean(v) is None or str(v).strip() == ""


def _row_payload(df: pd.DataFrame, mapping: dict) -> list[dict]:
    subject_col = mapping.get("subject")
    if not subject_col or subject_col not in df.columns:
        return []
    subject_type = type_name(subject_col)
    entity_cols = [c for c in mapping.get("entities", []) if c in df.columns]
    flag_cols = [c for c in mapping.get("flags", {}) if c in df.columns]
    extra_cols = [c for c in mapping.get("measures", []) + mapping.get("dates", []) if c in df.columns]

    out = []
    for idx, row in df.iterrows():
        if _blank(row[subject_col]):
            continue
        links = [{
            "type": type_name(col), "name": str(row[col]),
            "column": col, "relation": relation_name(col),
        } for col in entity_cols if not _blank(row[col])]
        out.append({
            "row": int(idx),
            "subject": str(row[subject_col]),
            "subject_type": subject_type,
            "subject_column": subject_col,
            "flags": [c for c in flag_cols if not _blank(row[c])],
            # Neo4j properties must be primitives or arrays, so the
            # measures and dates ride along as JSON text.
            "props": json.dumps({c: _clean(row[c]) for c in extra_cols}, default=str),
            "links": links,
        })
    return out


_Q_WRITE = """
UNWIND $rows AS row
MERGE (s:Node {dataset: $ds, type: row.subject_type, name: row.subject})
  ON CREATE SET s.column = row.subject_column
SET s.rows = coalesce(s.rows, 0)
WITH s, row
UNWIND row.links AS link
MERGE (t:Node {dataset: $ds, type: link.type, name: link.name})
  ON CREATE SET t.column = link.column
CREATE (s)-[:LINKED {row: row.row, column: link.column, relation: link.relation,
                     flags: row.flags, props: row.props}]->(t)
"""


def _write(tx, ds: str, rows: list[dict]) -> None:
    tx.run(_Q_WRITE, ds=ds, rows=rows)


def _delete_rows(tx, ds: str, rows: list[int]) -> None:
    tx.run("MATCH (:Node {dataset: $ds})-[r:LINKED]->() WHERE r.row IN $rows DELETE r", ds=ds, rows=rows)


def _drop_orphans(tx, ds: str) -> None:
    tx.run("MATCH (n:Node {dataset: $ds}) WHERE NOT (n)--() DELETE n", ds=ds)


def _mark(tx, ds: str, version: int) -> None:
    tx.run("MERGE (d:Dataset {id: $ds}) "
           "SET d.version = CASE WHEN d.version IS NULL OR d.version < $v THEN $v ELSE d.version END",
           ds=ds, v=version)


def sync_full(ds: str, version: int, df: pd.DataFrame, mapping: dict | None = None) -> None:
    mapping = mapping or infer_mapping(df)
    payload = _row_payload(df, mapping)
    with driver().session(database=settings.neo4j_database or None) as s:
        while s.run("MATCH (n:Node {dataset: $ds}) WITH n LIMIT 5000 DETACH DELETE n "
                    "RETURN count(*) AS c", ds=ds).single()["c"]:
            pass
        for i in range(0, len(payload), _BATCH):
            s.execute_write(_write, ds, payload[i:i + _BATCH])
        s.execute_write(_mark, ds, version)
    logger.info("Neo4j full sync: dataset %s v%s (%s rows)", ds, version, len(payload))


def sync_rows(ds: str, version: int, df: pd.DataFrame, rows: list[int], mapping: dict | None = None) -> None:
    if not rows:
        return
    mapping = mapping or infer_mapping(df)
    payload = _row_payload(df.loc[df.index.intersection(rows)], mapping)
    with driver().session(database=settings.neo4j_database or None) as s:
        for i in range(0, len(rows), _BATCH):
            s.execute_write(_delete_rows, ds, rows[i:i + _BATCH])
        for i in range(0, len(payload), _BATCH):
            s.execute_write(_write, ds, payload[i:i + _BATCH])
        s.execute_write(_drop_orphans, ds)
        s.execute_write(_mark, ds, version)
    logger.info("Neo4j row sync: dataset %s v%s (%s rows)", ds, version, len(rows))


def synced_version(ds: str) -> int | None:
    with driver().session(database=settings.neo4j_database or None) as s:
        rec = s.run("MATCH (d:Dataset {id: $ds}) RETURN d.version AS v", ds=ds).single()
        return rec["v"] if rec else None


def counts(ds: str) -> dict:
    with driver().session(database=settings.neo4j_database or None) as s:
        return {
            "nodes": s.run("MATCH (n:Node {dataset: $ds}) RETURN count(n) AS c", ds=ds).single()["c"],
            "edges": s.run("MATCH (:Node {dataset: $ds})-[r:LINKED]->() RETURN count(r) AS c", ds=ds).single()["c"],
        }


# ------------------------------------------------------------------ retrieval

def entity_summary(ds: str, value: str) -> dict | None:
    q = """
    MATCH (s:Node {dataset: $ds, name: $name})
    WHERE EXISTS { MATCH (s)-[:LINKED]->() }
    OPTIONAL MATCH (s)-[r:LINKED]->(t:Node)
    WITH s, collect(DISTINCT r.row) AS rows, collect(DISTINCT [r.column, t.name]) AS pairs,
         [f IN collect(r.flags) | f] AS flag_lists
    RETURN s.column AS subject_column, size(rows) AS row_count, pairs, flag_lists
    """
    with driver().session(database=settings.neo4j_database or None) as s:
        rec = s.run(q, ds=ds, name=value).single()
    if rec is None:
        return None

    linked: dict[str, set] = {}
    for column, name in rec["pairs"]:
        linked.setdefault(column, set()).add(name)
    flags: dict[str, int] = {}
    for lst in rec["flag_lists"]:
        for f in lst or []:
            flags[f] = flags.get(f, 0) + 1

    return {
        "subject": value,
        "subject_column": rec["subject_column"],
        "row_count": rec["row_count"],
        "flags": flags,
        "linked": {col: sorted(map(str, vals)) for col, vals in linked.items()},
    }


def find_by_attributes(ds: str, criteria: dict[str, str]) -> list[str]:
    # Each criterion is matched separately and the subjects intersected,
    # because the values may come from different rows of the same subject.
    q = """
    UNWIND $criteria AS c
    MATCH (s:Node {dataset: $ds})-[r:LINKED {column: c.column}]->(t:Node {dataset: $ds, name: c.value})
    WITH s, count(DISTINCT c.column) AS hit
    WITH s, sum(hit) AS hits
    WHERE hits >= $needed
    RETURN DISTINCT s.name AS name ORDER BY name
    """
    payload = [{"column": k, "value": v} for k, v in criteria.items()]
    with driver().session(database=settings.neo4j_database or None) as s:
        return [r["name"] for r in s.run(q, ds=ds, criteria=payload, needed=len(payload))]


_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


def resolve_entity(ds: str, text: str, entity_type: str | None = None, limit: int = 5) -> list[dict]:
    words = [w for w in _LUCENE_SPECIAL.sub(r"\\\1", text.strip()).split() if w]
    if not words:
        return []
    # Each word fuzzy-matched, all words required: "sakal media" ~ "Sakal Media Group".
    terms = " AND ".join(f"{w}~" if len(w) > 3 else w for w in words)
    q = """
    CALL db.index.fulltext.queryNodes('node_names', $terms) YIELD node, score
    WHERE node.dataset = $ds AND ($type IS NULL OR node.type = $type)
    RETURN node.name AS name, node.type AS type, node.column AS column, score
    ORDER BY score DESC LIMIT $limit
    """
    with driver().session(database=settings.neo4j_database or None) as s:
        return [
            {"name": r["name"], "type": r["type"], "column": r["column"], "score": round(r["score"], 3)}
            for r in s.run(q, terms=terms, ds=ds, type=entity_type, limit=limit)
        ]
