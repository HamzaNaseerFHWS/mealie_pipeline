# 26: Import a CSV or Excel list of recipe names as Recipe Requests

**What to build:** The user has a spreadsheet of recipes they want, as names rather than Video links. This is a **one-off** import. `mp requests add --file recipes.xlsx` (or `.csv`) reads it and registers one **Recipe Request** per row in the State Store. A Recipe Request is the pipeline's unit of work for "find this recipe on the web and add it to Mealie"; tickets 27 and 28 do the finding and importing. `mp requests` lists them with their status, and a results file shows what happened to each row.

**Sheet format:**
- The first row is a header. Recognised columns, case-insensitive:
  - `name` (required; `recipe`, `title` and `rezept` are also accepted)
  - `url` (optional; if present, the search is skipped and this page is used)
  - `language` (optional: `en`, `de`, `ur`/`hi`)
  - `notes` and `cuisine` (optional; shown in the report and appended to the search query as a hint)
- A sheet with no header and one column is treated as a plain list of names.
- Excel: the first worksheet, or `--sheet <name>`. CSV: UTF-8 with or without BOM, delimiter sniffed (comma, semicolon, tab; German Excel exports use semicolons).
- Names are trimmed. Blank rows and rows starting with `#` are ignored. Duplicate names within the sheet (case/space-insensitive) are registered once and reported.

**Blocked by:** 03

**Status:** ready-for-agent

**Read first:** `spec.md` modules 1 (State Store), 2 (Stage Runner) and 18 (Recipe Requests), and the CLI surface; ticket 03 (`mp add --file`, which this mirrors for names).

- [ ] The State Store gets a Recipe Request entity:
  - id, row number, source file, `name`, optional `url` / `language` / `notes` / `cuisine`
  - status: `pending`, `found`, `not_found`, `needs_choice`, `imported`, `already_in_mealie`, `review`, `failed`
  - the chosen page URL, the candidates considered, and the Mealie slug/link
  - Migrations are versioned like the rest.
- [ ] Parsing is a pure module, table-tested on fixtures the test builds itself (XLSX written in the test with `openpyxl`, CSV strings):
  - header variants, a headerless single column
  - a semicolon CSV with umlauts, a BOM
  - blank and comment rows, duplicates
  - a row with a URL and one without
  - a missing `name` column, which gives a clear error naming the accepted headers
- [ ] Re-importing the same file doesn't create duplicates: rows match by normalized name (or URL), and the summary says "N new, M already known".
- [ ] `mp requests` prints a table with status counts and the latest errors. `mp requests retry <row|name>` and `mp requests reset --failed-only` work like their Video counterparts.
- [ ] `reports/requests.csv` has one row per request: row number, name, status, chosen URL, Mealie link, score, reason. It's rewritten after every run, and written UTF-8 with BOM so Excel opens it correctly.
- [ ] Pipeline-seam test: importing a 6-row CSV (one duplicate, one blank, one with a URL) leaves 4 requests and the right summary.
- [ ] `openpyxl` is added to `pyproject.toml`. Old `.xls` files are rejected with a message asking for XLSX or CSV.

**Manual check on the laptop (user):** `uv run mp requests add --file <your sheet>` then `uv run mp requests`. Confirm the count matches your rows.
