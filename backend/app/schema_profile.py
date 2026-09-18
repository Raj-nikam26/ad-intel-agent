"""
schema_profile.py
-----------------
Works out what an uploaded spreadsheet contains, so the app is not tied
to one dataset.

Nothing here is specific to ad data. Each column is classified from its
values, and the result drives both the data-quality checks and the shape
of the knowledge graph:

  subject   the thing each row is mostly about (advertiser, customer,
            patient, product). Repeated text with many distinct values.
  entity    attributes worth linking and grouping by - categories,
            cities, offices. Repeated text with few distinct values.
  measure   numbers to total or compare.
  date      when the row happened.
  flag      mostly blank with one or two distinct values, where blank
            means "no" rather than "missing". This is the IsHouseAd case
            from the sample file, found by shape instead of by name.
  identifier  nearly unique per row - reference numbers, free text. Not
            linked in the graph, because a node per row says nothing.

The caller can override any of it, so a user who disagrees is never
stuck with a guess.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

logger = logging.getLogger("ad_intel.schema")

MAX_ENTITY_COLUMNS = 10
# A column is an attribute worth linking if its values repeat: either a
# small fixed set, or few distinct values relative to the row count. The
# absolute cap matters on short files, where every ratio looks large.
ENTITY_DISTINCT_RATIO = 0.5
ENTITY_DISTINCT_MAX = 20
SUBJECT_DISTINCT_RATIO = 0.95
FLAG_MISSING_RATIO = 0.5

# Names used by the graph when a column plays a familiar role, so a
# relationship reads as RAN_AD rather than HAS_PUBLICATION. Purely
# cosmetic; unknown columns get a name generated from the column itself.
FRIENDLY_TYPES = {
    "advertiser name by ai": "Advertiser",
    "advertisername": "AdvertiserRawName",
    "publication": "Publication",
    "category": "Category",
    "sub category": "SubCategory",
    "subcategory": "SubCategory",
    "advertiserlocation": "Location",
    "advertisersalesoffice": "SalesOffice",
}
FRIENDLY_RELATIONS = {
    "publication": "RAN_AD",
    "advertiserlocation": "LOCATED_IN",
    "advertisersalesoffice": "SERVICED_BY",
}


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def type_name(column: str) -> str:
    key = column.strip().lower()
    if key in FRIENDLY_TYPES:
        return FRIENDLY_TYPES[key]
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", column).strip()
    return "".join(w[:1].upper() + w[1:] for w in cleaned.split()) or "Value"


def relation_name(column: str) -> str:
    key = column.strip().lower()
    if key in FRIENDLY_RELATIONS:
        return FRIENDLY_RELATIONS[key]
    return "HAS_" + (re.sub(r"[^0-9A-Za-z]+", "_", column).strip("_").upper() or "VALUE")


def profile_columns(df: pd.DataFrame) -> list[dict]:
    total = max(len(df), 1)
    out = []
    for col in df.columns:
        s = df[col]
        blank = _blank_mask(s)
        present = s[~blank]
        distinct = int(present.nunique())
        is_numeric = bool(pd.api.types.is_numeric_dtype(s))
        is_datetime = bool(pd.api.types.is_datetime64_any_dtype(s))
        if not is_datetime and not is_numeric and distinct and "date" in str(col).lower():
            parsed = pd.to_datetime(present, errors="coerce", format="mixed")
            is_datetime = bool(parsed.notna().mean() > 0.9)
        out.append({
            "name": col,
            "dtype": str(s.dtype),
            "missing": int(blank.sum()),
            "missing_ratio": round(float(blank.mean()), 4),
            "distinct": distinct,
            "distinct_ratio": round(distinct / total, 4),
            "is_numeric": is_numeric,
            "is_datetime": is_datetime,
            "examples": [str(v) for v in present.head(3).tolist()],
        })
    return out


def _classify(p: dict) -> str:
    if p["distinct"] == 0:
        return "empty"
    if p["is_datetime"]:
        return "date"
    if p["is_numeric"]:
        # An all-distinct integer column is an id, not something to total.
        return "identifier" if p["distinct_ratio"] > SUBJECT_DISTINCT_RATIO else "measure"
    if p["missing_ratio"] >= FLAG_MISSING_RATIO and p["distinct"] <= 3:
        return "flag"
    if p["distinct_ratio"] > SUBJECT_DISTINCT_RATIO:
        return "identifier"
    if p["distinct_ratio"] <= ENTITY_DISTINCT_RATIO or p["distinct"] <= ENTITY_DISTINCT_MAX:
        return "entity"
    return "text"


def infer_mapping(df: pd.DataFrame) -> dict:
    """Returns the roles for each column, plus the subject and entity
    columns the graph is built from."""
    profiles = profile_columns(df)
    roles = {p["name"]: _classify(p) for p in profiles}
    by_name = {p["name"]: p for p in profiles}

    # Subject: the repeated text column with the most distinct values -
    # the column whose values the questions will be about. Ties go to the
    # more complete column, which on the sample picks the cleaned
    # "Advertiser Name by AI" over the raw name.
    candidates = [p for p in profiles if roles[p["name"]] in ("entity", "text")]
    subject = None
    if candidates:
        candidates.sort(key=lambda p: (-p["distinct"], p["missing"]))
        subject = candidates[0]["name"]
        roles[subject] = "subject"

    # Fewest distinct values first: a column with a handful of repeated
    # values groups the data usefully, while one with thousands is closer
    # to free text. Matters when there are more candidates than the cap.
    entity_profiles = sorted(
        (p for p in profiles if roles[p["name"]] == "entity" and p["name"] != subject),
        key=lambda p: p["distinct"],
    )
    entities = [p["name"] for p in entity_profiles[:MAX_ENTITY_COLUMNS]]
    for p in entity_profiles[MAX_ENTITY_COLUMNS:]:
        roles[p["name"]] = "text"

    flags = {
        p["name"]: (f"Blank appears to mean 'no'. {p['distinct']} distinct value(s) "
                    f"({', '.join(p['examples'][:2])}) in {100 - p['missing_ratio'] * 100:.0f}% of rows.")
        for p in profiles if roles[p["name"]] == "flag"
    }

    mapping = {
        "subject": subject,
        "entities": entities,
        "measures": [p["name"] for p in profiles if roles[p["name"]] == "measure"],
        "dates": [p["name"] for p in profiles if roles[p["name"]] == "date"],
        "flags": flags,
        "roles": roles,
        "columns": profiles,
    }
    logger.info("Inferred schema: subject=%s entities=%s flags=%s", subject, entities, list(flags))
    return mapping


def gap_columns(mapping: dict) -> list[str]:
    """Columns where a blank is a genuine gap: everything except flags,
    empty columns, and free-text identifiers nobody expects to be filled."""
    return [name for name, role in mapping["roles"].items()
            if role in ("subject", "entity", "text", "measure", "date")]
