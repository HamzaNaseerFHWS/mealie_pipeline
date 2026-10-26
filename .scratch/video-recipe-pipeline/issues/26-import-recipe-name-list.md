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

**Status:** done

**Read first:** `spec.md` modules 1 (State Store), 2 (Stage Runner) and 18 (Recipe Requests), and the CLI surface; ticket 03 (`mp add --file`, which this mirrors for names).

- [x] The State Store gets a Recipe Request entity:
  - id, row number, source file, `name`, optional `url` / `language` / `notes` / `cuisine`
  - status: `pending`, `found`, `not_found`, `needs_choice`, `imported`, `already_in_mealie`, `review`, `failed`
  - the chosen page URL, the candidates considered, and the Mealie slug/link
  - Migrations are versioned like the rest.
- [x] Parsing is a pure module, table-tested on fixtures the test builds itself (XLSX written in the test with `openpyxl`, CSV strings):
  - header variants, a headerless single column
  - a semicolon CSV with umlauts, a BOM
  - blank and comment rows, duplicates
  - a row with a URL and one without
  - a missing `name` column, which gives a clear error naming the accepted headers
- [x] Re-importing the same file doesn't create duplicates: rows match by normalized name (or URL), and the summary says "N new, M already known".
- [x] `mp requests` prints a table with status counts and the latest errors. `mp requests retry <row|name>` and `mp requests reset --failed-only` work like their Video counterparts.
- [x] `reports/requests.csv` has one row per request: row number, name, status, chosen URL, Mealie link, score, reason. It's rewritten after every run, and written UTF-8 with BOM so Excel opens it correctly.
- [x] Pipeline-seam test: importing a 6-row CSV (one duplicate, one blank, one with a URL) leaves 4 requests and the right summary.
- [x] `openpyxl` is added to `pyproject.toml`. Old `.xls` files are rejected with a message asking for XLSX or CSV.

**Manual check on the laptop (user):** `uv run mp requests add --file <your sheet>` then `uv run mp requests`. Confirm the count matches your rows.

## Comments

### Built (2026-10-26)

`mp requests add --file <csv|xlsx> [--sheet NAME]`, `mp requests` (status counts, total, latest errors), `mp requests retry <row|name>`, `mp requests reset --failed-only`, and `reports/requests.csv` (rewritten after every `mp requests` command; UTF-8 with BOM; columns `row_number, name, notes, cuisine, status, chosen_url, mealie_url, score, reason`). Nothing searches or imports yet: that is tickets 27 and 28, which will move requests off `pending`.

- **State Store:** migration 3 adds the `recipe_requests` table (id, row number, source file, name, optional url/language/notes/cuisine, status, chosen URL, candidates JSON, slug, Mealie link, score, reason, last error). `StateStore.db` exposes the connection to modules that own their own tables.
- **Parsing** (`request_sheet.py`, tested on CSV text and XLSX files built in the tests): the header variants, a headerless single column, semicolon/tab CSV with umlauts and a BOM, blank and `#` rows, duplicates, URL and non-URL rows, missing name column (error names the accepted headers), `--sheet`, corrupt xlsx, old `.xls` rejected. Row numbers are the Excel row numbers (header = row 1).
- **Identity / re-import:** requests match by normalized name (case, spacing and punctuation insensitive) or normalized URL (scheme, `www.`, trailing slash and fragment ignored); a re-import says "N new, M already known" and changes nothing.
- **retry / reset:** `retry` puts the request(s) matching a row number or a name back to `pending` and clears the error; `imported` and `already_in_mealie` are left alone. `reset` requires `--failed-only` (plain `reset` exits 2 with a message), and only touches `failed`.

### Decisions / notes

- German spellings of the optional headers (`sprache`, `notizen`, `küche`, `link`) are accepted too, for German Excel sheets.
- A bad URL or unknown language in a row is ignored with a warning; the row is still registered.
- Rows that start with `#` in the first cell are comments; a row with data but no name is skipped with a warning.
- Appended store migration number 3: another branch that also appends a migration needs its entry kept in order after this one when merging.

### Manual verification on the laptop (user)

1. `uv run mp requests add --file <your sheet>`: the summary should say "N new, 0 already known" where N is your row count minus blanks and duplicates.
2. `uv run mp requests`: the pending count matches; open `reports/requests.csv` in Excel (umlauts correct).
3. Run the same `add` again: "0 new, N already known".
4. Try a semicolon CSV exported from German Excel, and an `.xlsx` with `--sheet`.

### Follow-up: the grid layout (the user's real sheet)

The user's real sheet is a **grid**, not a list: row 1 holds category titles ("Gerichte – Frühstück / Brunch", "Getränke", "Proteins", ...) and every cell below, in every column, is one standalone recipe name; columns have different lengths. It produces **379 Recipe Requests from 19 columns** (rows 2-31; verified against an independent count of the non-empty cells). 14 names occur in several cells (Butter Chicken, Haleem, Baked Oats, Waffeln, Grießbrei, ...) and stay separate requests, each with its own category.

- `mp requests add --layout auto|list|grid` (default `auto`). `auto` picks **grid** when row 1 has no recognised header (`name`/`recipe`/`title`/`rezept`, `url`, `language`, `notes`, `cuisine` and the German spellings) and at least two columns have a title; otherwise **list**. A one-column sheet is always a list unless `--layout grid` is given; a header row that has list headers but no name column is still the "no name column" error (which now mentions `--layout grid`). The output says which layout was used and how it was chosen, e.g. `layout: grid (auto-detected); 379 request(s) from 19 column(s)`, and lists names that appear in several cells.
- Each request stores its **category** (the column title) and **position** (`R2C1`; `Sheet!R2C1` for an Excel worksheet). Both are columns of `reports/requests.csv` (`row_number, position, name, category, notes, cuisine, status, ...`) and `mp requests` now also prints a requests table (cell, category, name, status; `--show N`, default 25). Ticket 27 can use the category as a search hint.
- **Identity:** a grid cell is known by sheet position + normalized name, so re-adding the file is idempotent, the same recipe in two columns is two requests, and a changed cell is added as new. `mp requests retry` accepts a cell (`R2C2`), a row number or a name (a name resets every cell with that name).
- XLSX follows the same rules (all rows and columns, `--sheet` for each worksheet; positions are true to the sheet even if the data does not start at A1).
- Store migration 4 adds `category`, `position`, `layout` and `identity` to `recipe_requests` (migration 3 is unchanged, so a database already migrated keeps working).
- Fixture: `tests/fixtures/recipe_grid.csv` is a synthetic 5-column, 24-cell grid with the same shape (en dashes, umlauts, a quoted cell with commas, a leading space, empty cells, names repeated across and within columns). The real file is not committed.
