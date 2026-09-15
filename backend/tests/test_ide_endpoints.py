"""
Tests for the read-only endpoints the IDE runs on.

These use a small synthetic frame rather than the real 11k-row file so
the suite stays fast and runnable without the sample data present. The
behaviours pinned here are the ones that were verified against the real
file during development and would silently regress:

  - strict JSON (no NaN tokens) - a single empty cell used to be enough
    to make the browser's JSON.parse throw and blank the whole grid
  - full, untruncated row lists from /issues, unlike the agent tool path
  - free-text search treating the query as a literal, not a regex
  - `__row__` always carrying the dataframe index, never a display position
"""

import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def frame():
    return pd.DataFrame({
        "Date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        "AdvertiserName": ["PARLE PRODUCTS PVT. LTD.", "ACME (INDIA)", None, "ACME (INDIA)"],
        "Advertiser Name by AI": ["Parle Products", "Acme India", "Orphan Co", "Acme India"],
        "Publication": ["Sakal", "Sakal", "Lokmat", "Lokmat"],
        "Category": ["Bank/Finance", None, "Fmcg", "Fmcg"],
        "Sub Category": ["Loans", "Retail", None, "Snacks"],
        "AdvertiserLocation": ["Pune", "Mumbai", "Pune", None],
        "AdvertiserSalesOffice": ["Pune", "Mumbai", "Pune", "Nagpur"],
        # blank here means "not a house ad" - NOT missing data
        "IsHouseAd": [None, "Yes", None, None],
    })


