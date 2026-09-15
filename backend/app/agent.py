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
from app.graph_builder import build_graph, advertiser_summary, advertisers_by_category_and_office
from app.safe_editor import apply_operation, EditValidationError
from app.safe_executor import run_expression, UnsafeExpressionError, ExecutionError
from app.data_store import session_store, Session, VersionConflictError

# Tool results carry their Excel equivalent under this key. It is for the
# UI, so it is removed before the result is sent back to the model.
EXCEL_KEY = "_excel"

logger = logging.getLogger("ad_intel.agent")

SYSTEM_PROMPT = """You are an assistant for an ad-tracking dataset (newspaper \
ad insertions: advertiser, publication, category, location, size, etc). \
The data is NOT pre-cleaned - report issues honestly rather than assuming \
the data should look a certain way.

You have tools to: check for data-quality issues (never fixes anything), \
answer relational questions using a graph of advertisers/publications/\
categories/locations, answer flat filter/aggregate questions on the table, \
and apply a specific, scoped edit ONLY when the user explicitly asks you to \
fix/change/update something.

Rules:
- Never call apply_edit unless the user has explicitly asked for a change \
  in this message or the immediately preceding one.
- When calling apply_edit, use row_indices and column values that came from \
  a prior detect_issues or query result in this conversation - never invent them.
- Always explain what you found or what you changed in plain language after \
  a tool call, don't just show raw tool output.
- When calling tabular_query, also supply excel_formula: a single Excel \
  formula giving the same result on the user's sheet, using the column \
  letters and row range from the sheet layout below. Leave it empty if \
  there is no sensible single-formula equivalent.
"""

TOOL_DEFINITIONS = [
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
            "name": "get_advertiser_summary",
            "description": "Get a graph-based summary of one advertiser: publications used, categories, editions, locations, sales offices, house-ad count. Use for questions about a specific advertiser's overall activity.",
            "parameters": {
                "type": "object",
                "properties": {"advertiser": {"type": "string"}},
                "required": ["advertiser"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_advertisers_by_category_and_office",
            "description": "Find advertisers serviced by a given sales office that also advertised in a given category. Use for multi-hop relational questions joining sales office and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "sales_office": {"type": "string"},
                },
                "required": ["category", "sales_office"],
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
                    "operation": {"type": "string", "enum": ["fill_missing_value", "fill_missing_value_bulk", "standardize_value", "flag_rows"]},
                    "column": {"type": "string"},
                    "row_indices": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Required for fill_missing_value/standardize_value/flag_rows. NOT used for fill_missing_value_bulk, which fixes every missing row in the column regardless of what was shown earlier.",
                    },
                    "value": {"type": "string", "description": "For fill_missing_value/standardize_value: the new value. For flag_rows: the flag value."},
                    "flag_column": {"type": "string", "description": "Only for flag_rows: name of the flag column."},
                    "reason": {"type": "string", "description": "One-line summary of why, for the audit log."},
                },
                "required": ["operation", "reason"],
            },
        },
    },
]


def execute_tool_call(name: str, arguments: dict, session: Session) -> dict:
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

    if name == "get_advertiser_summary":
        g = build_graph(df)
        result = advertiser_summary(g, arguments["advertiser"])
        return result or {"error": f"Advertiser '{arguments['advertiser']}' not found in graph."}

    if name == "find_advertisers_by_category_and_office":
        g = build_graph(df)
        result = advertisers_by_category_and_office(g, arguments["category"], arguments["sales_office"])
        return {"advertisers": result, "count": len(result)}

    if name == "tabular_query":
        try:
            result = run_expression(arguments["expression"], df)
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
            if operation == "flag_rows":
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


def run_agent_turn(session: Session, user_message: str, model: str, api_key: str) -> dict:
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
            result = execute_tool_call(tc.function.name, args, session)

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
