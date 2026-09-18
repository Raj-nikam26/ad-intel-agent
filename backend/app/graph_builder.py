"""
graph_builder.py
----------------
Builds the knowledge graph from whatever columns the uploaded file has.

Shape: one subject per row linked to that row's attribute values.

    (Subject)-[:RELATION {row, column}]->(Attribute)

For the ad dataset that comes out as Advertiser -[RAN_AD]-> Publication,
-[LOCATED_IN]-> Location and so on, because the column roles are inferred
(see schema_profile.py) rather than hardcoded. For a support-ticket or
sales file it produces the equivalent links for those columns, with no
code change.

Node ids are namespaced by entity type - "Advertiser::Pune" and
"Location::Pune" must stay separate nodes. Without that, a name that
also appears as a city silently merges the two and every traversal
through either returns the union. That was a real bug found on the
sample file, and it is general: any file with repeated values across
columns hits it.

Rows missing the subject value are skipped: an edge needs something to
attach to. They stay in the dataframe and in the grid.
"""

from __future__ import annotations

import logging

import networkx as nx
import pandas as pd

from app.schema_profile import infer_mapping, relation_name, type_name

logger = logging.getLogger("ad_intel.graph")


def _blank(value) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def _node_id(entity_type: str, value) -> str:
    """Namespaces node IDs by entity type, so identical values in
    different columns never collapse into one node."""
    return f"{entity_type}::{value}"


def build_graph(df: pd.DataFrame, mapping: dict | None = None) -> nx.MultiDiGraph:
    mapping = mapping or infer_mapping(df)
    subject_col = mapping.get("subject")
    g = nx.MultiDiGraph()
    g.graph["mapping"] = mapping
    if not subject_col or subject_col not in df.columns:
        logger.warning("No subject column identified; graph is empty")
        return g

    subject_type = type_name(subject_col)
    entity_cols = [c for c in mapping.get("entities", []) if c in df.columns]
    flag_cols = [c for c in mapping.get("flags", {}) if c in df.columns]
    measure_cols = [c for c in mapping.get("measures", []) if c in df.columns]
    date_cols = [c for c in mapping.get("dates", []) if c in df.columns]
    skipped = 0

    for idx, row in df.iterrows():
        subject_value = row[subject_col]
        if _blank(subject_value):
            skipped += 1
            continue

        sid = _node_id(subject_type, subject_value)
        if not g.has_node(sid):
            g.add_node(sid, type=subject_type, name=subject_value, column=subject_col)
        node = g.nodes[sid]
        # setdefault, not assignment: this value may already exist as a node
        # because it appeared in an attribute column first.
        node.setdefault("rows", set())
        node.setdefault("flags", {})
        node["rows"].add(int(idx))
        for flag in flag_cols:
            if not _blank(row[flag]):
                node["flags"][flag] = node["flags"].get(flag, 0) + 1

        for col in entity_cols:
            value = row[col]
            if _blank(value):
                continue
            etype = type_name(col)
            tid = _node_id(etype, value)
            if not g.has_node(tid):
                g.add_node(tid, type=etype, name=value, column=col)
            g.add_edge(sid, tid, key=f"{col}_{idx}", relation=relation_name(col),
                       column=col, row_index=int(idx),
                       **{c: row[c] for c in measure_cols + date_cols})

    logger.info("Graph built: %s nodes, %s edges (%s rows skipped, no %s)",
                g.number_of_nodes(), g.number_of_edges(), skipped, subject_col)
    return g


# ------------------------------------------------------------------ retrieval

def entity_summary(g: nx.MultiDiGraph, value: str) -> dict | None:
    """Everything the graph knows about one subject: how many rows it
    covers, and its distinct values in each linked column."""
    mapping = g.graph.get("mapping", {})
    subject_col = mapping.get("subject")
    sid = _node_id(type_name(subject_col), value) if subject_col else None
    if not sid or sid not in g:
        return None

    node = g.nodes[sid]
    linked: dict[str, list] = {}
    for _, target, data in g.out_edges(sid, data=True):
        linked.setdefault(data["column"], set()).add(g.nodes[target]["name"])

    return {
        "subject": value,
        "subject_column": subject_col,
        "row_count": len(node.get("rows", ())),
        "flags": dict(node.get("flags", {})),
        "linked": {col: sorted(map(str, vals)) for col, vals in linked.items()},
    }


def find_by_attributes(g: nx.MultiDiGraph, criteria: dict[str, str]) -> list[str]:
    """Subjects linked to every given column/value pair.

    The values may come from different rows of the same subject - an
    advertiser handled by one office that also ran a category of ad
    somewhere else still counts. That is the multi-hop join a flat filter
    on a single row cannot express.
    """
    matched: list[set[str]] = []
    for column, value in criteria.items():
        tid = _node_id(type_name(column), value)
        if tid not in g:
            return []
        matched.append({src for src, _, _ in g.in_edges(tid, data=True)})
    if not matched:
        return []
    return sorted(g.nodes[n]["name"] for n in set.intersection(*matched))


# --------------------------------------------- ad-dataset convenience wrappers

def advertiser_summary(g: nx.MultiDiGraph, advertiser: str) -> dict | None:
    """The ad-dataset view of entity_summary, kept because the sample file
    and its tests speak in these terms."""
    base = entity_summary(g, advertiser)
    if base is None:
        return None
    linked = base["linked"]
    return {
        "advertiser": advertiser,
        "raw_name_variants": linked.get("AdvertiserName", []),
        "total_ad_insertions": base["row_count"],
        "house_ads": base["flags"].get("IsHouseAd", 0),
        "publications": linked.get("Publication", []),
        "categories": linked.get("Category", []),
        "editions": linked.get("Edition", []),
        "locations": linked.get("AdvertiserLocation", []),
        "sales_offices": linked.get("AdvertiserSalesOffice", []),
    }


def advertisers_by_category_and_office(g: nx.MultiDiGraph, category: str, sales_office: str) -> list[str]:
    return find_by_attributes(g, {"Category": category, "AdvertiserSalesOffice": sales_office})