@pytest.fixture
def session_id(client, frame):
    buf = io.BytesIO()
    frame.to_excel(buf, index=False)
    buf.seek(0)
    res = client.post(
        "/upload",
        files={"file": ("t.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 200, res.text
    return res.json()["session_id"]


# ------------------------------------------------------------------ upload

def test_upload_reports_semantic_blanks_separately_from_gaps(client, session_id):
    issues = client.get(f"/issues/{session_id}").json()
    scopes = {i["scope"] for i in issues["issues"]}
    assert "column:IsHouseAd" not in scopes, "IsHouseAd blanks must never be reported as gaps"
    assert "column:Category" in scopes


def test_upload_column_meta_carries_domain_semantics(client, frame):
    buf = io.BytesIO()
    frame.to_excel(buf, index=False)
    buf.seek(0)
    body = client.post(
        "/upload",
        files={"file": ("t.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()

    meta = {m["name"]: m for m in body["column_meta"]}
    assert meta["IsHouseAd"]["blank_means"], "UI needs the reason IsHouseAd blanks are fine"
    assert meta["IsHouseAd"]["is_gap_checked"] is False
    assert meta["Category"]["is_gap_checked"] is True
    assert meta["Category"]["missing_count"] == 1


# -------------------------------------------------------------------- data

def test_data_is_strictly_valid_json(client, session_id):
    """NaN would serialize as a bare `NaN` token, which is invalid JSON and
    makes the browser throw before rendering a single row."""
    body = client.get(f"/data/{session_id}").json()
    json.loads(json.dumps(body, allow_nan=False))
    missing_cells = [r["Category"] for r in body["rows"] if r["Category"] is None]
    assert missing_cells == [None], "a genuine gap must arrive as null, not NaN or ''"


def test_data_row_key_is_the_dataframe_index_even_when_sorted(client, session_id):
    unsorted = client.get(f"/data/{session_id}").json()["rows"]
    assert [r["__row__"] for r in unsorted] == [0, 1, 2, 3]

    # Ascending, not descending: the fixture is already in descending
    # Publication order, so sorting desc is a no-op and would assert nothing.
    body = client.get(f"/data/{session_id}", params={"sort_by": "Publication", "sort_dir": "asc"}).json()
    ids = [r["__row__"] for r in body["rows"]]
    assert ids == [2, 3, 0, 1], "sorting should reorder the view, preserving original indices"
    # every edit is addressed by dataframe index, so a sorted view must not
    # renumber rows or a later fix would land on the wrong ones
    for row in body["rows"]:
        assert row["Publication"] == unsorted[row["__row__"]]["Publication"]


def test_search_treats_query_as_a_literal_not_a_regex(client, session_id):
    """'ACME (INDIA)' contains regex metacharacters. Before regex=False this
    raised an unbalanced-parenthesis error and 500'd the grid mid-keystroke."""
    res = client.get(f"/data/{session_id}", params={"q": "("})
    assert res.status_code == 200
    assert res.json()["filtered_rows"] == 2

    assert client.get(f"/data/{session_id}", params={"q": "a[b"}).status_code == 200
    assert client.get(f"/data/{session_id}", params={"q": "*"}).json()["filtered_rows"] == 0


def test_search_scans_every_column(client, session_id):
    assert client.get(f"/data/{session_id}", params={"q": "Nagpur"}).json()["filtered_rows"] == 1
    assert client.get(f"/data/{session_id}", params={"q": "sakal"}).json()["filtered_rows"] == 2


def test_missing_only_filter(client, session_id):
    body = client.get(f"/data/{session_id}", params={"column": "Category", "missing_only": True}).json()
    assert body["filtered_rows"] == 1
    assert body["rows"][0]["__row__"] == 1

    assert client.get(f"/data/{session_id}", params={"missing_only": True}).status_code == 400


def test_rows_param_jumps_to_specific_rows(client, session_id):
    body = client.get(f"/data/{session_id}", params={"rows": "0,3"}).json()
    assert [r["__row__"] for r in body["rows"]] == [0, 3]


def test_pagination_reports_totals_independently_of_the_page(client, session_id):
    body = client.get(f"/data/{session_id}", params={"offset": 1, "limit": 2}).json()
    assert body["total_rows"] == 4
    assert body["filtered_rows"] == 4
    assert len(body["rows"]) == 2


# ------------------------------------------------------------------ issues

def test_issues_returns_full_row_lists(client, session_id):
    """The agent tool caps row_indices at 20 to protect LLM context. The UI
    path must not, or the Problems panel and the agent would disagree about
    how many rows an issue covers - the exact confusion behind the
    silently-under-fixing bulk edit bug."""
    body = client.get(f"/issues/{session_id}").json()
    cat = next(i for i in body["issues"] if i["scope"] == "column:Category")
    assert cat["total_rows_affected"] == len(cat["row_indices"]) == 1

    name = [i for i in body["issues"] if i["issue_type"] == "name_mismatch"]
    assert name, "raw vs AI-normalized name disagreements should be reported"
    for issue in name:
        assert len(issue["row_indices"]) == issue["total_rows_affected"]


# ------------------------------------------------------------------- graph

def test_graph_stats_and_neighborhood(client, session_id):
    stats = client.get(f"/graph/{session_id}/stats").json()
    assert stats["nodes_by_type"]["Publication"] == 2
    assert stats["node_count"] > 0

    hit = client.get(f"/graph/{session_id}/search", params={"q": "acme"}).json()["results"]
    assert hit, "graph search should find the AI-normalized advertiser name"

    view = client.get(
        f"/graph/{session_id}/neighborhood",
        params={"node": hit[0]["id"], "depth": 1},
    ).json()
    assert view["center"] == hit[0]["id"]
    assert len(view["nodes"]) > 1


def test_neighborhood_collapses_parallel_edges_into_weights(client, session_id):
    """Acme ran two ads (rows 1 and 3) in two publications. In the raw
    MultiDiGraph those are separate edges; the view must collapse parallel
    edges so the panel draws one weighted line, not N stacked ones."""
    hit = client.get(f"/graph/{session_id}/search", params={"q": "acme"}).json()["results"][0]
    view = client.get(f"/graph/{session_id}/neighborhood", params={"node": hit["id"]}).json()
    pairs = [(e["source"], e["target"], e["relation"]) for e in view["edges"]]
    assert len(pairs) == len(set(pairs)), "edges must be unique per (source, target, relation)"
    assert all(e["weight"] >= 1 for e in view["edges"])


def test_unknown_graph_node_is_404(client, session_id):
    res = client.get(f"/graph/{session_id}/neighborhood", params={"node": "Advertiser::Nope"})
    assert res.status_code == 404


# -------------------------------------------------------- diff + versioning

def test_diff_covers_every_changed_cell_not_just_the_audit_preview(client, session_id):
    """The audit log's diff_preview is capped at 5 rows for readability.
    The grid needs all of them, or a bulk fix would light up 5 cells while
    claiming to have changed more."""
    from app.agent import execute_tool_call
    from app.data_store import session_store

    session = session_store.get(session_id)
    result = execute_tool_call("apply_edit", {
        "operation": "fill_missing_value_bulk",
        "column": "Category",
        "value": "UNSPECIFIED",
        "reason": "test",
    }, session)
    assert result["status"] == "applied"

    body = client.get(f"/diff/{session_id}/1").json()
    assert body["changed_cell_count"] == 1
    assert body["changed_cells"][0] == {
        "row": 1, "column": "Category", "before": None, "after": "UNSPECIFIED",
    }


def test_diff_of_version_zero_is_empty_not_an_error(client, session_id):
    body = client.get(f"/diff/{session_id}/0").json()
    assert body["changed_cell_count"] == 0


def test_diff_rejects_out_of_range_version(client, session_id):
    assert client.get(f"/diff/{session_id}/99").status_code == 400


def test_chat_reports_version_without_an_api_key(client, session_id, monkeypatch):
    """With no key configured the endpoint must fail loudly with 503 rather
    than appear to succeed - the UI keys its 'agent ready' state off this."""
    from app.config import settings
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    res = client.post("/chat", json={"session_id": session_id, "message": "hi"})
    assert res.status_code == 503


def test_unknown_session_is_404_everywhere(client):
    for path in ["/data/nope", "/issues/nope", "/graph/nope/stats", "/diff/nope/0", "/history/nope"]:
        assert client.get(path).status_code == 404, path


# -------------------------------------------------------- sessions + restore

def test_upload_returns_the_filename(client, session_id):
    body = client.get(f"/session/{session_id}").json()
    assert body["filename"] == "t.xlsx"
    assert body["current_version"] == 0
    assert body["transcript"] == []


def test_sample_endpoint_opens_the_bundled_file(client):
    res = client.post("/sample")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["filename"] == "Sample.xlsx"
    assert body["row_count"] > 0


def _edit(session_id):
    from app.agent import execute_tool_call
    from app.data_store import session_store
    return execute_tool_call("apply_edit", {
        "operation": "fill_missing_value_bulk", "column": "Category",
        "value": "UNSPECIFIED", "reason": "test",
    }, session_store.get(session_id))


def test_revert_appends_a_version_instead_of_deleting_history(client, session_id):
    assert _edit(session_id)["status"] == "applied"

    res = client.post("/revert", json={"session_id": session_id, "to_version": 0})
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "restored", "restored_from": 0,
                          "current_version": 2, "rows_affected": 1}

    hist = client.get(f"/history/{session_id}").json()
    assert [e["operation"] for e in hist["audit_log"]] == ["fill_missing_value_bulk", "restore"]

    # the restore itself is a diffable change: the filled cell goes back to blank
    diff = client.get(f"/diff/{session_id}/2").json()
    assert diff["changed_cells"] == [{"row": 1, "column": "Category",
                                      "before": "UNSPECIFIED", "after": None}]


def test_revert_to_the_current_version_is_rejected(client, session_id):
    res = client.post("/revert", json={"session_id": session_id, "to_version": 0})
    assert res.status_code == 400


def test_edit_records_how_to_repeat_it_in_excel(client, session_id):
    result = _edit(session_id)
    excel = result["_excel"]
    item = excel["items"][0]
    # Category is column E in the fixture; data starts on row 2
    assert item["formulas"][0]["formula"] == '=SUMPRODUCT(--(TRIM($E$2:$E$5)=""))'
    assert item["formulas"][0]["expected"] == 1
    hist = client.get(f"/history/{session_id}").json()
    assert hist["audit_log"][0]["excel"] == excel


def test_scoped_edit_lists_exactly_the_changed_cells(client, session_id):
    from app.agent import execute_tool_call
    from app.data_store import session_store
    result = execute_tool_call("apply_edit", {
        "operation": "standardize_value", "column": "AdvertiserSalesOffice",
        "row_indices": [0, 2], "value": "Pune HQ", "reason": "test",
    }, session_store.get(session_id))
    # AdvertiserSalesOffice is column H; df rows 0 and 2 are sheet rows 2 and 4
    assert result["_excel"]["items"][0]["cells"] == ["H2,H4"]
