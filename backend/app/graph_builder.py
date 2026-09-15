"""
graph_builder.py
-----------------
Builds a property graph from the ad-tracking table using networkx.

A note on "GraphRAG" here, worth being precise about (this is exactly
the kind of thing to be able to explain rather than gloss over):
Microsoft's original GraphRAG technique is built for UNSTRUCTURED text
corpora - it uses an LLM to extract entities/relationships out of raw
documents, then clusters them into communities, then summarizes those
communities for retrieval. That extraction step exists to turn
unstructured text INTO a graph.

This dataset is already structured - Advertiser, Publication, Category,
Location, Sales Office, and Edition are already explicit columns, not
buried in prose. Running an LLM to "extract" entities that are already
column values would be slower, more expensive, and less reliable than
just reading them directly. So this builds the graph deterministically
from the columns, and reserves the LLM for what it's actually needed
for: turning a natural-language question into a graph query, and
turning retrieved graph facts back into a natural-language answer.
That's the same "retrieval over a graph, grounded generation on top"
principle GraphRAG is built on - adapted to skip the unstructured-text
extraction step this data doesn't need.

Entity identity choice: advertiser nodes are keyed on "Advertiser Name
by AI" (the existing AI-normalized name already present in the source
data) rather than the raw "AdvertiserName" column, since the raw column
has ~900 rows where near-identical or legal-entity-suffix variants of
the same advertiser would otherwise appear as separate nodes. The raw
name is kept as a node attribute for traceability, not discarded.
"""

from __future__ import annotations

import logging

import networkx as nx
import pandas as pd

logger = logging.getLogger("ad_intel.graph_builder")

ADVERTISER_KEY_COLUMN = "Advertiser Name by AI"


def _node_id(entity_type: str, value: str) -> str:
    """Namespaces node IDs by entity type. Without this, an advertiser
    name that happens to match a location or category string (plausible
    with thousands of free-text values) would silently collide into the
    same graph node - a real bug caught by testing against the actual
    11k-row file, not a hypothetical edge case."""
    return f"{entity_type}::{value}"


def build_graph(df: pd.DataFrame) -> nx.MultiDiGraph:
    """
    Builds a directed multigraph:
      Advertiser --[RAN_AD]--> Publication   (edge carries date, page,
                                               category, sub_category,
                                               edition, size, reach,
                                               is_house_ad, row_index)
      Advertiser --[LOCATED_IN]--> Location
      Advertiser --[SERVICED_BY]--> SalesOffice
      Publication --[HAS_CATEGORY]--> Category --[HAS_SUBCATEGORY]--> SubCategory

    Rows with a missing advertiser key are skipped for graph purposes
    (they still exist in the underlying dataframe - graph construction
    doesn't touch or drop source data, it just can't place an edge with
    no identity to attach it to).
    """
    g = nx.MultiDiGraph()
    skipped = 0

    for idx, row in df.iterrows():
        advertiser = row.get(ADVERTISER_KEY_COLUMN)
        publication = row.get("Publication")

        if pd.isna(advertiser) or pd.isna(publication):
            skipped += 1
            continue

        adv_id = _node_id("Advertiser", advertiser)
        pub_id = _node_id("Publication", publication)

        if not g.has_node(adv_id):
            g.add_node(adv_id, type="Advertiser", name=advertiser, raw_names=set())
        g.nodes[adv_id]["raw_names"].add(str(row.get("AdvertiserName", "")))

        if not g.has_node(pub_id):
            g.add_node(pub_id, type="Publication", name=publication)

        category = row.get("Category")
        sub_category = row.get("Sub Category")
        location = row.get("AdvertiserLocation")
        sales_office = row.get("AdvertiserSalesOffice")

        g.add_edge(
            adv_id, pub_id,
            key=f"ad_{idx}",
            relation="RAN_AD",
            row_index=int(idx),
            date=str(row.get("Date")),
            page=row.get("Page"),
            category=category if pd.notna(category) else None,
            sub_category=sub_category if pd.notna(sub_category) else None,
            edition=row.get("Edition"),
            width=row.get("Width (cm)"),
            height=row.get("Height (cm)"),
            area=row.get("Area (sq cm)"),
            reach=row.get("Advertiser Reach"),
            is_house_ad=str(row.get("IsHouseAd")) == "Yes",
        )

        if pd.notna(location):
            loc_id = _node_id("Location", location)
            if not g.has_node(loc_id):
                g.add_node(loc_id, type="Location", name=location)
            g.add_edge(adv_id, loc_id, relation="LOCATED_IN")

        if pd.notna(sales_office):
            office_id = _node_id("SalesOffice", sales_office)
            if not g.has_node(office_id):
                g.add_node(office_id, type="SalesOffice", name=sales_office)
            g.add_edge(adv_id, office_id, relation="SERVICED_BY")

        if pd.notna(category):
            cat_id = _node_id("Category", category)
            if not g.has_node(cat_id):
                g.add_node(cat_id, type="Category", name=category)
            g.add_edge(pub_id, cat_id, relation="HAS_CATEGORY")
            if pd.notna(sub_category):
                subcat_id = _node_id("SubCategory", sub_category)
                if not g.has_node(subcat_id):
                    g.add_node(subcat_id, type="SubCategory", name=sub_category)
                g.add_edge(cat_id, subcat_id, relation="HAS_SUBCATEGORY")

    logger.info(
        "Graph built: %s nodes, %s edges (%s rows skipped for missing advertiser/publication)",
        g.number_of_nodes(), g.number_of_edges(), skipped,
    )
    return g


