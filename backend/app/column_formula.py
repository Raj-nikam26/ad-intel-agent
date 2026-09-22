"""
column_formula.py
-----------------
Calculated columns from a small, Excel-like formula language, e.g.

    2 * ([Width] + [Height])          perimeter
    ROUND([Revenue] / [Units], 2)     price per unit
    [First name] & " " & [Last name]  joined text

This is not eval. The formula is parsed into a syntax tree and only the
node types below are accepted; anything else - attribute access,
subscripts, lambdas, comprehensions, names that are not columns, any
function outside the list - is refused before evaluation. Evaluation
walks the tree itself over whole columns, so there is no code for a
model or a user to inject.

    column reference   [Any column name]  or  Name  (single word)
    numbers, "text"
    + - * /  ^ (power)  & (join text)  unary -
    ROUND(x, n)  ABS(x)  MIN(a, b, ...)  MAX(a, b, ...)  SQRT(x)  MOD(a, b)

Numbers are read from each column as numbers; a blank or non-numeric
cell makes that row's result blank rather than raising, and so does
division by zero. The same tree is printed back as an Excel formula for
row 2, so the user can reproduce the column in their own file.
"""

from __future__ import annotations

import ast
import re

import numpy as np
import pandas as pd

MAX_LENGTH = 300
MAX_NODES = 120

FUNCTIONS = {"ROUND", "ABS", "MIN", "MAX", "SQRT", "MOD"}
_BRACKET = re.compile(r"\[([^\[\]]+)\]")


class FormulaError(ValueError):
    pass


def _prepare(formula: str, columns: list[str]) -> tuple[ast.Expression, dict[str, str]]:
    text = (formula or "").strip()
    if text.startswith("="):
        text = text[1:].strip()
    if not text:
        raise FormulaError("The formula is empty.")
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"Formulas are limited to {MAX_LENGTH} characters.")

    by_lower = {str(c).strip().lower(): c for c in columns}
    refs: dict[str, str] = {}

    def bracket(m: re.Match) -> str:
        name = m.group(1).strip()
        col = by_lower.get(name.lower())
        if col is None:
            raise FormulaError(f"There is no column named '{name}'.")
        key = f"__col{len(refs)}"
        refs[key] = col
        return key

    text = _BRACKET.sub(bracket, text)
    # Excel spells power as ^; in Python ^ is XOR, so parse it as **.
    text = text.replace("^", "**")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise FormulaError("The formula could not be read. Check brackets, quotes and operators.") from e

    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise FormulaError("The formula is too long.")

    # Bare single-word names must be columns (function names in a call
    # position are checked separately in _check).
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in refs:
            if id(node) in called:
                continue
            col = by_lower.get(node.id.lower())
            if col is None:
                raise FormulaError(
                    f"'{node.id}' is not a column. Put column names with spaces in square brackets, "
                    f"like [Unit price].")
            refs[node.id] = col
    return tree, refs


_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Call, ast.Load,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.BitAnd, ast.USub, ast.UAdd)


