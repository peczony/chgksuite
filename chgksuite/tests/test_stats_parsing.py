"""Tests for add_stats results-table parsing (xlsx_to_results / custom_csv_to_results).

The fixtures ``stats_tour.xlsx``, ``stats_full.xlsx`` and ``stats_tour.csv`` are
real "вопросная таблица" exports from rating.chgk.info. ``stats_tour.*`` and
``stats_full.xlsx`` are the same tournament (id 6290) in the two layouts the site
offers, so parsing them must yield identical per-team masks.
"""

import csv
import os

import openpyxl
import pytest

from chgksuite.common import custom_csv_to_results, xlsx_to_results

CURRENTDIR = os.path.dirname(os.path.abspath(__file__))

TOUR_XLSX = os.path.join(CURRENTDIR, "stats_tour.xlsx")
FULL_XLSX = os.path.join(CURRENTDIR, "stats_full.xlsx")
TOUR_CSV = os.path.join(CURRENTDIR, "stats_tour.csv")
# Another real per-tour export: header on row 0 (no leading blank row) and a
# " Номер команды" first column instead of "Team ID".
TOUR_CSV2 = os.path.join(CURRENTDIR, "stats_tour2.csv")


class CapturingLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, *args, **kwargs):
        self.warnings.append(" ".join(str(a) for a in args))

    def info(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def _by_name(results):
    return {r["current"]["name"]: r["mask"] for r in results}


def _write_csv(path, rows, **kwargs):
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, **kwargs).writerows(rows)
    return str(path)


# --- real-file parsing -----------------------------------------------------


def test_tour_xlsx_parses():
    logger = CapturingLogger()
    results = xlsx_to_results(TOUR_XLSX, logger=logger)
    assert len(results) == 59
    assert all(len(r["mask"]) == 36 for r in results)
    assert all(set(r["mask"]) <= {"0", "1"} for r in results)
    assert _by_name(results)["09/13"] == "010001000000000000000000000000000000"
    assert logger.warnings == []


def test_full_xlsx_parses():
    logger = CapturingLogger()
    results = xlsx_to_results(FULL_XLSX, logger=logger)
    assert len(results) == 59
    assert all(len(r["mask"]) == 36 for r in results)
    assert _by_name(results)["09/13"] == "010001000000000000000000000000000000"
    assert logger.warnings == []


def test_tour_and_full_xlsx_agree():
    """Same tournament in 'tour' and 'full' layouts must give identical masks."""
    tour = _by_name(xlsx_to_results(TOUR_XLSX))
    full = _by_name(xlsx_to_results(FULL_XLSX))
    assert set(tour) == set(full)
    assert tour == full


def test_tour_csv_parses():
    """Real CSV export: per-tour layout, UTF-8 BOM and a leading blank row."""
    logger = CapturingLogger()
    results = custom_csv_to_results(TOUR_CSV, logger=logger)
    assert len(results) == 33
    assert all(len(r["mask"]) == 36 for r in results)
    assert all(set(r["mask"]) <= {"0", "1"} for r in results)
    assert _by_name(results)["Acquired Taste"] == "001110110001100111100101111111110100"
    assert logger.warnings == []


def test_tour_csv2_parses():
    """Real CSV export with header on row 0 and a ' Номер команды' first column."""
    logger = CapturingLogger()
    results = custom_csv_to_results(TOUR_CSV2, logger=logger)
    assert len(results) == 80
    assert all(len(r["mask"]) == 36 for r in results)
    assert all(set(r["mask"]) <= {"0", "1"} for r in results)
    assert _by_name(results)["Be Humble"] == "101100111110010100100100100101110101"
    assert logger.warnings == []


# --- csv layouts -----------------------------------------------------------


def test_full_layout_csv(tmp_path):
    """Historical 'full' layout (no 'Тур' column): id, name, city, q1, q2, ..."""
    path = _write_csv(
        tmp_path / "full.csv",
        [
            ["Team ID", "Название", "Город", "1", "2", "3", "4"],
            ["1", "Alpha", "Town", "1", "0", "1", "1"],
            ["2", "Beta", "City", "0", "0", "1", "0"],
        ],
    )
    results = custom_csv_to_results(path)
    assert _by_name(results) == {"Alpha": "1011", "Beta": "0010"}


def test_tour_layout_csv_aggregates_tours(tmp_path):
    """'tour' layout: per-team rows across tours are concatenated in order."""
    path = _write_csv(
        tmp_path / "tour.csv",
        [
            ["Team ID", "Название", "Город", "Тур", "1", "2"],
            ["1", "Alpha", "Town", "1", "1", "0"],
            ["1", "Alpha", "Town", "2", "0", "1"],
            ["2", "Beta", "City", "1", "1", "1"],
            ["2", "Beta", "City", "2", "0", "0"],
        ],
    )
    results = custom_csv_to_results(path)
    assert _by_name(results) == {"Alpha": "1001", "Beta": "1100"}


def test_custom_delimiter_kwargs(tmp_path):
    """Extra kwargs are forwarded to csv.reader (e.g. a semicolon delimiter)."""
    path = tmp_path / "semi.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("Team ID;Название;Город;1;2\n1;Alpha;Town;1;0\n")
    results = custom_csv_to_results(str(path), delimiter=";")
    assert _by_name(results) == {"Alpha": "10"}


def test_leading_blank_row_and_bom(tmp_path):
    path = tmp_path / "bom.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(",,,\n")  # leading blank row, like the real export
        f.write("Team ID,Название,Город,1,2\n")
        f.write("1,Alpha,Town,1,1\n")
    results = custom_csv_to_results(str(path))
    assert _by_name(results) == {"Alpha": "11"}


# --- disputed / malformed handling -----------------------------------------


def test_disputed_value_warns_not_fails(tmp_path):
    """Unresolved controversials (non-0/1) are counted as 0 and warned about."""
    path = _write_csv(
        tmp_path / "disputed.csv",
        [
            ["Team ID", "Название", "Город", "1", "2", "3"],
            ["1", "Alpha", "Town", "1", "X", "1"],
        ],
    )
    logger = CapturingLogger()
    results = custom_csv_to_results(path, logger=logger)
    assert _by_name(results) == {"Alpha": "101"}
    assert len(logger.warnings) == 1
    assert "спорны" in logger.warnings[0].lower() or "X" in logger.warnings[0]


def test_disputed_value_in_xlsx_warns(tmp_path):
    path = tmp_path / "disputed.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Team ID", "Название", "Город", 1, 2, 3])
    ws.append([1, "Alpha", "Town", 1, "?", 0])
    wb.save(path)
    logger = CapturingLogger()
    results = xlsx_to_results(str(path), logger=logger)
    assert _by_name(results) == {"Alpha": "100"}
    assert len(logger.warnings) == 1


def test_empty_csv_returns_empty_and_warns(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    logger = CapturingLogger()
    assert custom_csv_to_results(str(path), logger=logger) == []
    assert len(logger.warnings) == 1


def test_headerless_csv_returns_empty_and_warns(tmp_path):
    path = _write_csv(
        tmp_path / "noheader.csv",
        [["1", "Alpha", "Town", "1", "0"]],
    )
    logger = CapturingLogger()
    assert custom_csv_to_results(path, logger=logger) == []
    assert len(logger.warnings) == 1


def test_no_logger_does_not_raise(tmp_path):
    """Calling without a logger must not raise on the warning path."""
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert custom_csv_to_results(str(path)) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