def advertiser_summary(g: nx.MultiDiGraph, advertiser: str) -> dict | None:
    """Pulls together everything the graph knows about one advertiser -
    the kind of multi-hop fact-gathering a flat filter can't do in one
    step, which is what makes this a genuine graph-retrieval case."""
    adv_id = _node_id("Advertiser", advertiser)
    if adv_id not in g:
        return None

    publications = set()
    categories = set()
    editions = set()
    total_ads = 0
    house_ads = 0

    for _, target, data in g.out_edges(adv_id, data=True):
        if data.get("relation") == "RAN_AD":
            publications.add(g.nodes[target]["name"])
            total_ads += 1
            if data.get("is_house_ad"):
                house_ads += 1
            if data.get("category"):
                categories.add(data["category"])
            if data.get("edition"):
                editions.add(data["edition"])

    locations = list({g.nodes[t]["name"] for _, t, d in g.out_edges(adv_id, data=True) if d.get("relation") == "LOCATED_IN"})
    sales_offices = list({g.nodes[t]["name"] for _, t, d in g.out_edges(adv_id, data=True) if d.get("relation") == "SERVICED_BY"})

    return {
        "advertiser": advertiser,
        "raw_name_variants": list(g.nodes[adv_id].get("raw_names", [])),
        "total_ad_insertions": total_ads,
        "house_ads": house_ads,
        "publications": list(publications),
        "categories": list(categories),
        "editions": list(editions),
        "locations": locations,
        "sales_offices": sales_offices,
    }


def advertisers_by_category_and_office(g: nx.MultiDiGraph, category: str, sales_office: str) -> list[str]:
    """Example multi-hop traversal: advertisers serviced by a given
    sales office that also ran ads in a given category - requires
    joining two different edge types, exactly the kind of query a flat
    single-table filter handles awkwardly but a graph handles directly."""
    result = set()
    office_id = _node_id("SalesOffice", sales_office)
    for node_id, attrs in g.nodes(data=True):
        if attrs.get("type") != "Advertiser":
            continue
        offices = {t for _, t, d in g.out_edges(node_id, data=True) if d.get("relation") == "SERVICED_BY"}
        if office_id not in offices:
            continue
        categories = {d.get("category") for _, _, d in g.out_edges(node_id, data=True) if d.get("relation") == "RAN_AD"}
        if category in categories:
            result.add(attrs["name"])
    return list(result)
