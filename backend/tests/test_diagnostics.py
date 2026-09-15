import pandas as pd
from app.diagnostics import (
    detect_missing_value_gaps, detect_name_variants, NON_MISSING_SEMANTICS
)


def make_df():
    return pd.DataFrame({
        "Category": ["Finance", None, "Fmcg"],
        "AdvertiserName": ["ABC LTD", "XYZ CO", None],
        "Advertiser Name by AI": ["ABC Ltd", "Different Name Co", "PQR"],
        "IsHouseAd": [None, "Yes", None],
    })


def test_missing_value_gap_detected():
    issues = detect_missing_value_gaps(make_df())
    cats = [i for i in issues if i.scope == "column:Category"]
    assert len(cats) == 1
    assert cats[0].row_indices == [1]


def test_non_missing_semantic_column_skipped():
    # IsHouseAd has 2/3 values missing but has known non-missing semantics
    # (blank = not a house ad) - must NOT be reported as a gap.
    issues = detect_missing_value_gaps(make_df())
    assert all(i.scope != "column:IsHouseAd" for i in issues)
    assert "IsHouseAd" in NON_MISSING_SEMANTICS


def test_name_mismatch_detected():
    issues = detect_name_variants(make_df())
    scopes = [i.scope for i in issues]
    assert "advertiser:XYZ CO" in scopes


def test_no_mutation_of_input():
    df = make_df()
    original = df.copy(deep=True)
    detect_missing_value_gaps(df)
    detect_name_variants(df)
    pd.testing.assert_frame_equal(df, original)
