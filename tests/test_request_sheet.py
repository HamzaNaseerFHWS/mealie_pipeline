"""Sheet parsing: table tests on CSV text and XLSX files the tests build themselves."""

from pathlib import Path

import pytest
from openpyxl import Workbook

from mealie_pipeline.request_sheet import SheetError, SheetRow, parse_cells, read_sheet


def write_csv(tmp_path: Path, text: str, *, encoding: str = "utf-8", name: str = "recipes.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def names(path: Path) -> list[str]:
    return [r.name for r in read_sheet(path).rows]


@pytest.mark.parametrize("header", ["name", "Name", "RECIPE", "Title", "Rezept", " rezept "])
def test_every_name_header_variant_is_accepted(tmp_path, header):
    path = write_csv(tmp_path, f"{header}\nPalak Paneer\nAloo Gobi\n")

    assert names(path) == ["Palak Paneer", "Aloo Gobi"]


def test_row_numbers_are_the_excel_rows_with_the_header_as_row_1(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "name\nA\n\nB\n"))

    assert [(r.row_number, r.name) for r in parsed.rows] == [(2, "A"), (4, "B")]


def test_a_headerless_single_column_is_a_plain_list_of_names(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "Palak Paneer\nChicken Karahi\n"))

    assert [(r.row_number, r.name) for r in parsed.rows] == [(1, "Palak Paneer"), (2, "Chicken Karahi")]


def test_all_optional_columns_are_read_in_any_order(tmp_path):
    text = (
        "Notes,URL,Name,Cuisine,Language\n"
        "extra spicy,https://example.com/karahi,Chicken Karahi,Pakistani,Urdu\n"
        ",,Käsespätzle,German,de\n"
    )

    first, second = read_sheet(write_csv(tmp_path, text)).rows

    assert first == SheetRow(
        2, "Chicken Karahi", "https://example.com/karahi", "ur", "extra spicy", "Pakistani"
    )
    assert second == SheetRow(3, "Käsespätzle", None, "de", None, "German")


def test_a_semicolon_csv_with_umlauts_and_a_bom(tmp_path):
    text = "Rezept;Sprache;Notizen\nKäsespätzle;de;mit Röstzwiebeln\nGrüne Soße;de;\n"
    path = write_csv(tmp_path, text, encoding="utf-8-sig")

    parsed = read_sheet(path)

    assert [(r.name, r.language, r.notes) for r in parsed.rows] == [
        ("Käsespätzle", "de", "mit Röstzwiebeln"),
        ("Grüne Soße", "de", None),
    ]


def test_a_tab_separated_file(tmp_path):
    assert names(write_csv(tmp_path, "name\turl\nDal\t\nRoti\t\n")) == ["Dal", "Roti"]


def test_a_quoted_name_containing_the_delimiter_stays_one_cell(tmp_path):
    assert names(write_csv(tmp_path, 'name\n"Dal, Tadka"\n')) == ["Dal, Tadka"]


def test_blank_rows_and_comment_rows_are_ignored_and_names_are_trimmed(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "name\n  Dal  \n\n# my wishlist\n   \n#Roti,skipped\nNaan\n"))

    assert [r.name for r in parsed.rows] == ["Dal", "Naan"]
    assert parsed.warnings == []


def test_duplicates_within_the_sheet_are_registered_once_and_reported(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "name\nPalak Paneer\npalak   PANEER\nPalak-Paneer!\nDal\n"))

    assert [r.name for r in parsed.rows] == ["Palak Paneer", "Dal"]
    assert parsed.duplicates == ["palak   PANEER", "Palak-Paneer!"]


def test_a_row_with_data_but_no_name_is_skipped_with_a_warning(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "name,notes\nDal,\n,only a note\n"))

    assert [r.name for r in parsed.rows] == ["Dal"]
    assert parsed.warnings == ["row 3: no name, skipped"]


def test_a_bad_url_or_language_is_ignored_with_a_warning_but_the_row_stays(tmp_path):
    parsed = read_sheet(write_csv(tmp_path, "name,url,language\nDal,not a url,klingon\n"))

    (row,) = parsed.rows
    assert (row.name, row.url, row.language) == ("Dal", None, None)
    assert len(parsed.warnings) == 2


@pytest.mark.parametrize("text", ["url,notes\nhttps://x.com,hi\n", "dal,roti\nnaan,rice\n"])
def test_a_missing_name_column_names_the_accepted_headers(tmp_path, text):
    with pytest.raises(SheetError, match="name, recipe, title, rezept"):
        read_sheet(write_csv(tmp_path, text))


def test_an_empty_file_is_an_error(tmp_path):
    with pytest.raises(SheetError, match="empty"):
        read_sheet(write_csv(tmp_path, "\n\n"))


def test_a_non_utf8_csv_asks_for_csv_utf8(tmp_path):
    with pytest.raises(SheetError, match="UTF-8"):
        read_sheet(write_csv(tmp_path, "name\nKäse\n", encoding="cp1252"))


def test_old_xls_files_are_rejected_with_a_helpful_message(tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0")

    with pytest.raises(SheetError, match=r"\.xlsx or \.csv"):
        read_sheet(path)


def test_an_unknown_extension_is_rejected(tmp_path):
    path = tmp_path / "recipes.docx"
    path.write_bytes(b"x")

    with pytest.raises(SheetError, match="unsupported file type"):
        read_sheet(path)


def make_xlsx(tmp_path: Path) -> Path:
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    first.title = "Wishlist"
    first.append(["Name", "URL", "Cuisine"])
    first.append(["Palak Paneer", None, "Indian"])
    first.append([None, None, None])
    first.append(["Aloo Gobi", "https://example.com/aloo", None])
    second = workbook.create_sheet("Other")
    second.append(["name"])
    second.append(["Dal Makhani"])
    path = tmp_path / "recipes.xlsx"
    workbook.save(path)
    return path


def test_xlsx_reads_the_first_worksheet_by_default(tmp_path):
    parsed = read_sheet(make_xlsx(tmp_path))

    assert [(r.row_number, r.name, r.url, r.cuisine) for r in parsed.rows] == [
        (2, "Palak Paneer", None, "Indian"),
        (4, "Aloo Gobi", "https://example.com/aloo", None),
    ]


def test_xlsx_sheet_option_picks_a_worksheet_and_an_unknown_one_lists_the_choices(tmp_path):
    path = make_xlsx(tmp_path)

    assert [r.name for r in read_sheet(path, "Other").rows] == ["Dal Makhani"]
    with pytest.raises(SheetError, match="Wishlist, Other"):
        read_sheet(path, "Nope")


def test_a_corrupt_xlsx_is_a_clear_error(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not a zip file")

    with pytest.raises(SheetError, match="cannot read broken.xlsx"):
        read_sheet(path)


def test_parse_cells_works_on_a_plain_grid():
    parsed = parse_cells([["name"], ["Dal"], ["Roti"]])

    assert [r.name for r in parsed.rows] == ["Dal", "Roti"]
