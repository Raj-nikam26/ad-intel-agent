"""
diagnostics.py
--------------
Detects and REPORTS data-quality issues. Never modifies data.

Separate from safe_editor.py on purpose: the "what's wrong with X"
path can never change anything, so the agent may call it as often as it
likes at zero risk.

The checks work on any uploaded file. Which columns to check is decided
from the data itself (see schema_profile.py), not from a fixed list of
names:

  missing values      in columns where a blank is a genuine gap
  disagreeing columns two columns that usually hold the same value but
                      differ on some rows
  near-duplicates     values in the subject column that are almost the
                      same string, so probably one thing spelled two ways

Explicit non-goal: nothing here decides what "clean" means or normalises
anything. Per the brief, the data is used as-is; this only surfaces facts
for a human - or the agent on explicit instruction - to act on.

The one place a blank is NOT a gap is a flag column: mostly empty, with
one or two distinct values, where empty means "no". The sample file's
IsHouseAd is blank in 10,595 of 11,275 rows and a generic missing-value
check would call it the worst column in the file. It is inferred by that
shape, so the same protection applies to any file's flag columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

from app.schema_profile import gap_columns, infer_mapping

logger = logging.getLogger("ad_intel.diagnostics")

# Domain knowledge that survives regardless of what the inference says.
# Anything discovered about a specific source system belongs here rather
# than scattered inline.
NON_MISSING_SEMANTICS = {
    "IsHouseAd": "Blank means 'not a house ad'; 'Yes' means it is. This is expected, not a gap.",
}

NAME_SIMILARITY_THRESHOLD = 0.90
PAIR_SIMILARITY = 0.50              # how alike two columns must look to be treated as a pair
PAIR_SAMPLE = 200                   # rows sampled when judging that
PAIR_CARDINALITY = 0.80             # how close their distinct-value counts must be
MAX_COLUMN_PAIRS = 6


@dataclass
class Issue:
    issue_type: str
    scope: str          # e.g. "column:Category", "advertiser:SAKAL MEDIA PVT LTD"
    row_indices: list   # which rows this issue touches (for later editing)
    description: str
    sample: list = field(default_factory=list)


def _mapping(df: pd.DataFrame, mapping: dict | None = None) -> dict:
    return mapping or infer_mapping(df)


def semantic_blanks(df: pd.DataFrame, mapping: dict | None = None) -> dict[str, str]:
    """Columns where a blank carries meaning, inferred plus known."""
    found = dict(_mapping(df, mapping).get("flags", {}))
    for col, note in NON_MISSING_SEMANTICS.items():
        if col in df.columns:
            found[col] = note
    return found


def _blank_mask(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].isna() | (df[col].astype(str).str.strip() == "")


def detect_missing_value_gaps(df: pd.DataFrame, scope_column: str | None = None,
                              mapping: dict | None = None) -> list[Issue]:
    """Reports genuine missing-value gaps, skipping columns where a blank
    means something."""
    mapping = _mapping(df, mapping)
    skip = semantic_blanks(df, mapping)
    columns = [scope_column] if scope_column else gap_columns(mapping)
    issues = []
    for col in columns:
        if col not in df.columns or col in skip:
            continue
        missing = _blank_mask(df, col)
        count = int(missing.sum())
        if count:
            issues.append(Issue(
                issue_type="missing_value",
                scope=f"column:{col}",
                row_indices=df[missing].index.tolist(),
                description=(f"{count} row is missing a value in '{col}'." if count == 1
                             else f"{count} rows are missing a value in '{col}'."),
                sample=df[missing].head(3).index.tolist(),
            ))
    return issues


def detect_column_disagreements(df: pd.DataFrame, mapping: dict | None = None) -> list[Issue]:
    """Finds pairs of columns that usually hold the same value but differ
    on some rows - two spellings of a name, a raw and a cleaned field.

    It does not judge which side is right. It reports the disagreement and
    leaves the decision to a person.
    """
    mapping = _mapping(df, mapping)
    text_cols = [c for c, role in mapping["roles"].items()
                 if role in ("subject", "entity", "text", "identifier") and c in df.columns]
    issues: list[Issue] = []
    pairs = 0

    for i, a in enumerate(text_cols):
        for b in text_cols[i + 1:]:
            if pairs >= MAX_COLUMN_PAIRS:
                return issues
            both = df.dropna(subset=[a, b])
            if both.empty:
                continue
            left = both[a].astype(str).str.strip().str.lower()
            right = both[b].astype(str).str.strip().str.lower()

            # Are these two columns holding the same KIND of value? Judged by
            # how alike the strings are, not by how often they match exactly -
            # a raw name and a cleaned name disagree on every row yet clearly
            # describe the same thing.
            sample = list(zip(left.head(PAIR_SAMPLE), right.head(PAIR_SAMPLE)))
            if not sample:
                continue
            likeness = sum(SequenceMatcher(None, x, y).ratio() for x, y in sample) / len(sample)
            if likeness < PAIR_SIMILARITY or likeness > 0.999:
                continue

            # Two spellings of the same thing have roughly the same number of
            # distinct values. A city column and the office covering it look
            # alike string-wise but are many-to-one, and reporting every row
            # where they differ would be noise, not a data-quality problem.
            counts = sorted((left.nunique(), right.nunique()))
            if not counts[1] or counts[0] / counts[1] < PAIR_CARDINALITY:
                continue

            pairs += 1
            mismatched = both[left != right]
            for _, group in mismatched.groupby(a):
                other = group[b].unique().tolist()
                issues.append(Issue(
                    issue_type="name_mismatch",
                    scope=f"advertiser:{group[a].iloc[0]}",
                    row_indices=group.index.tolist(),
                    description=(f"'{a}' value '{group[a].iloc[0]}' disagrees with "
                                 f"'{b}' value(s) {other} on {len(group)} row(s)."),
                    sample=other[:3],
                ))
    return issues


def detect_near_duplicates(df: pd.DataFrame, column: str | None = None,
                           threshold: float = NAME_SIMILARITY_THRESHOLD,
                           max_comparisons: int = 5000,
                           mapping: dict | None = None) -> list[Issue]:
    """Flags values in the subject column that are suspiciously similar -
    likely one thing spelled two ways.

    Capped at max_comparisons: this is an O(n^2) string comparison, so on
    a long list it stops early rather than becoming silently slow.
    """
    mapping = _mapping(df, mapping)
    column = column or mapping.get("subject")
    if not column or column not in df.columns:
        return []

    names = df[column].dropna().unique().tolist()
    issues, comparisons = [], 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            comparisons += 1
            if comparisons > max_comparisons:
                logger.info("detect_near_duplicates: comparison cap reached")
                return issues
            a, b = str(names[i]), str(names[j])
            if a.strip().lower() == b.strip().lower():
                continue
            ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if ratio >= threshold:
                rows = df[df[column].isin([names[i], names[j]])].index.tolist()
                issues.append(Issue(
                    issue_type="near_duplicate_advertiser",
                    scope=f"advertiser_pair:{a}|{b}",
                    row_indices=rows,
                    description=f"'{a}' and '{b}' are {ratio:.0%} similar - possibly the same thing.",
                    sample=[a, b],
                ))
    return issues


def run_full_diagnostics(df: pd.DataFrame, mapping: dict | None = None) -> list[Issue]:
    mapping = _mapping(df, mapping)
    return (detect_missing_value_gaps(df, mapping=mapping)
            + detect_column_disagreements(df, mapping=mapping)
            + detect_near_duplicates(df, mapping=mapping))


def run_scoped_diagnostics(df: pd.DataFrame, scope_value: str, mapping: dict | None = None) -> list[Issue]:
    """Checks scoped to one column or one value, for when the user asks
    about a specific thing rather than everything."""
    mapping = _mapping(df, mapping)
    issues = []
    if scope_value in df.columns:
        issues += detect_missing_value_gaps(df, scope_column=scope_value, mapping=mapping)

    matching = df[df.apply(
        lambda row: row.astype(str).str.contains(scope_value, case=False, na=False).any(), axis=1)]
    if not matching.empty:
        for issue in run_full_diagnostics(df, mapping=mapping):
            if set(issue.row_indices) & set(matching.index):
                issues.append(issue)
    return issues


# Older name kept so existing callers and tests keep working.
detect_name_variants = detect_column_disagreements
detect_near_duplicate_advertisers = detect_near_duplicates
