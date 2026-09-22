"""
main.py
-------
Endpoints:

  Session
    POST /upload                  - load the Excel file AS-IS (no cleaning), start a session
    POST /sample                  - start a session on the bundled sample file
    GET  /session/{session_id}    - reopen a saved session (sessions survive restarts)
    GET  /export/{session_id}     - download the current (possibly edited) version

  The IDE surface (read-only views onto the working data)
    GET  /data/{session_id}       - paginated window on the table, with search/filter/sort
    GET  /issues/{session_id}     - structured issue list for the Problems panel
    GET  /graph/{session_id}/stats        - graph overview
    GET  /graph/{session_id}/neighborhood - subgraph around one node, for the graph panel
    GET  /graph/{session_id}/search       - node lookup by name
    GET  /diff/{session_id}/{version}     - every cell changed by one edit

  Agent + versioning
    POST /chat                    - one conversational turn; may read, or may edit
    GET  /history/{session_id}    - full audit log of edits made this session
    POST /revert                  - restore an earlier version (appends; never deletes history)

Design note on the read endpoints: they exist so the UI can show the
data directly, without going through the LLM. Asking an agent to
paginate a spreadsheet would be slow, expensive and non-deterministic
for something the server can answer exactly. The LLM is reserved for
the part that actually needs judgement - interpreting the question and
choosing the edit. The panels read; the agent reasons.
"""

from __future__ import annotations

import io
import json
import logging
import math
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, File, UploadFile, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import rate_limit
from app.agent import run_agent_turn
from app import excel_formulas
from app.excel_reader import read_table
from app.safe_editor import EditValidationError, apply_operation
from app.auth import current_user, optional_user, owns, router as auth_router
from app.config import settings
from app.data_store import session_store, Session, VersionConflictError
from app.diagnostics import run_full_diagnostics, run_scoped_diagnostics, semantic_blanks
from app.schema_profile import gap_columns, infer_mapping
from app.diff import diff_versions
from app.graph_cache import get_graph, invalidate_session
from app.graph_sync import on_new_version
from app.schemas import (
    UploadResponse, ColumnMeta, DataPage, ChatRequest, ChatResponse,
    HistoryResponse, AuditLogEntry, RevertRequest, RevertResponse, AddColumnRequest, AddColumnResponse,
    MappingResponse, MappingRequest,
    IssuesResponse, IssueOut, GraphStats, GraphNode, GraphEdge, GraphView,
    DiffResponse,
)

