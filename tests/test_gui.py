"""Offscreen smoke tests that drive the real widgets."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

import matplotlib  # noqa: E402

matplotlib.use("QtAgg")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from decisionmaker.core import project  # noqa: E402
from decisionmaker.core.ahp import GOAL_ID  # noqa: E402
from decisionmaker.core.anp import ANPModel  # noqa: E402
from decisionmaker.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    # never block on a modal dialog
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w = MainWindow()
    w.settings.clear()
    yield w
    w.setWindowModified(False)
    w.close()


def visit_all_tabs(editor):
    for k in range(editor.count()):
        editor.setCurrentIndex(k)
        QApplication.processEvents()


def test_ahp_example_full_workflow(window, tmp_path):
    window.open_example("laptop_ahp.json")
    editor = window.editor
    model = window.model
    visit_all_tabs(editor)

    # comparisons: first set is criteria w.r.t. goal
    editor.setCurrentWidget(editor.comparisons)
    page = editor.comparisons
    page.select_key(GOAL_ID)
    pe = page.editor
    ids = pe._set.item_ids
    row = pe._rows[(0, 1)]
    row.group.button(0).click()  # leftmost = 9 for the first item
    assert model.comparison(GOAL_ID).get(ids[0], ids[1]) == 9
    assert window.isWindowModified()

    # typing into the matrix (row 2 over column 0)
    pe.matrix.item(2, 0).setText("1/5")
    assert model.comparison(GOAL_ID).get(ids[2], ids[0]) == pytest.approx(1 / 5)
    messages = []
    pe.message.connect(messages.append)
    pe.matrix.item(2, 0).setText("banana")
    assert messages and model.comparison(GOAL_ID).get(ids[2], ids[0]) == pytest.approx(1 / 5)

    # make the matrix inconsistent, then apply the first hint and see CR improve
    pe.matrix.item(0, 3).setText("1/9")
    before = model.evaluate().local[GOAL_ID].cr
    assert before > 0.1
    QApplication.processEvents()  # let deleteLater() remove stale hint rows
    apply = [b for b in pe.findChildren(QPushButton) if b.text() == "Apply"]
    assert apply
    apply[0].click()
    after = model.evaluate().local[GOAL_ID].cr
    assert after < before

    # navigation buttons walk through all sets without errors
    for _ in range(10):
        page._step(1)

    # results: switch synthesis mode
    editor.setCurrentWidget(editor.results)
    editor.results.mode.setCurrentIndex(1)
    assert model.synthesis == "ideal"
    assert editor.results.ranking.table.rowCount() == 3

    # consistency table double-click jumps to the comparison
    editor.results.consistency.jump.emit(GOAL_ID)
    assert editor.currentWidget() is editor.comparisons

    # sensitivity: pick a criterion and probe
    editor.setCurrentWidget(editor.sensitivity)
    sp = editor.sensitivity
    sp.item_combo.setCurrentIndex(1)
    sp.slider.setValue(900)
    assert sp.table.rowCount() == 3
    assert sp.result is not None

    # save and export
    path = tmp_path / "laptop.json"
    window.path = path
    assert window.save()
    assert not window.isWindowModified()
    assert project.load(path).synthesis == "ideal"
    project.export_csv(model, tmp_path / "out.csv")


def test_ahp_model_page_editing(window):
    window.new_ahp()
    editor = window.editor
    model = window.model
    mp = editor.model_page
    mp._add_criterion()
    mp._add_criterion()  # the new criterion is selected: adds a sibling
    assert len(model.root.children) == 2
    # a sub-criterion under the second criterion, then a sibling of it
    mp.refresh(select=model.root.children[1].id)
    mp._add_subcriterion()
    mp._add_criterion()
    assert len(model.root.children[1].children) == 2
    assert [c.name for c in model.root.children[1].children] == ["Sub-criterion 1", "Sub-criterion 2"]
    # rename via the tree item
    item = mp.tree.topLevelItem(0).child(0)
    item.setText(0, "Price")
    assert model.root.children[0].name == "Price"
    for _ in range(3):
        mp._add_alternative()
    assert len(model.alternatives) == 3
    mp.alts.setCurrentRow(2)
    mp._move_alternative(-1)
    assert model.alternatives[1].name == "Alternative 3"
    mp._remove_alternative()
    assert len(model.alternatives) == 2
    mp.goal.setText("Pick")
    mp._goal_edited("Pick")
    assert model.goal == "Pick"
    visit_all_tabs(editor)
    sets = model.comparison_sets()
    # goal (2 criteria) + criterion 2 (2 subs) + 3 leaves with 2 alternatives
    assert len(sets) == 5
    # removing a criterion with children asks (patched to Yes) and removes the subtree
    mp.refresh(select=model.root.children[1].id)
    mp._remove_criterion()
    assert len(model.root.children) == 1


def test_anp_example_full_workflow(window, tmp_path):
    window.open_example("car_anp.json")
    editor = window.editor
    model: ANPModel = window.model
    visit_all_tabs(editor)

    # supermatrix views
    editor.setCurrentWidget(editor.supermatrix)
    for k in range(editor.supermatrix.which.count()):
        editor.supermatrix.which.setCurrentIndex(k)
        n = editor.supermatrix.table.rowCount()
        assert n in (len(model.clusters), len(model.nodes()))

    # toggle a connection in the grid
    editor.setCurrentWidget(editor.connections)
    cp = editor.connections
    links = len(model.links)
    item = cp.table.item(0, 0)  # goal compared w.r.t. goal
    item.setCheckState(Qt.CheckState.Checked)
    assert len(model.links) == links + 1
    item.setCheckState(Qt.CheckState.Unchecked)
    assert len(model.links) == links

    # bulk: unlink alternatives -> criteria feedback, then link it again
    alts = next(c for c in model.clusters if c.name == "Alternatives")
    crit = next(c for c in model.clusters if c.name == "Criteria")
    cp.src.setCurrentIndex(cp.src.findData(alts.id))
    cp.dst.setCurrentIndex(cp.dst.findData(crit.id))
    cp._bulk(False)
    assert len(model.links) == links - 9
    cp._bulk(True)
    assert len(model.links) == links

    editor.setCurrentWidget(editor.results)
    assert editor.results.ranking.table.rowCount() == 3
    assert editor.results.nodes.rowCount() == len(model.nodes())

    editor.setCurrentWidget(editor.sensitivity)
    sp = editor.sensitivity
    for k in range(sp.set_combo.count()):
        sp.set_combo.setCurrentIndex(k)
    sp.slider.setValue(100)

    project.export_csv(model, tmp_path / "anp.csv")


def test_anp_new_project_with_template(window):
    window.new_anp()
    editor = window.editor
    model = window.model
    editor.network._template()
    assert [c.name for c in model.clusters] == ["Goal", "Criteria", "Alternatives"]
    assert len(model.links) == 3 + 9 + 9
    editor.network.tree.setCurrentItem(editor.network.tree.topLevelItem(1))
    editor.network._add_node()
    assert len(model.clusters[1].nodes) == 4
    visit_all_tabs(editor)
    r = model.evaluate()
    assert r.alternative_scores.sum() == pytest.approx(1)
    # remove a cluster (confirmation patched to Yes)
    editor.network.tree.setCurrentItem(editor.network.tree.topLevelItem(0))
    editor.network._remove()
    assert len(model.clusters) == 2
    visit_all_tabs(editor)


def test_close_and_reopen(window, tmp_path):
    window.open_example("laptop_ahp.json")
    path = tmp_path / "x.json"
    window.path = path
    window.save()
    window.close_project()
    assert window.model is None
    assert window.open_path(path)
    assert window.model.goal == "Choose a new laptop"
    assert not window.open_path(tmp_path / "missing.json")
