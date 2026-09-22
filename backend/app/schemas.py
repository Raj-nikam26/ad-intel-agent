"""schemas.py - API request/response contracts."""

from pydantic import BaseModel
from typing import Any


class ColumnMeta(BaseModel):
    """Per-column metadata the IDE needs to render a column well.

    `blank_means` is the important one: it carries the domain semantics
    (e.g. IsHouseAd blank = "not a house ad") through to the UI, so the
    grid can render those blanks as ordinary values instead of painting
    them as missing-data gaps. Without this the UI would visually
    contradict the diagnostics layer, which deliberately does not flag
    them.
    """
    name: str
    dtype: str
    missing_count: int
    blank_means: str | None = None
    is_gap_checked: bool = False


class UploadResponse(BaseModel):
    """Returned on upload, and again when a saved session is reopened -
    which is why it carries the current version and the chat so far."""
    session_id: str
    filename: str
    row_count: int
    column_count: int
    columns: list[str]
    column_meta: list[ColumnMeta]
    preview: list[dict[str, Any]]
    current_version: int = 0
    transcript: list[dict[str, Any]] = []
    notice: str | None = None   # e.g. where the table was found in the sheet


class DataPage(BaseModel):
    """A window onto the current version of the table."""
    session_id: str
    version: int
    offset: int
    limit: int
    total_rows: int
    filtered_rows: int
    columns: list[str]
    rows: list[dict[str, Any]]


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict[str, Any]]
    # Lets the IDE know whether this turn changed the data, so the grid
    # can refresh and highlight exactly what moved without polling.
    version: int
    data_changed: bool


class AuditLogEntry(BaseModel):
    version: int
    timestamp: float
    operation: str
    scope: str
    rows_affected: int
    reason: str
    diff_preview: list[dict[str, Any]]
    excel: dict[str, Any] | None = None
    user_id: str | None = None


class HistoryResponse(BaseModel):
    current_version: int
    total_versions: int
    audit_log: list[AuditLogEntry]


class RevertRequest(BaseModel):
    session_id: str
    to_version: int


class AddColumnRequest(BaseModel):
    session_id: str
    name: str
    value: str | None = None           # fill every row with this value
    source_column: str | None = None   # or copy this column
    after_column: str | None = None    # position; default is the end
    formula: str | None = None         # or calculate it, e.g. 2*([Width]+[Height])
    reason: str | None = None
    dry_run: bool = False              # validate and preview only; nothing is saved


class AddColumnResponse(BaseModel):
    status: str
    column: str
    current_version: int
    rows_affected: int
    excel: dict[str, Any] | None = None
    preview: list[Any] = []


class RevertResponse(BaseModel):
    status: str
    restored_from: int
    current_version: int
    rows_affected: int


class IssueOut(BaseModel):
    issue_type: str
    scope: str
    description: str
    row_indices: list[int]
    total_rows_affected: int
    sample: list[Any]


class IssuesResponse(BaseModel):
    session_id: str
    version: int
    total_issues: int
    counts_by_type: dict[str, int]
    issues: list[IssueOut]


class GraphStats(BaseModel):
    node_count: int
    edge_count: int
    nodes_by_type: dict[str, int]
    edges_by_relation: dict[str, int]
    top_advertisers: list[dict[str, Any]]


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    degree: int


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: int


class GraphView(BaseModel):
    center: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class DiffResponse(BaseModel):
    session_id: str
    from_version: int
    to_version: int
    changed_cells: list[dict[str, Any]]
    changed_cell_count: int
    changed_row_count: int
    added_columns: list[str]
    removed_columns: list[str]
    truncated: bool


class MappingResponse(BaseModel):
    """What the app worked out about this file's columns, and what the
    user can change about it."""
    session_id: str
    subject: str | None
    entities: list[str]
    measures: list[str]
    dates: list[str]
    flags: dict[str, str]
    roles: dict[str, str]
    columns: list[dict[str, Any]]


class MappingRequest(BaseModel):
    subject: str | None = None
    entities: list[str] | None = None
    flags: list[str] | None = None
