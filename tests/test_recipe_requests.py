"""Recipe Requests at the pipeline seam: `mp requests ...` on a temporary workspace."""

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.cli import app
from mealie_pipeline.recipe_requests import RecipeRequests
from mealie_pipeline.store import StateStore
from tests.helpers import fake_adapters

SIX_ROWS = (
    "name,url,notes\n"
    "Palak Paneer,,creamy\n"
    "Chicken Karahi,,\n"
    "palak  paneer,,again\n"  # duplicate of row 2
    ",,\n"  # blank
    "Aloo Gobi,https://example.com/aloo-gobi,\n"
    "Dal Makhani,,\n"
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def workspace(tmp_path) -> Path:
    (tmp_path / ".env").write_text("MEALIE_URL=http://fake:9000\nMEALIE_TOKEN=t\n", encoding="utf-8")
    return tmp_path


def mp(workspace: Path, *args: str):
    return CliRunner().invoke(app, ["--workspace", str(workspace), *args], obj=fake_adapters())


def sheet(workspace: Path, text: str, name: str = "recipes.csv") -> Path:
    path = workspace / name
    path.write_text(text, encoding="utf-8")
    return path


def requests(workspace: Path) -> RecipeRequests:
    return RecipeRequests(StateStore(workspace / "pipeline.db"))


def set_status(workspace: Path, name: str, status: str, error: str | None = None) -> None:
    db = StateStore(workspace / "pipeline.db").db
    db.execute("UPDATE recipe_requests SET status = ?, last_error = ? WHERE name = ?", (status, error, name))
    db.commit()


def test_a_six_row_csv_leaves_four_requests_and_the_right_summary(workspace):
    result = mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))

    assert result.exit_code == 0, result.output
    assert "4 new, 0 already known" in result.output
    assert "1 duplicate name(s) in the sheet" in result.output
    stored = requests(workspace).all()
    assert [(r.row_number, r.name, r.status) for r in stored] == [
        (2, "Palak Paneer", "pending"),
        (3, "Chicken Karahi", "pending"),
        (6, "Aloo Gobi", "pending"),
        (7, "Dal Makhani", "pending"),
    ]
    assert stored[2].url == "https://example.com/aloo-gobi" and stored[0].notes == "creamy"


def test_reimporting_the_same_file_creates_no_duplicates(workspace):
    path = sheet(workspace, SIX_ROWS)
    mp(workspace, "requests", "add", "--file", str(path))

    again = mp(workspace, "requests", "add", "--file", str(path))

    assert "0 new, 4 already known" in again.output
    assert len(requests(workspace).all()) == 4


def test_a_second_sheet_adds_only_the_new_names_and_matches_by_url_too(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))
    other = sheet(
        workspace,
        "name,url\nPALAK PANEER,\nMy aloo gobi,http://www.example.com/aloo-gobi/\nBiryani,\n",
        "more.csv",
    )

    result = mp(workspace, "requests", "add", "--file", str(other))

    assert "1 new, 2 already known" in result.output  # name match, then URL match
    assert [r.name for r in requests(workspace).all()][-1] == "Biryani"


def test_a_missing_name_column_is_a_clear_error_and_imports_nothing(workspace):
    result = mp(
        workspace, "requests", "add", "--file", str(sheet(workspace, "url,notes\nhttps://x.com,hi\n"))
    )

    assert result.exit_code == 2
    assert "name, recipe, title, rezept" in result.output
    assert requests(workspace).all() == []


def test_an_old_xls_file_is_rejected(workspace):
    old = workspace / "old.xls"
    old.write_bytes(b"\xd0\xcf\x11\xe0")

    result = mp(workspace, "requests", "add", "--file", str(old))

    assert result.exit_code == 2 and ".xlsx or .csv" in result.output


def test_a_missing_file_is_a_clear_error(workspace):
    result = mp(workspace, "requests", "add", "--file", str(workspace / "nope.csv"))

    assert result.exit_code == 2 and "cannot import" in result.output


def test_listing_shows_status_counts_and_the_latest_errors(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))
    set_status(workspace, "Chicken Karahi", "failed", "search provider timed out")
    set_status(workspace, "Dal Makhani", "imported")

    out = mp(workspace, "requests").output

    cells = {c[0]: c[1] for c in (line.replace("│", " ").split() for line in out.splitlines()) if len(c) == 2}
    assert (cells["pending"], cells["failed"], cells["imported"], cells["found"]) == ("2", "1", "1", "0")
    assert "Requests: 4" in out
    assert "row 3 Chicken Karahi: search provider timed out" in out


