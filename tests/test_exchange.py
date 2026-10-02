"""The interchange export must be readable by generic tools: re-read it with plain csv/openpyxl."""

import csv
import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from decisionmaker.core import project
from decisionmaker.core.exchange import build_tables, export_csv_zip, export_xlsx
from decisionmaker.core.pairwise import analyze

EXAMPLES = Path(__file__).resolve().parents[1] / "decisionmaker" / "examples"
NAMES = ["laptop_ahp.json", "car_anp.json"]


def read_zip_csv(z: zipfile.ZipFile, name: str) -> list[list[str]]:
    text = z.read(name).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.parametrize("name", NAMES)
def test_csv_zip_matrices_reproduce_priorities(tmp_path, name):
    model = project.load(EXAMPLES / name)
    path = tmp_path / "out.zip"
    export_csv_zip(model, path)
    with zipfile.ZipFile(path) as z:
        files = set(z.namelist())
        assert {"README.txt", "structure.csv", "judgments.csv", "comparisons.csv", "results.csv"} <= files
        index = read_zip_csv(z, "comparisons.csv")
        assert len(index) - 1 == len(model.comparison_sets())
        for row in index[1:]:
            rows = read_zip_csv(z, row[-1])
            names = rows[0][1:-1]
            m = np.array([[float(x) for x in r[1:-1]] for r in rows[1:]])
            pri = np.array([float(r[-1]) for r in rows[1:]])
            assert [r[0] for r in rows[1:]] == names
            assert m * m.T == pytest.approx(np.ones_like(m))  # reciprocal
            assert analyze(m).priorities == pytest.approx(pri, abs=1e-8)
        if model.kind == "anp":
            assert "connections.csv" in files and "limit_supermatrix.csv" in files


@pytest.mark.parametrize("name", NAMES)
def test_judgments_table_rebuilds_the_same_model(tmp_path, name):
    """Re-entering only the Judgments rows (as a user would in another tool) gives identical results."""
    model = project.load(EXAMPLES / name)
    path = tmp_path / "out.zip"
    export_csv_zip(model, path)
    with zipfile.ZipFile(path) as z:
        judgments = read_zip_csv(z, "judgments.csv")
    header = judgments[0]
    col = {h: k for k, h in enumerate(header)}
    fresh = project.load(EXAMPLES / name)
    fresh.comparisons.clear()
    sets = {s.title: s for s in fresh.comparison_sets()}
    for row in judgments[1:]:
        s = sets[row[col["Comparison"]]]
        a = s.item_ids[s.item_names.index(row[col["Item A"]])]
        b = s.item_ids[s.item_names.index(row[col["Item B"]])]
        # use the questionnaire columns, not the numeric value
        pref, intensity = row[col["Preferred"]], int(row[col["Intensity (1-9)"]])
        value = 1.0 if pref == "Equal" else (intensity if pref == row[col["Item A"]] else 1 / intensity)
        assert float(row[col["Value (A over B)"]]) == pytest.approx(value)
        fresh.comparison(s.key).set(a, b, value)
    assert fresh.evaluate().alternative_scores == pytest.approx(model.evaluate().alternative_scores)


@pytest.mark.parametrize("name", NAMES)
def test_xlsx_workbook(tmp_path, name):
    openpyxl = pytest.importorskip("openpyxl")
    model = project.load(EXAMPLES / name)
    path = tmp_path / "out.xlsx"
    export_xlsx(model, path)
    wb = openpyxl.load_workbook(path)
    for sheet in ["About", "Structure", "Judgments", "Comparisons", "Results"]:
        assert sheet in wb.sheetnames
    tables = build_tables(model)
    index = wb["Comparisons"]
    assert index.max_row - 1 == len(tables.matrices)
    for r in range(2, index.max_row + 1):
        sheet_name = index.cell(r, index.max_column).value
        assert index.cell(r, index.max_column).hyperlink is not None
        ws = wb[sheet_name]
        n = len([c for c in ws[1] if c.value is not None]) - 2  # minus corner and Priority
        m = np.array([[ws.cell(i, j).value for j in range(2, n + 2)] for i in range(2, n + 2)], dtype=float)
        assert m * m.T == pytest.approx(np.ones((n, n)))
        assert ws.cell(2, 2).number_format == "# ?/?"
    if model.kind == "anp":
        assert {"Connections", "Limit supermatrix", "Weighted supermatrix"} <= set(wb.sheetnames)
        conn = wb["Connections"]
        n = len(model.nodes())
        cells = [conn.cell(i, j).value for i in range(2, n + 2) for j in range(2, n + 2)]
        assert set(cells) <= {0, 1}
        assert sum(cells) == len(model.links)
    else:
        results = wb["Results"]
        assert results.cell(3, 2).value == model.evaluate().alternative_names[model.evaluate().ranking()[0]]


def test_long_and_duplicate_sheet_names(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from decisionmaker.core.ahp import GOAL_ID, AHPModel

    m = AHPModel("x" * 60)
    a = m.add_criterion("Same name: with [bad] chars / and a very long tail indeed")
    b = m.add_criterion("Same name: with [bad] chars / and a very long tail indeed")
    for k in range(3):
        m.add_alternative(f"Alt {k}")
    m.comparison(GOAL_ID).set(a.id, b.id, 3)
    path = tmp_path / "x.xlsx"
    export_xlsx(m, path)
    names = openpyxl.load_workbook(path).sheetnames
    assert len(names) == len(set(n.lower() for n in names))
    assert all(len(n) <= 31 for n in names)
