"""Reads a CSV or XLSX of recipe names into rows (pure apart from opening the file).

Recognised header cells, case-insensitive: `name` (also `recipe`, `title`, `rezept`), `url`,
`language`, `notes`, `cuisine`. A sheet with no header and one column is a plain list of names.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_HEADERS = ("name", "recipe", "title", "rezept")
OTHER_HEADERS = ("url", "language", "notes", "cuisine")
ACCEPTED_HEADERS = ", ".join(NAME_HEADERS)
# German spellings (a German Excel) map onto the same optional columns.
HEADER_ALIASES = {
    "link": "url",
    "sprache": "language",
    "notizen": "notes",
    "notiz": "notes",
    "küche": "cuisine",
    "kueche": "cuisine",
}
LANGUAGES = {
    "en": "en",
    "english": "en",
    "de": "de",
    "german": "de",
    "deutsch": "de",
    "ur": "ur",
    "urdu": "ur",
    "hi": "hi",
    "hindi": "hi",
}
DELIMITERS = (",", ";", "\t")


class SheetError(Exception):
    """The file cannot be used; the message says why and what to do."""


@dataclass(frozen=True)
class SheetRow:
    row_number: int  # the row as the user sees it in Excel (the header is row 1)
    name: str
    url: str | None = None
    language: str | None = None
    notes: str | None = None
    cuisine: str | None = None


@dataclass
class ParsedSheet:
    rows: list[SheetRow] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)  # names repeated within the sheet
    warnings: list[str] = field(default_factory=list)


def normalize_name(name: str) -> str:
    """Case-, space- and punctuation-insensitive identity of a recipe name."""
    return " ".join(re.sub(r"[^\w\s]", " ", name.casefold()).split())


def normalize_url(url: str) -> str:
    cleaned = url.strip().split("#")[0].rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", cleaned, flags=re.IGNORECASE).casefold()


def parse_cells(grid: list[list[str]]) -> ParsedSheet:
    """Turns rows of cell text into `SheetRow`s; row numbers count from 1 over the original grid."""
    numbered = [(i, [c.strip() for c in row]) for i, row in enumerate(grid, start=1)]
    first = next(((i, row) for i, row in numbered if any(row)), None)
    if first is None:
        raise SheetError("the sheet is empty")
    first_index, first_row = first
    headers = [HEADER_ALIASES.get(c.casefold(), c.casefold()) for c in first_row]
    result = ParsedSheet()

    columns: dict[str, int]
    if any(h in NAME_HEADERS for h in headers):
        columns = {h: n for n, h in reversed(list(enumerate(headers))) if h}
        name_col = next(columns[h] for h in NAME_HEADERS if h in columns)
        body = [(i, row) for i, row in numbered if i > first_index]
    elif any(h in OTHER_HEADERS for h in headers) or max(len(r) for _, r in numbered) > 1:
        raise SheetError(
            f"no name column found. Put a header row first with one of: {ACCEPTED_HEADERS} "
            "(optional columns: url, language, notes, cuisine)"
        )
    else:  # a plain, headerless list of names
        columns, name_col = {}, 0
        body = [(i, row) for i, row in numbered if i >= first_index]

    def cell(row: list[str], header: str) -> str | None:
        n = columns.get(header)
        return row[n] if n is not None and n < len(row) and row[n] else None

    seen: set[str] = set()
    for index, row in body:
        if not any(row) or (row and row[0].startswith("#")):
            continue
        name = row[name_col] if name_col < len(row) else ""
        if not name:
            result.warnings.append(f"row {index}: no name, skipped")
            continue
        if name.startswith("#"):
            continue
        key = normalize_name(name)
        if key in seen:
            result.duplicates.append(name)
            continue
        seen.add(key)
        url, language = cell(row, "url"), cell(row, "language")
        if url and not re.match(r"https?://", url, re.IGNORECASE):
            result.warnings.append(f"row {index}: {url!r} is not an http(s) URL, ignored")
            url = None
        if language:
            normalized = LANGUAGES.get(language.casefold())
            if normalized is None:
                result.warnings.append(
                    f"row {index}: unknown language {language!r}, ignored (use en, de, ur, hi)"
                )
            language = normalized
        result.rows.append(SheetRow(index, name, url, language, cell(row, "notes"), cell(row, "cuisine")))
    return result


def _split_csv(text: str) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    sample = lines[:5] or [""]

    def width(delimiter: str) -> int:
        return max((len(next(csv.reader([ln], delimiter=delimiter))) for ln in sample), default=1)

    delimiter = max(DELIMITERS, key=lambda d: (width(d), d == ","))  # ties go to the comma
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def read_grid(path: Path, sheet: str | None = None) -> list[list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise SheetError(
            f"{path.name} is an old .xls file, which is not supported: save it as .xlsx or .csv and try again"
        )
    if suffix == ".xlsx":
        return _read_xlsx(path, sheet)
    if suffix in (".csv", ".tsv", ".txt"):
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise SheetError(f"{path.name} is not UTF-8: save it as 'CSV UTF-8' from Excel") from err
        return _split_csv(text)
    raise SheetError(f"{path.name}: unsupported file type {suffix!r}. Use .xlsx or .csv")


def _read_xlsx(path: Path, sheet: str | None) -> list[list[str]]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as err:  # openpyxl raises many types for a corrupt or non-xlsx file
        raise SheetError(f"cannot read {path.name} as an Excel file: {err}") from err
    try:
        if sheet is not None and sheet not in workbook.sheetnames:
            names = ", ".join(workbook.sheetnames)
            raise SheetError(f"no sheet named {sheet!r}. Sheets in the file: {names}")
        worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
        return [["" if v is None else str(v) for v in row] for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def read_sheet(path: Path, sheet: str | None = None) -> ParsedSheet:
    return parse_cells(read_grid(path, sheet))
