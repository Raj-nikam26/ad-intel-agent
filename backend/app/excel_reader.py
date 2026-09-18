"""
excel_reader.py
---------------
Finds the table inside a workbook.

Real workbooks rarely start at A1. A report often has a title and a date
above the table, a blank margin column or two on the left, and the
column headings on row 3 or 4. Reading such a sheet with the headings
assumed to be on row 1 produces columns named "Unnamed: 0", the title
as a heading, and the real headings as the first data row.

This module locates the table and reads only it:

  1. Use the first sheet that has any data (cover sheets are skipped).
  2. Find the header row: the first row that is about as wide as the
     table and consists of distinct text labels. A title on its own
     line, or a line of notes, is too narrow to qualify.
  3. Read from that row, drop the empty margin columns and completely
     empty rows, and name any heading-less column after its Excel
     letter ("Column D") rather than "Unnamed: 3".

Nothing inside the table is changed: values, blanks and types are kept
exactly as they are in the file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd

SCAN_ROWS = 30          # how far down to look for the header row
MIN_WIDTH_SHARE = 0.5   # header must fill at least half the table's width
MIN_TEXT_SHARE = 0.8    # and be mostly text


@dataclass
class TableLocation:
    sheet: str
    header_row: int      # 1-based Excel row of the headings
    first_column: str    # Excel letter of the first table column
    first_sheet: bool = True

    @property
    def moved(self) -> bool:
        """True when the table is not simply A1 of the first sheet."""
        return self.origin != "A1" or not self.first_sheet

    @property
    def origin(self) -> str:
        return f"{self.first_column}{self.header_row}"


def col_letter(index: int) -> str:
    s = ""
    n = index + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_blank(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(v, str) and v.strip() == ""


def _is_text(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        float(v.replace(",", ""))
        return False
    except ValueError:
        return True


def find_header_row(raw: pd.DataFrame) -> int:
    """Index (0-based, within `raw`) of the header row. 0 when unsure."""
    counts = [sum(not _is_blank(v) for v in row) for row in raw.itertuples(index=False)]
    width = max(counts, default=0)
    if width <= 1:
        return 0
    for i in range(min(SCAN_ROWS, len(raw))):
        if counts[i] < max(2, width * MIN_WIDTH_SHARE):
            continue                      # a title, a note or an empty line
        values = [v for v in raw.iloc[i] if not _is_blank(v)]
        texts = [str(v).strip() for v in values if _is_text(v)]
        if len(texts) < len(values) * MIN_TEXT_SHARE:
            continue                      # a data row, not headings
        if len(set(t.lower() for t in texts)) < len(texts):
            continue                      # repeated labels: more likely data
        # A header needs something under it.
        if i + 1 < len(raw) and not any(not _is_blank(v) for v in raw.iloc[i + 1:].stack()):
            continue
        return i
    return 0


def _first_sheet_with_data(book: pd.ExcelFile) -> tuple[str, pd.DataFrame]:
    for name in book.sheet_names:
        raw = book.parse(name, header=None, nrows=SCAN_ROWS + 20)
        if raw.notna().any().any():
            return name, raw
    raise ValueError("The workbook has no data on any sheet.")


def read_table(contents: bytes) -> tuple[pd.DataFrame, TableLocation]:
    book = pd.ExcelFile(io.BytesIO(contents))
    sheet, raw = _first_sheet_with_data(book)

    # Leading empty rows are skipped by position so the header search and
    # the final read agree on row numbers.
    header_idx = find_header_row(raw)

    df = book.parse(sheet, header=header_idx)

    # Margin columns: no heading and nothing in them.
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    empty_margin = [c for c in unnamed if df[c].isna().all()]
    positions = {c: i for i, c in enumerate(df.columns)}
    first_col = min((positions[c] for c in df.columns if c not in empty_margin), default=0)
    df = df.drop(columns=empty_margin)

    # Columns with data but no heading get their Excel letter as a name.
    renames = {}
    for c in df.columns:
        if str(c).startswith("Unnamed:"):
            name = f"Column {col_letter(positions[c])}"
            while name in df.columns or name in renames.values():
                name += "_"
            renames[c] = name
    df = df.rename(columns=renames)
    # Headings can be numbers or dates (a "2024" column); names are text
    # everywhere else in the app, and must stay unique.
    names: list[str] = []
    for c in df.columns:
        name = str(c).strip() or "Column"
        while name in names:
            name += "_"
        names.append(name)
    df.columns = names

    # Rows with nothing in them carry no data (spacer lines, the gap
    # between a table and a totals block). Everything else is kept.
    df = df.dropna(how="all").reset_index(drop=True)

    # pandas counts header_idx over the rows it read, which excludes
    # nothing - so the Excel row is simply index + 1.
    location = TableLocation(sheet=sheet, header_row=header_idx + 1, first_column=col_letter(first_col),
                             first_sheet=sheet == book.sheet_names[0])
    return df, location
