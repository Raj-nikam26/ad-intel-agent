"""
agent.py
--------
The conversational orchestrator. This is what makes the tool "an
agent" rather than a single-shot query box: it keeps per-session
conversation history, and on each user message it lets the LLM decide
which underlying capability (or none) is needed, via OpenAI-style
function/tool calling against OpenRouter.

Tool design philosophy: the LLM never writes execution code (compare
safe_executor.py / safe_editor.py, where that's true for reads too now
that edits exist). It only ever picks a NAMED tool and fills in typed
arguments. This is what lets "what's the issue with X" -> "fix it" work
across two turns: the second message doesn't need to re-describe the
problem, because TOOL_DEFINITIONS + conversation history give the model
enough to call apply_edit with the right column/row_indices, which the
dispatcher below then validates before doing anything.

Flow per user message:
  1. Append user message to session history.
  2. Call the LLM with the full history + tool definitions.
  3. If it requests a tool call, execute it via execute_tool_call()
     (pure, deterministic, independently testable - see
     tests/test_agent_dispatch.py) and feed the result back to the LLM.
  4. Repeat until the LLM returns a plain text answer (no more tool
     calls), then return that to the caller along with a structured
     record of what tools ran, for the UI to show ("Generated query:
     ...", "Edit applied: ...").

Note: the LLM round-trip itself (steps 2-4) cannot be exercised without
a live OPENROUTER_API_KEY, same limitation as query_engine.py in the
earlier version of this project. execute_tool_call() - the part that
actually touches data - is fully unit-testable and tested without any
LLM call (see tests/test_agent_dispatch.py).
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from app import excel_formulas
from app.diagnostics import run_full_diagnostics, run_scoped_diagnostics, Issue
from app import graph_backend
from app.safe_editor import apply_operation, EditValidationError
from app.isolated_exec import run_isolated
from app.safe_executor import UnsafeExpressionError, ExecutionError
from app.data_store import session_store, Session, VersionConflictError

# Tool results carry their Excel equivalent under this key. It is for the
# UI, so it is removed before the result is sent back to the model.
EXCEL_KEY = "_excel"

logger = logging.getLogger("ad_intel.agent")

SYSTEM_PROMPT = """You are an assistant for a spreadsheet the user has uploaded. The data is NOT pre-cleaned - report what you find honestly rather than assuming the data should look a certain way.

You have tools to: check for data-quality issues (never changes anything), answer relational questions using a knowledge graph built from the file's columns, answer flat filter/aggregate questions on the table, and apply a specific, scoped edit ONLY when the user explicitly asks you to fix, change or update something.

