"""
diff.py
-------
Computes cell-level differences between two versions of the dataframe.

Why this is a separate module rather than reusing the `diff_preview`
already stored on each audit entry: that preview is capped at 5 rows on
purpose, because its job is to be *readable* in a log line. The IDE has
a different job - it needs to paint every single changed cell in the
grid, so that "fix all 138 missing Categories" visibly lights up 138
cells rather than 5. Same underlying idea, different completeness
requirement, so they stay separate rather than one growing a `limit`
argument and serving neither well.

This module is read-only. It never touches session data.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("ad_intel.diff")

# A hard cap so a pathological edit can't produce a multi-megabyte
# response. Well above the ~900-row worst case in the real file; if it
# ever trips, the response says so rather than silently truncating.
MAX_CHANGED_CELLS = 20_000


def _both_blank(a, b) -> bool:
    """Treats NaN, None and empty string as equivalent for change
    detection. Without this, a fill that replaces NaN with "" - or a
    round-trip through Excel export/import - would show up as a change
    when nothing meaningful moved."""
    a_blank = pd.isna(a) or str(a).strip() == ""
    b_blank = pd.isna(b) or str(b).strip() == ""
    return a_blank and b_blank


def _cell_changed(a, b) -> bool:
    if _both_blank(a, b):
        return False
    if pd.isna(a) or pd.isna(b):
        return True
    return str(a) != str(b)


def diff_versions(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """
    Returns every changed cell between two versions, plus added/removed
    columns (an edit can add a column - `flag_rows` creates the flag
    column when it doesn't exist yet).
    """
    added_columns = [c for c in after.columns if c not in before.columns]
    removed_columns = [c for c in before.columns if c not in after.columns]
    shared_columns = [c for c in after.columns if c in before.columns]

    shared_index = before.index.intersection(after.index)

    changes: list[dict] = []
    truncated = False

    for col in shared_columns:
        before_col = before.loc[shared_index, col]
        after_col = after.loc[shared_index, col]

        # Vectorized pre-filter: only inspect positions that differ under
        # pandas' own comparison (which already treats NaN != NaN), then
        # apply the blank-equivalence rule per candidate. On 11k rows this
        # is the difference between scanning ~20 cells and ~250,000.
        candidates = shared_index[~(before_col.eq(after_col) | (before_col.isna() & after_col.isna()))]

        for idx in candidates:
            b_val, a_val = before.at[idx, col], after.at[idx, col]
            if not _cell_changed(b_val, a_val):
                continue
            if len(changes) >= MAX_CHANGED_CELLS:
                truncated = True
                break
            changes.append({
                "row": int(idx),
                "column": col,
                "before": None if pd.isna(b_val) else str(b_val),
                "after": None if pd.isna(a_val) else str(a_val),
            })
        if truncated:
            break

    # A newly added column is entirely "new" - report only the rows where
    # it actually carries a value, not all 11k blank ones.
    for col in added_columns:
        for idx in after.index:
            val = after.at[idx, col]
            if pd.isna(val) or str(val).strip() == "":
                continue
            if len(changes) >= MAX_CHANGED_CELLS:
                truncated = True
                break
            changes.append({"row": int(idx), "column": col, "before": None, "after": str(val)})
        if truncated:
            break

    return {
        "changed_cells": changes,
        "changed_cell_count": len(changes),
        "changed_row_count": len({c["row"] for c in changes}),
        "added_columns": added_columns,
        "removed_columns": removed_columns,
        "truncated": truncated,
    }