logging.basicConfig(level=settings.log_level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("ad_intel.main")

# Every saved version is mirrored into the knowledge graph (no-op unless NEO4J_URI is set).
session_store.add_listener(on_new_version)

app = FastAPI(
    title="Ad Intelligence Agent",
    description="Conversational agent over ad-tracking data: detects issues, "
                 "answers relational questions via a graph, and applies scoped, "
                 "audited edits on explicit request. Source data is never "
                 "auto-cleaned.",
    version="2.0.0",
)

app.include_router(auth_router)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # The API returns JSON and file downloads only, never pages.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _require_session(session_id: str, user: dict | None = None) -> Session:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found. Please re-upload.")
    if not owns(session, user):
        # 404 rather than 403: someone guessing ids learns nothing about
        # which of them exist.
        raise HTTPException(status_code=404, detail="Session not found. Please re-upload.")
    return session


def _json_safe(value: Any) -> Any:
    """Converts one cell to something strictly JSON-serializable.

    NaN/Inf are the reason this exists: FastAPI will happily emit bare
    `NaN` tokens, which are invalid JSON and make the browser's
    JSON.parse throw - the whole grid would fail to load because of one
    empty cell, of which this file has ~150.

    Missing becomes null, NOT empty string. The distinction matters
    downstream: the grid renders null as a visible gap and "" as an
    intentional empty value, and conflating them would misrepresent the
    raw data the brief says to preserve as-is.
    """
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, (int, float, bool, str)):
        return value
    # Timestamps, numpy scalars, Decimals, everything else -> string form.
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Row dicts with a stable `__row__` key carrying the dataframe index.

    The UI must always show and send the ORIGINAL index, never a display
    position, because every edit operation is addressed by dataframe
    index. Sorting or filtering the view would otherwise silently
    re-point an edit at the wrong rows.
    """
    out = []
    for idx, row in df.iterrows():
        record: dict[str, Any] = {"__row__": int(idx)}
        for col in df.columns:
            record[col] = _json_safe(row[col])
        out.append(record)
    return out


def _mapping(session: Session) -> dict:
    """The inferred schema for this session, worked out once."""
    if session.mapping is None:
        session.mapping = infer_mapping(session.current_df)
    return session.mapping


def _column_meta(df: pd.DataFrame, mapping: dict) -> list[ColumnMeta]:
    blanks = semantic_blanks(df, mapping)
    checked = set(gap_columns(mapping))
    meta = []
    for col in df.columns:
        missing = int((df[col].isna() | (df[col].astype(str).str.strip() == "")).sum())
        meta.append(ColumnMeta(
            name=col,
            dtype=str(df[col].dtype),
            missing_count=missing,
            blank_means=blanks.get(col),
            is_gap_checked=col in checked and col not in blanks,
        ))
    return meta


def _current_version(session: Session) -> int:
    return len(session.versions) - 1


def _session_payload(session: Session) -> UploadResponse:
    df = session.current_df
    return UploadResponse(
        session_id=session.session_id,
        filename=session.filename,
        row_count=len(df),
        column_count=len(df.columns),
        columns=df.columns.tolist(),
        column_meta=_column_meta(df, _mapping(session)),
        preview=_records(df.head(5)),
        current_version=_current_version(session),
        transcript=session.transcript,
    )


def _start_session(contents: bytes, filename: str, owner_id: str | None = None) -> UploadResponse:
    try:
        # Deliberately NO cleaning step here - the data is stored exactly
        # as uploaded. See diagnostics.py for read-only issue detection
        # and safe_editor.py for the only path that can ever change it.
        # read_table only locates the table (header row, margins); it
        # does not alter any value inside it.
        df, where = read_table(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Could not parse this file as Excel.") from e

    if df.empty:
        raise HTTPException(status_code=400, detail="Uploaded file has no rows.")

    session = session_store.create(df, filename=filename, owner_id=owner_id)
    logger.info("Session created: %s (%s rows, %s columns, table at %s!%s)",
                session.session_id, len(df), len(df.columns), where.sheet, where.origin)
    payload = _session_payload(session)
    if where.moved:
        payload.notice = (f"Table found at {where.origin} on sheet '{where.sheet}'. "
                          f"Headings were taken from row {where.header_row}; row numbers here "
                          "match the exported file, where the table starts at A1.")
    return payload


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------

@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "agent_configured": bool(settings.openrouter_api_key),
        "auth_enabled": settings.auth_enabled,
        "user": optional_user(request),
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(http: Request, file: UploadFile = File(...), user: dict | None = Depends(current_user)):
    rate_limit.check("upload", http, user)
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx or .xls file.")

    contents = await file.read()
    if len(contents) / (1024 * 1024) > settings.max_upload_size_mb:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_upload_size_mb} MB limit.")

    return _start_session(contents, file.filename, owner_id=user["id"] if user else None)


@app.post("/sample", response_model=UploadResponse)
def start_sample(http: Request, user: dict | None = Depends(current_user)):
    """Opens the bundled dataset. Someone trying a deployed copy of the app
    has no file of their own, and should not need one to see it work."""
    rate_limit.check("upload", http, user)
    path = settings.resolved_sample_file
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The sample file is not available on this server.")
    return _start_session(path.read_bytes(), path.name, owner_id=user["id"] if user else None)


@app.get("/session/{session_id}", response_model=UploadResponse)
def reopen_session(session_id: str, user: dict | None = Depends(current_user)):
    return _session_payload(_require_session(session_id, user))


def _mapping_payload(session: Session) -> MappingResponse:
    m = _mapping(session)
    return MappingResponse(
        session_id=session.session_id,
        subject=m.get("subject"), entities=m.get("entities", []),
        measures=m.get("measures", []), dates=m.get("dates", []),
        flags=m.get("flags", {}), roles=m.get("roles", {}), columns=m.get("columns", []),
    )


@app.get("/mapping/{session_id}", response_model=MappingResponse)
def get_mapping(session_id: str, user: dict | None = Depends(current_user)):
    """The inferred column roles. The guess is visible so it can be corrected."""
    return _mapping_payload(_require_session(session_id, user))


@app.post("/mapping/{session_id}", response_model=MappingResponse)
def set_mapping(session_id: str, request: MappingRequest, user: dict | None = Depends(current_user)):
    """Overrides the inferred roles. The graph is rebuilt from the new
    mapping, because which column is the subject changes its whole shape."""
    session = _require_session(session_id, user)
    m = dict(_mapping(session))
    columns = set(session.current_df.columns)

    if request.subject is not None:
        if request.subject not in columns:
            raise HTTPException(status_code=400, detail=f"Unknown column '{request.subject}'.")
        m["subject"] = request.subject
    if request.entities is not None:
        unknown = [c for c in request.entities if c not in columns]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown column(s): {', '.join(unknown)}.")
        m["entities"] = [c for c in request.entities if c != m.get("subject")]
    if request.flags is not None:
        unknown = [c for c in request.flags if c not in columns]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown column(s): {', '.join(unknown)}.")
        m["flags"] = {c: "Blank means 'no' - set by you, not inferred." for c in request.flags}

    roles = dict(m["roles"])
    for col in columns:
        if col == m.get("subject"):
            roles[col] = "subject"
        elif col in m.get("entities", []):
            roles[col] = "entity"
        elif col in m.get("flags", {}):
            roles[col] = "flag"
        elif roles.get(col) in ("subject", "entity", "flag"):
            roles[col] = "text"
    m["roles"] = roles
    session.mapping = m

    invalidate_session(session_id)
    on_new_version(session_id, _current_version(session), None, session.current_df)
    logger.info("Mapping overridden for %s: subject=%s entities=%s", session_id, m["subject"], m["entities"])
    return _mapping_payload(session)


@app.get("/export/{session_id}")
def export(session_id: str, user: dict | None = Depends(current_user)):
    session = _require_session(session_id, user)
    buffer = io.BytesIO()
    session.current_df.to_excel(buffer, index=False)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=edited_v{_current_version(session)}.xlsx"},
    )


# --------------------------------------------------------------------------
# the IDE surface
# --------------------------------------------------------------------------

@app.get("/data/{session_id}", response_model=DataPage)
def get_data(
    session_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: str | None = Query(None, description="Free-text search across all columns."),
    column: str | None = Query(None, description="Restrict `q` / `missing_only` to one column."),
    missing_only: bool = Query(False, description="Only rows missing a value in `column`."),
    rows: str | None = Query(None, description="Comma-separated dataframe indices to show (used when jumping to an issue)."),
    sort_by: str | None = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    user: dict | None = Depends(current_user),
):
    """A window onto the current version of the table.

    Note `rows`: the Problems panel uses it to jump the grid straight to
    the rows an issue touches. That's the interaction that makes this an
    IDE rather than a viewer - a problem is a thing you click to land on,
    the same way you'd click a compiler error and land on the line.
    """
    session = _require_session(session_id, user)
    df = session.current_df
    total_rows = len(df)

    view = df

    if rows:
        try:
            wanted = [int(r) for r in rows.split(",") if r.strip()]
        except ValueError as e:
            raise HTTPException(status_code=400, detail="`rows` must be comma-separated integers.") from e
        view = view.loc[view.index.intersection(wanted)]

    if missing_only:
        if not column or column not in df.columns:
            raise HTTPException(status_code=400, detail="`missing_only` requires a valid `column`.")
        view = view[view[column].isna() | (view[column].astype(str).str.strip() == "")]

    if q:
        # regex=False on both paths: this string comes straight from a
        # search box, and advertiser names in this file are full of
        # regex metacharacters - "PARLE PRODUCTS PVT. LTD." is harmless,
        # but a name containing "(" would otherwise raise an unbalanced-
        # parenthesis error and 500 the grid mid-keystroke.
        if column:
            if column not in df.columns:
                raise HTTPException(status_code=400, detail=f"Unknown column '{column}'.")
            mask = view[column].astype(str).str.contains(q, case=False, na=False, regex=False)
        else:
            # Column-wise OR rather than a row-wise df.apply. The apply
            # version builds a Series per row - 11,275 of them - and took
            # ~1.8s per keystroke against the real file. This does one
            # vectorized pass per column (16 of them) instead.
            mask = pd.Series(False, index=view.index)
            for col in view.columns:
                mask |= view[col].astype(str).str.contains(q, case=False, na=False, regex=False)
        view = view[mask]

    if sort_by:
        if sort_by not in df.columns:
            raise HTTPException(status_code=400, detail=f"Unknown column '{sort_by}'.")
        # na_position last in both directions: a sorted view should not
        # bury the missing values the user is most likely hunting for.
        view = view.sort_values(sort_by, ascending=(sort_dir == "asc"), na_position="last")

    filtered_rows = len(view)
    page = view.iloc[offset: offset + limit]

    return DataPage(
        session_id=session_id,
        version=_current_version(session),
        offset=offset,
        limit=limit,
        total_rows=total_rows,
        filtered_rows=filtered_rows,
        columns=df.columns.tolist(),
        rows=_records(page),
    )


@app.get("/issues/{session_id}", response_model=IssuesResponse)
def get_issues(
    session_id: str,
    scope: str | None = Query(None, description="Column or advertiser name to scope the check to."),
    limit: int = Query(200, ge=1, le=1000),
    user: dict | None = Depends(current_user),
):
    """Structured issue list for the Problems panel.

    Unlike the agent's `detect_issues` tool - which truncates row lists
    to keep the LLM context small - this returns the full row list per
    issue, because the UI needs to be able to select and act on all of
    them. That truncation was the source of a real bug (a bulk fix that
    only fixed the 20 rows the model could see); keeping the UI path
    untruncated means the panel and the agent can't disagree about how
    many rows an issue actually covers.
    """
    session = _require_session(session_id, user)
    df = session.current_df

    mapping = _mapping(session)
    issues = (run_scoped_diagnostics(df, scope, mapping=mapping) if scope
              else run_full_diagnostics(df, mapping=mapping))

    counts: dict[str, int] = {}
    for i in issues:
        counts[i.issue_type] = counts.get(i.issue_type, 0) + 1

    return IssuesResponse(
        session_id=session_id,
        version=_current_version(session),
        total_issues=len(issues),
        counts_by_type=counts,
        issues=[
            IssueOut(
                issue_type=i.issue_type,
                scope=i.scope,
                description=i.description,
                row_indices=[int(r) for r in i.row_indices],
                total_rows_affected=len(i.row_indices),
                sample=[_json_safe(s) for s in i.sample],
            )
            for i in issues[:limit]
        ],
    )


@app.get("/graph/{session_id}/stats", response_model=GraphStats)
def graph_stats(session_id: str, user: dict | None = Depends(current_user)):
    session = _require_session(session_id, user)
    g = get_graph(session_id, _current_version(session), session.current_df)

    nodes_by_type: dict[str, int] = {}
    for _, attrs in g.nodes(data=True):
        t = attrs.get("type", "Unknown")
        nodes_by_type[t] = nodes_by_type.get(t, 0) + 1

    edges_by_relation: dict[str, int] = {}
    for _, _, data in g.edges(data=True):
        r = data.get("relation", "UNKNOWN")
        edges_by_relation[r] = edges_by_relation.get(r, 0) + 1

    ad_counts = []
    for node_id, attrs in g.nodes(data=True):
        if attrs.get("type") != "Advertiser":
            continue
        n_ads = sum(1 for _, _, d in g.out_edges(node_id, data=True) if d.get("relation") == "RAN_AD")
        ad_counts.append({"id": node_id, "name": attrs.get("name"), "ad_count": n_ads})
    ad_counts.sort(key=lambda x: x["ad_count"], reverse=True)

    return GraphStats(
        node_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
        nodes_by_type=nodes_by_type,
        edges_by_relation=edges_by_relation,
        top_advertisers=ad_counts[:15],
    )


@app.get("/graph/{session_id}/search")
def graph_search(session_id: str, q: str, limit: int = Query(20, ge=1, le=100), user: dict | None = Depends(current_user)):
    session = _require_session(session_id, user)
    g = get_graph(session_id, _current_version(session), session.current_df)
    needle = q.strip().lower()
    hits = []
    for node_id, attrs in g.nodes(data=True):
        name = str(attrs.get("name", ""))
        if needle in name.lower():
            hits.append({
                "id": node_id,
                "label": name,
                "type": attrs.get("type", "Unknown"),
                "degree": g.degree(node_id),
            })
            if len(hits) >= limit * 4:
                break
    # Most-connected first: for a partial name match, the hub is almost
    # always the one the user meant.
    hits.sort(key=lambda h: h["degree"], reverse=True)
    return {"results": hits[:limit]}


@app.get("/graph/{session_id}/neighborhood", response_model=GraphView)
def graph_neighborhood(
    session_id: str,
    node: str = Query(..., description="Node id, e.g. 'Advertiser::Sakal Media Group'."),
    depth: int = Query(1, ge=1, le=3),
    max_nodes: int = Query(60, ge=5, le=200),
    user: dict | None = Depends(current_user),
):
    """The subgraph around one node, collapsed for display.

    Two things happen here that matter for it being readable rather than
    a hairball:

    1. Parallel RAN_AD edges are collapsed into ONE edge carrying a
       `weight`. In the raw MultiDiGraph an advertiser that ran 400 ads
       in one publication has 400 separate edges; drawn literally that is
       400 overlapping lines conveying one fact. Weight conveys the same
       fact as line thickness.
    2. Expansion is breadth-first and capped. Depth 2 from a hub
       advertiser reaches thousands of nodes - past roughly 60 a node-link
       diagram stops communicating anything, so the cap is enforced here
       rather than shipping a graph the browser has to discard.
    """
    session = _require_session(session_id, user)
    g = get_graph(session_id, _current_version(session), session.current_df)

    if node not in g:
        raise HTTPException(status_code=404, detail=f"Node '{node}' not in graph.")

    # Undirected BFS - relationships are meaningful in both directions
    # here (you want a Category's advertisers as readily as an
    # advertiser's categories).
    seen = {node}
    frontier = [node]
    truncated = False
    for _ in range(depth):
        next_frontier = []
        for current in frontier:
            neighbors = set(g.successors(current)) | set(g.predecessors(current))
            for nbr in neighbors:
                if nbr in seen:
                    continue
                if len(seen) >= max_nodes:
                    truncated = True
                    break
                seen.add(nbr)
                next_frontier.append(nbr)
            if truncated:
                break
        if truncated:
            break
        frontier = next_frontier

    nodes = [
        GraphNode(
            id=n,
            label=str(g.nodes[n].get("name", n)),
            type=g.nodes[n].get("type", "Unknown"),
            degree=g.degree(n),
        )
        for n in seen
    ]

    collapsed: dict[tuple[str, str, str], int] = {}
    for u, v, data in g.edges(data=True):
        if u not in seen or v not in seen:
            continue
        key = (u, v, data.get("relation", "UNKNOWN"))
        collapsed[key] = collapsed.get(key, 0) + 1

    edges = [
        GraphEdge(source=u, target=v, relation=rel, weight=w)
        for (u, v, rel), w in collapsed.items()
    ]

    return GraphView(center=node, nodes=nodes, edges=edges, truncated=truncated)


@app.get("/diff/{session_id}/{version}", response_model=DiffResponse)
def get_diff(session_id: str, version: int, user: dict | None = Depends(current_user)):
    """Every cell changed by the edit that produced `version`.

    Version 0 is the original upload, so it has no predecessor to diff
    against and returns an empty change set rather than an error - the UI
    can ask for the diff of whatever version it's on without special-casing.
    """
    session = _require_session(session_id, user)
    if version < 0 or version >= len(session.versions):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid version {version}; valid range 0-{len(session.versions) - 1}",
        )

    if version == 0:
        return DiffResponse(
            session_id=session_id, from_version=0, to_version=0,
            changed_cells=[], changed_cell_count=0, changed_row_count=0,
            added_columns=[], removed_columns=[], truncated=False,
        )

    result = diff_versions(session.versions[version - 1], session.versions[version])
    return DiffResponse(session_id=session_id, from_version=version - 1, to_version=version, **result)


# --------------------------------------------------------------------------
# agent + versioning
# --------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http: Request, user: dict | None = Depends(current_user)):
    session = _require_session(request.session_id, user)
    rate_limit.check("chat", http, user)

    if not settings.openrouter_api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not configured on the server.")

    version_before = _current_version(session)
    user_entry = {"role": "user", "text": request.message}

    try:
        result = run_agent_turn(
            session=session,
            user_id=user["id"] if user else None,
            user_message=request.message,
            model=settings.openrouter_model,
            api_key=settings.openrouter_api_key,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Agent turn failed: %s", e)
        session_store.save_conversation(session)
        session_store.append_transcript(session, [
            user_entry, {"role": "system", "text": f"Error: Agent call failed: {e}"},
        ])
        raise HTTPException(status_code=502, detail=f"Agent call failed: {e}") from e

    version_after = _current_version(session)
    data_changed = version_after != version_before

    # Sanitised once here so the stored transcript and the response agree.
    tool_calls = json.loads(json.dumps(result["tool_calls"], default=str))
    session_store.save_conversation(session)
    session_store.append_transcript(session, [user_entry, {
        "role": "assistant",
        "text": result["reply"],
        "toolCalls": tool_calls,
        "versionBadge": version_after if data_changed else None,
    }])

    return ChatResponse(
        reply=result["reply"],
        tool_calls=tool_calls,
        version=version_after,
        data_changed=data_changed,
    )


@app.get("/history/{session_id}", response_model=HistoryResponse)
def history(session_id: str, user: dict | None = Depends(current_user)):
    session = _require_session(session_id, user)
    return HistoryResponse(
        current_version=_current_version(session),
        total_versions=len(session.versions),
        audit_log=[
            AuditLogEntry(
                version=e.version, timestamp=e.timestamp, operation=e.operation,
                scope=e.scope, rows_affected=e.rows_affected, reason=e.reason,
                diff_preview=[{k: _json_safe(v) for k, v in d.items()} for d in e.diff_preview],
                excel=e.excel, user_id=e.user_id,
            )
            for e in session.audit_log
        ],
    )


@app.post("/columns", response_model=AddColumnResponse)
def add_column(request: AddColumnRequest, user: dict | None = Depends(current_user)):
    """Adds a column at the user's request. Goes through the same edit
    operation, versioning and audit log as the assistant's edits, so it
    shows in History and can be restored away like any other change."""
    session = _require_session(request.session_id, user)
    df = session.current_df
    args = {
        "new_column": request.name, "value": request.value,
        "source_column": request.source_column or None, "after_column": request.after_column or None,
        "formula": request.formula or None,
    }
    try:
        new_df, preview = apply_operation(df, operation="add_column", **args)
    except EditValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    name = request.name.strip()
    if request.dry_run:
        sample = [_json_safe(v) for v in new_df[name].head(5)]
        return AddColumnResponse(status="preview", column=name, current_version=_current_version(session),
                                 rows_affected=0, preview=sample)

    filled = bool(args["source_column"] or args["formula"]) or request.value not in (None, "")
    how = (f"= {args['formula']}" if args["formula"]
           else f"copy of {args['source_column']}" if args["source_column"]
           else f"filled with '{request.value}'" if filled else "empty")
    excel = excel_formulas.for_edit("add_column", args, df, new_df)
    try:
        entry = session_store.apply_edit(
            session_id=session.session_id, new_df=new_df, operation="add_column", scope=name,
            rows_affected=len(new_df) if filled else 0,
            reason=request.reason or f"Added column {name} ({how})",
            diff_preview=preview, excel=excel, user_id=user["id"] if user else None,
        )
    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return AddColumnResponse(status="added", column=name, current_version=entry.version,
                             rows_affected=entry.rows_affected, excel=excel)


@app.post("/revert", response_model=RevertResponse)
def revert(request: RevertRequest, user: dict | None = Depends(current_user)):
    """Makes an earlier version current again, as a new version.

    Nothing after `to_version` is deleted - restoring v1 from v3 produces
    v4, whose data equals v1's, and v2 and v3 stay in the history with
    their audit entries. The audit log is the record that makes agent
    edits trustworthy, so undoing an edit must not erase that record.
    Because version numbers only ever grow, cached graphs stay valid.
    """
    session = _require_session(request.session_id, user)
    current = _current_version(session)
    if request.to_version < 0 or request.to_version >= current:
        detail = (f"v{request.to_version} is already the current version."
                  if request.to_version == current
                  else f"Invalid version {request.to_version}; valid range 0-{current - 1}")
        raise HTTPException(status_code=400, detail=detail)

    delta = diff_versions(session.current_df, session.versions[request.to_version])
    preview = [
        {"row": c["row"], "column": c["column"], "before": c["before"], "after": c["after"]}
        for c in delta["changed_cells"][:5]
    ]
    try:
        entry = session_store.restore(
            request.session_id, request.to_version,
            rows_affected=delta["changed_row_count"], diff_preview=preview,
            user_id=user["id"] if user else None,
        )
    except (ValueError, VersionConflictError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return RevertResponse(
        status="restored",
        restored_from=request.to_version,
        current_version=entry.version,
        rows_affected=entry.rows_affected,
    )