def test_retry_by_row_number_and_by_name_puts_a_request_back_to_pending(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))
    set_status(workspace, "Chicken Karahi", "failed", "boom")
    set_status(workspace, "Palak Paneer", "not_found")

    by_row = mp(workspace, "requests", "retry", "3")
    by_name = mp(workspace, "requests", "retry", "palak PANEER")

    assert by_row.exit_code == 0 and "row 3 Chicken Karahi: back to pending" in by_row.output
    assert by_name.exit_code == 0
    stored = {r.name: r for r in requests(workspace).all()}
    assert stored["Chicken Karahi"].status == "pending" and stored["Chicken Karahi"].last_error is None
    assert stored["Palak Paneer"].status == "pending"


def test_retry_leaves_finished_requests_alone_and_unknown_ones_exit_1(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))
    set_status(workspace, "Dal Makhani", "imported")

    finished = mp(workspace, "requests", "retry", "Dal Makhani")
    unknown = mp(workspace, "requests", "retry", "Biryani")

    assert "already imported, left alone" in finished.output
    assert unknown.exit_code == 1 and "no request matches" in unknown.output
    assert {r.name: r.status for r in requests(workspace).all()}["Dal Makhani"] == "imported"


def test_reset_failed_only_resets_failed_and_nothing_else(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))
    set_status(workspace, "Chicken Karahi", "failed", "boom")
    set_status(workspace, "Aloo Gobi", "not_found")
    set_status(workspace, "Dal Makhani", "review")

    result = mp(workspace, "requests", "reset", "--failed-only")

    assert result.exit_code == 0 and "1 failed request(s) back to pending" in result.output
    assert {r.name: r.status for r in requests(workspace).all()} == {
        "Palak Paneer": "pending",
        "Chicken Karahi": "pending",
        "Aloo Gobi": "not_found",
        "Dal Makhani": "review",
    }


def test_reset_without_the_flag_does_nothing(workspace):
    result = mp(workspace, "requests", "reset")

    assert result.exit_code == 2 and "--failed-only" in result.output


def test_requests_csv_has_one_row_per_request_and_is_utf8_with_bom(workspace):
    text = "name,url,notes,cuisine\nKäsespätzle,,mit Röstzwiebeln,German\nPalak Paneer,https://x.com/p,,\n"
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, text)))
    set_status(workspace, "Palak Paneer", "failed", "page was a listicle")

    mp(workspace, "requests")  # the report is rewritten after every command

    path = workspace / "reports" / "requests.csv"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "row_number", "name", "notes", "cuisine", "status", "chosen_url", "mealie_url", "score", "reason",
    ]  # fmt: skip
    assert rows[0] == {
        "row_number": "2",
        "name": "Käsespätzle",
        "notes": "mit Röstzwiebeln",
        "cuisine": "German",
        "status": "pending",
        "chosen_url": "",
        "mealie_url": "",
        "score": "",
        "reason": "",
    }
    assert (rows[1]["status"], rows[1]["chosen_url"], rows[1]["reason"]) == (
        "failed",
        "https://x.com/p",
        "page was a listicle",
    )


def test_the_requests_survive_reopening_the_database(workspace):
    mp(workspace, "requests", "add", "--file", str(sheet(workspace, SIX_ROWS)))

    assert len(requests(workspace).all()) == 4  # a fresh StateStore (migrations re-applied) sees them


def test_an_xlsx_sheet_imports_through_the_cli(workspace):
    from openpyxl import Workbook

    workbook = Workbook()
    active = workbook.active
    assert active is not None
    active.append(["Rezept", "Sprache"])
    active.append(["Grüne Soße", "de"])
    active.append(["Palak Paneer", None])
    path = workspace / "list.xlsx"
    workbook.save(path)

    result = mp(workspace, "requests", "add", "--file", str(path))

    assert result.exit_code == 0 and "2 new, 0 already known" in result.output
    assert [(r.name, r.language) for r in requests(workspace).all()] == [
        ("Grüne Soße", "de"),
        ("Palak Paneer", None),
    ]