def _check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise FormulaError(f"'{type(node).__name__}' is not allowed in a column formula.")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str)):
            raise FormulaError("Only numbers and text can be used as values.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id.upper() not in FUNCTIONS:
                raise FormulaError(f"Allowed functions: {', '.join(sorted(FUNCTIONS))}.")
            if node.keywords:
                raise FormulaError("Functions take plain arguments only.")


def _num(x, index):
    if isinstance(x, pd.Series):
        return pd.to_numeric(x, errors="coerce").astype(float)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return pd.Series(np.nan, index=index)
    return float(x)


def _text(x, index):
    if isinstance(x, pd.Series):
        def fmt(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return ""
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            return str(v)
        return x.map(fmt)
    return pd.Series("" if x is None else str(x), index=index)


def _eval(node, df: pd.DataFrame, refs: dict[str, str]):
    idx = df.index
    if isinstance(node, ast.Expression):
        return _eval(node.body, df, refs)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return df[refs[node.id]]
    if isinstance(node, ast.UnaryOp):
        v = _num(_eval(node.operand, df, refs), idx)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, df, refs), _eval(node.right, df, refs)
        if isinstance(node.op, ast.BitAnd):
            return _text(left, idx) + _text(right, idx)
        a, b = _num(left, idx), _num(right, idx)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            with np.errstate(divide="ignore", invalid="ignore"):
                return a / b
        if isinstance(node.op, ast.Pow):
            with np.errstate(over="ignore", invalid="ignore"):
                return a ** b
    if isinstance(node, ast.Call):
        name = node.func.id.upper()
        args = [_eval(a, df, refs) for a in node.args]
        nums = [_num(a, idx) for a in args]
        need = {"ROUND": (1, 2), "ABS": (1, 1), "SQRT": (1, 1), "MOD": (2, 2), "MIN": (1, 30), "MAX": (1, 30)}[name]
        if not need[0] <= len(args) <= need[1]:
            raise FormulaError(f"{name} takes {need[0]}" + (f" to {need[1]}" if need[1] != need[0] else "")
                               + " argument(s).")
        if name == "ROUND":
            digits = int(args[1]) if len(args) > 1 and not isinstance(args[1], pd.Series) else 0
            return pd.Series(nums[0], index=idx).round(digits)
        if name == "ABS":
            return abs(nums[0])
        if name == "SQRT":
            with np.errstate(invalid="ignore"):
                return np.sqrt(pd.Series(nums[0], index=idx).where(lambda s: s >= 0))
        if name == "MOD":
            with np.errstate(divide="ignore", invalid="ignore"):
                return pd.Series(nums[0], index=idx) % nums[1]
        frame = pd.concat([pd.Series(n, index=idx) for n in nums], axis=1)
        return frame.min(axis=1, skipna=False) if name == "MIN" else frame.max(axis=1, skipna=False)
    raise FormulaError("Unsupported formula.")


def evaluate(formula: str, df: pd.DataFrame) -> pd.Series:
    """The new column's values, one per row, blank where not computable."""
    tree, refs = _prepare(formula, list(df.columns))
    _check(tree)
    result = _eval(tree, df, refs)
    if not isinstance(result, pd.Series):
        result = pd.Series([result] * len(df), index=df.index)
    if pd.api.types.is_float_dtype(result):
        result = result.replace([np.inf, -np.inf], np.nan)
        # Whole-number results (2 * (3 + 4)) read better as integers.
        finite = result.dropna()
        if len(finite) and (finite % 1 == 0).all():
            result = result.astype("Int64").astype(object).where(result.notna(), None)
    return result


# ------------------------------------------------------------------ Excel form

_PREC = {ast.BitAnd: 1, ast.Add: 2, ast.Sub: 2, ast.Mult: 3, ast.Div: 3, ast.Pow: 5}
_SYM = {ast.BitAnd: "&", ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "^"}


def to_excel(formula: str, df_after: pd.DataFrame, letter_of) -> str:
    """The formula for row 2 of the sheet, with columns as cell references.
    `letter_of(column)` gives the column's letter in the updated table."""
    tree, refs = _prepare(formula, [c for c in df_after.columns])
    _check(tree)

    def show(node, parent_prec=0, right=False) -> str:
        if isinstance(node, ast.Expression):
            return show(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return '"' + node.value.replace('"', '""') + '"'
            return repr(node.value)
        if isinstance(node, ast.Name):
            return f"{letter_of(refs[node.id])}2"
        if isinstance(node, ast.UnaryOp):
            inner = show(node.operand, 4)
            return f"-{inner}" if isinstance(node.op, ast.USub) else inner
        if isinstance(node, ast.BinOp):
            p = _PREC[type(node.op)]
            text = f"{show(node.left, p)}{_SYM[type(node.op)]}{show(node.right, p, right=True)}"
            return f"({text})" if p < parent_prec or (right and p == parent_prec) else text
        if isinstance(node, ast.Call):
            return f"{node.func.id.upper()}({','.join(show(a) for a in node.args)})"
        raise FormulaError("Unsupported formula.")

    return "=" + show(tree)