Rules:
- To create a new column - including a calculated one such as "perimeter from width and height" - call apply_edit with operation add_column and a formula, e.g. 2*([Width]+[Height]). Do not compute it with tabular_query: that only answers, it does not save a column.
- Never call apply_edit unless the user has explicitly asked for a change   in this message or the immediately preceding one.
- When calling apply_edit, use row_indices and column values that came from   a prior detect_issues or query result in this conversation - never invent them.
- Always explain what you found or what you changed in plain language after   a tool call, don't just show raw tool output.
- Graph tools need exact stored values. If the user's wording might differ   (case, spelling, partial), call resolve_entity first and use the best match.
- Answer graph questions only from what the graph tools return.
- When calling tabular_query, also supply excel_formula: a single Excel   formula giving the same result on the user's sheet, using the column   letters and row range from the sheet layout below. Leave it empty if   there is no sensible single-formula equivalent.
"""


def schema_note(session: Session) -> str:
    """Tells the model what this particular file contains, so the same
    tools work whatever was uploaded."""
    from app.schema_profile import infer_mapping

    if session.mapping is None:
        session.mapping = infer_mapping(session.current_df)
    m = session.mapping
    parts = [f"This file is '{session.filename}' with {len(session.current_df):,} rows."]
    if m.get("subject"):
        parts.append(f"Each row is mainly about '{m['subject']}' - that is the subject of graph questions.")
    if m.get("entities"):
        parts.append("Attributes linked in the graph: " + ", ".join(m["entities"]) + ".")
    if m.get("measures"):
        parts.append("Numeric columns: " + ", ".join(m["measures"]) + ".")
    if m.get("flags"):
        parts.append("Columns where a blank means 'no', not missing data: " + ", ".join(m["flags"]) + ".")
    return " ".join(parts)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_entity",
            "description": "Find the exact name of an advertiser, publication, category, sub-category, location or sales office in the knowledge graph from a partial or misspelled name. Call this before a graph tool whenever the user's wording may not match a stored name exactly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The name as the user wrote it."},
                    "entity_type": {
                        "type": "string",
                        "enum": ["Advertiser", "Publication", "Category", "SubCategory", "Location", "SalesOffice"],
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_issues",
            "description": "Detect data-quality issues (missing values, name mismatches, near-duplicate advertisers). Read-only, never modifies data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "Optional: a column name or advertiser name to scope the check to. Omit for a full check.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_summary",
            "description": "Graph summary of one subject value: how many rows it covers and its distinct values in every linked column. Use for questions about one thing's overall activity.",
            "parameters": {
                "type": "object",
                "properties": {"entity": {"type": "string", "description": "The subject value, exactly as stored."}},
                "required": ["entity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_by_attributes",
            "description": "Find subjects linked to ALL of the given column/value pairs. The values may come from different rows of the same subject. Use for multi-hop questions joining two or more attributes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "criteria": {
                        "type": "object",
                        "description": "Column name to value, e.g. {\"Category\": \"Bank/Finance\", \"AdvertiserSalesOffice\": \"PUNE\"}",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["criteria"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tabular_query",
            "description": "Answer a flat filter/aggregate question over the raw table using a pandas expression, e.g. counts, sums, simple filters not requiring relational/graph joins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A single pandas expression operating on `df`, e.g. df[df['Category']=='Fmcg']",
                    },
                    "excel_formula": {
                        "type": "string",
                        "description": "An Excel formula producing the same result on the sheet, e.g. =COUNTIFS($E$2:$E$11276,\"Fmcg\"). Empty if none fits.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_edit",
            "description": "Apply a scoped, explicit data edit. Only call this when the user has explicitly asked for a fix/change in this or the prior message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["fill_missing_value", "fill_missing_value_bulk", "standardize_value", "flag_rows", "add_column"]},
                    "column": {"type": "string"},
                    "row_indices": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Required for fill_missing_value/standardize_value/flag_rows. NOT used for fill_missing_value_bulk, which fixes every missing row in the column regardless of what was shown earlier.",
                    },
                    "value": {"type": "string", "description": "For fill_missing_value/standardize_value: the new value. For flag_rows: the flag value."},
                    "flag_column": {"type": "string", "description": "Only for flag_rows: name of the flag column."},
                    "new_column": {"type": "string", "description": "Only for add_column: name of the column to create."},
                    "source_column": {"type": "string", "description": "Only for add_column: copy this existing column's values into the new one. Omit for an empty column or a fixed value (use value)."},
                    "after_column": {"type": "string", "description": "Only for add_column: place the new column after this one. Omit to add it at the end."},
                    "formula": {"type": "string", "description": "Only for add_column: calculate the new column from other columns, Excel-style, with column names in square brackets. Operators + - * / ^ and & (join text); functions ROUND, ABS, MIN, MAX, SQRT, MOD. Examples: 2*([Width]+[Height]); ROUND([Revenue]/[Units],2); [First name] & \" \" & [Last name]."},
                    "reason": {"type": "string", "description": "One-line summary of why, for the audit log."},
                },
                "required": ["operation", "reason"],
            },
        },
    },
]


def execute_tool_call(name: str, arguments: dict, session: Session,
                      user_id: str | None = None) -> dict:
    """
    Pure dispatcher: given a tool name + arguments + the session (for its
    current dataframe / graph), runs the corresponding logic and returns
    a JSON-serializable result. No LLM involved here - fully unit
    testable in isolation (see tests/test_agent_dispatch.py).
    """
    df = session.current_df

    if name == "detect_issues":
        scope = arguments.get("scope")
        issues: list[Issue] = run_scoped_diagnostics(df, scope) if scope else run_full_diagnostics(df)
        return {
            "issue_count": len(issues),
            "issues": [
                {"type": i.issue_type, "scope": i.scope, "description": i.description,
                 "row_indices": i.row_indices[:20], "sample": i.sample}
                for i in issues[:15]
            ],
        }

    if name == "resolve_entity":
        matches = graph_backend.resolve_entity(session, arguments["text"], arguments.get("entity_type"))
        return {"matches": matches} if matches else {"matches": [], "note": "No graph entity resembles that name."}

    if name == "get_entity_summary":
        value = arguments["entity"]
        result = graph_backend.entity_summary(session, value)
        return result or {"error": f"'{value}' is not a subject in the graph. "
                                   "Use resolve_entity to find the exact name."}

    if name == "find_by_attributes":
        criteria = arguments.get("criteria") or {}
        result = graph_backend.find_by_attributes(session, criteria)
        return {"matches": result, "count": len(result), "criteria": criteria}

    if name == "tabular_query":
        try:
            result = run_isolated(arguments["expression"], df)
        except (UnsafeExpressionError, ExecutionError) as e:
            return {"error": str(e)}
        if isinstance(result, pd.DataFrame):
            return {"row_count": len(result), "rows": result.head(50).to_dict(orient="records")}
        if isinstance(result, pd.Series):
            return {"result": result.head(50).to_dict()}
        return {"result": result}

    if name == "apply_edit":
        operation = arguments["operation"]
        column = arguments.get("column")
        try:
            if operation == "add_column":
                new_df, preview = apply_operation(
                    df, operation="add_column",
                    new_column=arguments.get("new_column", ""),
                    value=arguments.get("value"),
                    source_column=arguments.get("source_column"),
                    after_column=arguments.get("after_column"),
                    formula=arguments.get("formula"),
                )
                filled = (arguments.get("source_column") or arguments.get("formula")
                          or arguments.get("value") not in (None, ""))
                rows_affected = len(df) if filled else 0
                column = arguments.get("new_column", "").strip()

            elif operation == "flag_rows":
                new_df, preview = apply_operation(
                    df, operation="flag_rows",
                    row_indices=arguments["row_indices"],
                    flag_column=arguments.get("flag_column", "review_flag"),
                    flag_value=arguments.get("value", "flagged"),
                )
                rows_affected = len(arguments["row_indices"])

            elif operation == "fill_missing_value_bulk":
                before_missing = int((df[column].isna() | (df[column].astype(str).str.strip() == "")).sum())
                new_df, preview = apply_operation(
                    df, operation="fill_missing_value_bulk",
                    column=column, value=arguments.get("value"),
                )
                rows_affected = before_missing

            elif operation == "standardize_value":
                new_df, preview = apply_operation(
                    df, operation="standardize_value",
                    column=column, row_indices=arguments["row_indices"],
                    new_value=arguments.get("value"),
                )
                rows_affected = len(arguments["row_indices"])

            else:  # fill_missing_value (scoped, explicit row list)
                new_df, preview = apply_operation(
                    df, operation="fill_missing_value",
                    column=column, row_indices=arguments["row_indices"],
                    value=arguments.get("value"),
                )
                rows_affected = len(arguments["row_indices"])

        except EditValidationError as e:
            return {"error": str(e)}
        except KeyError as e:
            return {"error": f"Missing required argument: {e}"}

        excel = excel_formulas.for_edit(operation, arguments, df, new_df)
        try:
            entry = session_store.apply_edit(
                session_id=session.session_id,
                new_df=new_df,
                operation=operation,
                scope=column or arguments.get("flag_column", ""),
                rows_affected=rows_affected,
                reason=arguments.get("reason", ""),
                diff_preview=preview,
                excel=excel,
                user_id=user_id,
            )
        except VersionConflictError as e:
            return {"error": str(e)}
        return {
            "status": "applied",
            "version": entry.version,
            "rows_affected": entry.rows_affected,
            "diff_preview": entry.diff_preview,
            EXCEL_KEY: excel,
        }

    return {"error": f"Unknown tool: {name}"}


def run_agent_turn(session: Session, user_message: str, model: str, api_key: str,
                   user_id: str | None = None) -> dict:
    """
    Runs one full agent turn: sends the message + history + tools to the
    LLM via OpenRouter, executes any requested tool calls, and loops
    until the model returns a final plain-text answer.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    if not session.conversation:
        session.conversation.append({
            "role": "system",
            "content": SYSTEM_PROMPT + "\n" + excel_formulas.sheet_layout(session.current_df),
        })
    session.conversation.append({"role": "user", "content": user_message})

    tool_calls_made = []
    max_iterations = 5  # hard cap - never loop on tool calls indefinitely

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=session.conversation,
            tools=TOOL_DEFINITIONS,
            extra_headers={"HTTP-Referer": "https://localhost", "X-Title": "Ad Intel Agent"},
        )
        message = response.choices[0].message

        if not message.tool_calls:
            session.conversation.append({"role": "assistant", "content": message.content})
            return {"reply": message.content, "tool_calls": tool_calls_made}

        session.conversation.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
        })

        for tc in message.tool_calls:
            args = json.loads(tc.function.arguments)
            logger.info("Agent invoking tool=%s args=%s", tc.function.name, args)
            df_before = session.current_df
            result = execute_tool_call(tc.function.name, args, session, user_id=user_id)

            excel = result.pop(EXCEL_KEY, None) if isinstance(result, dict) else None
            if excel is None and tc.function.name != "apply_edit":
                excel = excel_formulas.for_read(tc.function.name, df_before, args, result)

            tool_calls_made.append({
                "name": tc.function.name, "arguments": args, "result": result, "excel": excel,
            })
            session.conversation.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return {"reply": "I ran into trouble finishing that request - please try rephrasing.", "tool_calls": tool_calls_made}
