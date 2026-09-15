import pandas as pd
import pytest
from app.safe_editor import (
    fill_missing_value, standardize_value, flag_rows, apply_operation, EditValidationError
)


def make_df():
    return pd.DataFrame({
        "Category": ["Finance", None, "Fmcg"],
        "AdvertiserName": ["ABC LTD", "XYZ CO", "PQR"],
    })


def test_fill_missing_value_only_touches_missing_rows():
    df = make_df()
    new_df, preview = fill_missing_value(df, "Category", [0, 1], "Unknown")
    assert new_df.at[1, "Category"] == "Unknown"
    assert new_df.at[0, "Category"] == "Finance"  # untouched - wasn't missing


def test_fill_missing_value_refuses_if_nothing_missing():
    df = make_df()
    with pytest.raises(EditValidationError):
        fill_missing_value(df, "Category", [0], "Unknown")  # row 0 isn't missing


def test_original_dataframe_never_mutated():
    df = make_df()
    original = df.copy(deep=True)
    fill_missing_value(df, "Category", [1], "Unknown")
    pd.testing.assert_frame_equal(df, original)


def test_standardize_value_requires_row_indices():
    df = make_df()
    with pytest.raises(EditValidationError):
        standardize_value(df, "AdvertiserName", [], "New Name")


def test_standardize_value_applies_to_specified_rows_only():
    df = make_df()
    new_df, preview = standardize_value(df, "AdvertiserName", [1], "XYZ Company Ltd")
    assert new_df.at[1, "AdvertiserName"] == "XYZ Company Ltd"
    assert new_df.at[0, "AdvertiserName"] == "ABC LTD"


def test_flag_rows_creates_column_if_missing():
    df = make_df()
    new_df, preview = flag_rows(df, [0, 2], "review_flag", "possible_duplicate")
    assert new_df.at[0, "review_flag"] == "possible_duplicate"
    assert new_df.at[1, "review_flag"] == ""


def test_apply_operation_rejects_unknown_operation():
    df = make_df()
    with pytest.raises(EditValidationError):
        apply_operation(df, "delete_everything", column="Category")


def test_apply_operation_dispatches_correctly():
    df = make_df()
    new_df, preview = apply_operation(df, "fill_missing_value", column="Category", row_indices=[1], value="Unknown")
    assert new_df.at[1, "Category"] == "Unknown"
