"""
End-to-end check of the production services against the real sample file.

Needs `docker compose up -d` running. Not part of the unit suite.

    cd backend
    python tests/integration_neo4j.py

Checks:
  1. a session is stored in PostgreSQL and reloads from it
  2. Neo4j holds the same node and edge counts as the in-process graph
  3. both graph backends give identical answers to the retrieval queries
  4. an edit updates only the touched rows in Neo4j, and the answer changes
  5. fuzzy name resolution finds the exact stored name
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://adintel:adintel@localhost:5432/adintel")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_PASSWORD", "adintel-graph")
os.environ["REDIS_URL"] = ""  # sync inline so the check is deterministic
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import graph_backend, neo4j_graph  # noqa: E402
from app.config import settings  # noqa: E402
from app.data_store import SessionStore  # noqa: E402
from app.graph_builder import build_graph, entity_summary, find_by_attributes  # noqa: E402
from app.graph_sync import on_new_version  # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(("PASS  " if cond else "FAIL  ") + msg)
    ok &= bool(cond)


def same_summary(a, b):
    if a is None or b is None:
        return False
    if a["row_count"] != b["row_count"] or a["flags"] != b["flags"]:
        return False
    return {k: set(v) for k, v in a["linked"].items()} == {k: set(v) for k, v in b["linked"].items()}


df = pd.read_excel(settings.resolved_sample_file)
store = SessionStore()  # PostgreSQL, per DATABASE_URL
store.add_listener(on_new_version)
check(bool(store._postgres_url), "session store is using PostgreSQL")

s = store.create(df, filename="Sample.xlsx")
ds = s.session_id

store._cache.clear()
reloaded = store.get(ds)
check(reloaded is not None and len(reloaded.current_df) == len(df), "session reloads from PostgreSQL + snapshots")

g = build_graph(df)
c = neo4j_graph.counts(ds)
check(c["nodes"] == g.number_of_nodes(), f"node count matches ({c['nodes']} vs {g.number_of_nodes()})")
check(c["edges"] == g.number_of_edges(), f"edge count matches ({c['edges']} vs {g.number_of_edges()})")

adv = df["Advertiser Name by AI"].value_counts().index[0]
check(same_summary(neo4j_graph.entity_summary(ds, adv), entity_summary(g, adv)),
      f"advertiser summary identical for '{adv}'")

pairs = (df.dropna(subset=["Advertiser Name by AI", "Publication", "AdvertiserSalesOffice", "Category"])
         .groupby(["AdvertiserSalesOffice", "Category"]).size().sort_values(ascending=False).head(3).index)
for office, cat in pairs:
    criteria = {"AdvertiserSalesOffice": office, "Category": cat}
    a = set(neo4j_graph.find_by_attributes(ds, criteria))
    b = set(find_by_attributes(g, criteria))
    check(a == b and a, f"office x category identical: {office} / {cat} ({len(a)} advertisers)")

# edit: move the top advertiser's first row to a new office, then check the graph followed
row = int(df.index[df["Advertiser Name by AI"] == adv][0])
edited = s.current_df.copy()
edited.loc[row, "AdvertiserSalesOffice"] = "Integration Test Office"
store.apply_edit(ds, edited, "standardize_value", "AdvertiserSalesOffice", 1, "integration", [])
hits = neo4j_graph.find_by_attributes(ds, {"AdvertiserSalesOffice": "Integration Test Office",
                                          "Category": str(edited.loc[row, "Category"])})
check(hits == [adv], f"edit synced to Neo4j: new office returns the advertiser (got {hits})")
g2 = build_graph(edited)
check(neo4j_graph.counts(ds)["edges"] == g2.number_of_edges(), "edge count still matches after the edit")
check(neo4j_graph.synced_version(ds) == 1, "Neo4j records it is at v1")

fuzzy = adv[: max(4, len(adv) // 2)].lower()
matches = neo4j_graph.resolve_entity(ds, fuzzy)
check(any(m["name"] == adv for m in matches), f"resolve_entity('{fuzzy}') finds '{adv}'")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
