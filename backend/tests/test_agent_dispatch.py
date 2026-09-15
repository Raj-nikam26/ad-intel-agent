import pandas as pd
from app.agent import execute_tool_call
from app.data_store import session_store


def make_df():
    return pd.DataFrame({
        "Advertiser Name by AI": ["Acme Corp", "Acme Corp", "Beta Inc"],
        "AdvertiserName": ["ACME CORP", "ACME CORP", "BETA INC"],
        "Publication": ["Times", "Herald", "Times"],
        "Category": ["Finance", "Finance", None],
        "Sub Category": ["Loan", "Loan", None],
        "AdvertiserLocation": ["Pune", "Pune", "Mumbai"],
        "AdvertiserSalesOffice": ["Pune", "Pune", "Mumbai"],
        "Edition": ["Pune", "Mumbai", "Pune"],
        "Date": ["2026-01-01"] * 3,
        "Page": [1, 2, 3],
        "Width (cm)": [4, 4, 5],
        "Height (cm)": [5, 5, 5],
        "Area (sq cm)": [20, 20, 25],
        "Advertiser Reach": ["Regional"] * 3,
        "IsHouseAd": [None, None, "Yes"],
    })


def make_session():
    return session_store.create(make_df())


def test_detect_issues_tool_returns_structured_issues():
    session = make_session()
    result = execute_tool_call("detect_issues", {}, session)
    assert result["issue_count"] > 0
    assert any(i["type"] == "missing_value" for i in result["issues"])


def test_get_advertiser_summary_tool():
    session = make_session()
    result = execute_tool_call("get_advertiser_summary", {"advertiser": "Acme Corp"}, session)
    assert result["total_ad_insertions"] == 2


def test_get_advertiser_summary_unknown_advertiser():
    session = make_session()
    result = execute_tool_call("get_advertiser_summary", {"advertiser": "Nope Inc"}, session)
    assert "error" in result


def test_tabular_query_tool():
    session = make_session()
    result = execute_tool_call("tabular_query", {"expression": "df[df['Category']=='Finance']"}, session)
    assert result["row_count"] == 2


def test_tabular_query_rejects_unsafe_expression():
    session = make_session()
    result = execute_tool_call("tabular_query", {"expression": "__import__('os').system('ls')"}, session)
    assert "error" in result


def test_apply_edit_fill_missing_value_via_dispatcher():
    session = make_session()
    result = execute_tool_call("apply_edit", {
        "operation": "fill_missing_value",
        "column": "Category",
        "row_indices": [2],
        "value": "Uncategorized",
        "reason": "user requested fix for missing category on row 2",
    }, session)
    assert result["status"] == "applied"
    assert session.current_df.at[2, "Category"] == "Uncategorized"
    # audit log recorded
    assert len(session.audit_log) == 1
    assert session.audit_log[0].reason.startswith("user requested")


def test_fill_missing_value_bulk_via_dispatcher_fixes_all_not_just_shown_sample():
    session = make_session()
    # Simulate: detect_issues would only show a capped sample, but bulk
    # fix must still catch every missing row, not just the sample.
    result = execute_tool_call("apply_edit", {
        "operation": "fill_missing_value_bulk",
        "column": "Category",
        "value": "Uncategorized",
        "reason": "user asked to fix all missing categories",
    }, session)
    assert result["status"] == "applied"
    assert result["rows_affected"] == 1  # row 2 is the only missing Category in this fixture
    assert session.current_df.at[2, "Category"] == "Uncategorized"
    session = make_session()
    result = execute_tool_call("apply_edit", {
        "operation": "delete_everything",
        "row_indices": [0],
        "reason": "malicious",
    }, session)
    assert "error" in result


def test_original_data_preserved_after_edit():
    session = make_session()
    execute_tool_call("apply_edit", {
        "operation": "fill_missing_value",
        "column": "Category",
        "row_indices": [2],
        "value": "Uncategorized",
        "reason": "fix",
    }, session)
    assert pd.isna(session.original_df.at[2, "Category"])  # original untouched
    assert len(session.versions) == 2  # v0 original + v1 after edit
