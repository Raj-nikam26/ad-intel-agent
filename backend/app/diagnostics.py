"""
diagnostics.py
--------------
Detects and REPORTS data-quality issues. Never modifies data.

This is deliberately separate from safe_editor.py (which performs
edits). Keeping detection and mutation in different modules means the
"what's wrong with X" question path can never accidentally change
anything - the agent can call this freely, as often as it wants,
with zero risk to the underlying data.

Explicit non-goal: this module does NOT decide what "clean" data looks
like or normalize anything on its own. Per the brief, the raw data is
used as-is; this only surfaces facts about it (missing values,
inconsistent name variants, etc.) for a human - or the agent, on
explicit instruction - to act on.

Domain note baked into this logic (found by inspecting the real file,
not assumed): `IsHouseAd` is blank for non-house-ads and "Yes" for
house ads - that is NOT missing data, it's how the source system
encodes a boolean. Flagging it as "94% missing" would be a wrong,
generic diagnostic. Domain-aware nulls are treated differently from
genuine gaps (see NON_MISSING_SEMANTICS below).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

logger = logging.getLogger("ad_intel.diagnostics")

# Columns where a blank value has a real meaning (not a data gap).
# Add to this dict as more such columns are discovered in the source data -
# this is the one place such domain knowledge lives, not scattered
# inline as magic conditions.
NON_MISSING_SEMANTICS = {
    "IsHouseAd": "Blank means 'not a house ad'; 'Yes' means it is. This is expected, not a gap.",
}

# Columns worth checking for missing values as genuine gaps.
GAP_CHECK_COLUMNS = [
    "Category", "Sub Category", "AdvertiserName", "AdvertiserLocation",
    "AdvertiserSalesOffice", "Advertiser Name by AI",
]

NAME_SIMILARITY_THRESHOLD = 0.90


@dataclass
class Issue:
    issue_type: str
    scope: str          # e.g. "column:Category", "advertiser:SAKAL MEDIA PVT LTD", "row:1042"
    row_indices: list   # which rows this issue touches (for later editing)
    description: str
    sample: list = field(default_factory=list)


def detect_missing_value_gaps(df: pd.DataFrame, scope_column: str | None = None) -> list[Issue]:
    """Reports genuine missing-value gaps. Skips columns with known
    non-missing semantics (see NON_MISSING_SEMANTICS)."""
    issues = []
    columns = [scope_column] if scope_column else GAP_CHECK_COLUMNS
    for col in columns:
        if col not in df.columns or col in NON_MISSING_SEMANTICS:
            continue
        missing_mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        count = int(missing_mask.sum())
        if count > 0:
            issues.append(Issue(
                issue_type="missing_value",
                scope=f"column:{col}",
                row_indices=df[missing_mask].index.tolist(),
                description=f"{count} rows are missing a value in '{col}'.",
                sample=df[missing_mask].head(3).index.tolist(),
            ))
    return issues


def detect_name_variants(df: pd.DataFrame, name_column: str = "AdvertiserName",
                          canonical_column: str = "Advertiser Name by AI") -> list[Issue]:
    """Flags rows where the raw name and the existing AI-normalized name
    column disagree. This does not judge which one is 'correct' - it
    surfaces the disagreement so a human/agent-on-request can decide."""
    issues = []
    both = df.dropna(subset=[name_column, canonical_column])
    mismatch_mask = (
        both[name_column].str.strip().str.lower()
        != both[canonical_column].str.strip().str.lower()
    )
    mismatched = both[mismatch_mask]
    for _, group in mismatched.groupby(name_column):
        canonical_values = group[canonical_column].unique().tolist()
        issues.append(Issue(
            issue_type="name_mismatch",
            scope=f"advertiser:{group[name_column].iloc[0]}",
            row_indices=group.index.tolist(),
            description=(
                f"Raw name '{group[name_column].iloc[0]}' disagrees with "
                f"'{canonical_column}' value(s) {canonical_values} on {len(group)} row(s)."
            ),
            sample=canonical_values[:3],
        ))
    return issues


def detect_near_duplicate_advertisers(df: pd.DataFrame, column: str = "Advertiser Name by AI",
                                       threshold: float = NAME_SIMILARITY_THRESHOLD,
                                       max_comparisons: int = 5000) -> list[Issue]:
    """Flags pairs of distinct advertiser names that are suspiciously
    similar (likely the same advertiser, inconsistently spelled) and NOT
    already reconciled by the canonical AI-name column. Capped at
    max_comparisons for performance on large advertiser lists - this is
    an O(n^2) string comparison, documented as a known scaling limit
    (see README) rather than silently slow on the full ~5,000-advertiser list."""
    names = df[column].dropna().unique().tolist()
    issues = []
    comparisons = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            comparisons += 1
            if comparisons > max_comparisons:
                logger.info("detect_near_duplicate_advertisers: comparison cap reached")
                return issues
            a, b = names[i], names[j]
            if a.strip().lower() == b.strip().lower():
                continue
            ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if ratio >= threshold:
                rows = df[df[column].isin([a, b])].index.tolist()
                issues.append(Issue(
                    issue_type="near_duplicate_advertiser",
                    scope=f"advertiser_pair:{a}|{b}",
                    row_indices=rows,
                    description=f"'{a}' and '{b}' are {ratio:.0%} similar - possibly the same advertiser.",
                    sample=[a, b],
                ))
    return issues


def run_full_diagnostics(df: pd.DataFrame) -> list[Issue]:
    """Runs all checks. Used for a broad 'what issues exist' question."""
    issues = []
    issues += detect_missing_value_gaps(df)
    issues += detect_name_variants(df)
    issues += detect_near_duplicate_advertisers(df)
    return issues


def run_scoped_diagnostics(df: pd.DataFrame, scope_value: str) -> list[Issue]:
    """Runs checks scoped to one entity - e.g. one advertiser name, or
    one column - used when the user asks about a specific thing rather
    than 'everything'. `scope_value` is matched loosely against column
    names and advertiser names since the agent won't always know which
    the user means."""
    issues = []

    if scope_value in df.columns:
        issues += detect_missing_value_gaps(df, scope_column=scope_value)

    matching_rows = df[
        df.apply(lambda row: row.astype(str).str.contains(scope_value, case=False, na=False).any(), axis=1)
    ]
    if not matching_rows.empty:
        for issue in run_full_diagnostics(df):
            if set(issue.row_indices) & set(matching_rows.index):
                issues.append(issue)

    return issues
