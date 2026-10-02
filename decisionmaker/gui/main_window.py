"""Main window: welcome screen, menus, file handling."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import __copyright__, __version__
from ..core import exchange, project
from ..core.ahp import AHPModel
from ..core.anp import ANPModel
from .ahp_editor import AHPEditor
from .anp_editor import ANPEditor
from .widgets import heading, note

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLES = [
    ("AHP: choose a new laptop (criteria with sub-criteria)", "laptop_ahp.json"),
    ("ANP: buy a family car (feedback and inner dependence)", "car_anp.json"),
]
FILE_FILTER = "Decision projects (*.json);;All files (*)"

GUIDE_HTML = """
<h2>How to use</h2>
<ol>
<li><b>Choose a method.</b> <i>AHP</i> is a hierarchy: goal → criteria (→ sub-criteria …) → alternatives.
Use it when the criteria are independent of each other and of the alternatives. <i>ANP</i> is a network of
clusters and nodes with arbitrary influence, including feedback (alternatives influence the importance of the
criteria) and inner dependence (criteria influence each other).</li>
<li><b>Build the model</b> in the first tab(s). For ANP, define in <i>Connections</i> which nodes are
compared with respect to which.</li>
<li><b>AHP: choose how alternatives are scored</b> under each lowest-level criterion (<i>Scoring</i> tab):
pairwise comparison, direct measured values (ratio scale: zero means none; benefit = value / sum, cost =
(1/value) / sum), or ratings (compare levels such as Excellent…Poor once, then rate each alternative).</li>
<li><b>Make the pairwise comparisons.</b> For each pair, pick how strongly one item dominates the other.</li>
<li><b>Check consistency.</b> Aim for a consistency ratio CR ≤ 0.10. When a matrix is inconsistent the editor
highlights the judgment that disagrees most with the others and suggests a value.</li>
<li><b>Read the results</b> and test how robust they are in <i>Sensitivity</i>.</li>
</ol>
<h2>The 1–9 scale</h2>
<table border="0" cellspacing="0" cellpadding="3">
<tr><td><b>1</b></td><td>Equal: both contribute equally</td></tr>
<tr><td><b>3</b></td><td>Moderate: experience slightly favors one</td></tr>
<tr><td><b>5</b></td><td>Strong: experience strongly favors one</td></tr>
<tr><td><b>7</b></td><td>Very strong: dominance demonstrated in practice</td></tr>
<tr><td><b>9</b></td><td>Extreme: the highest possible order of affirmation</td></tr>
<tr><td><b>2, 4, 6, 8</b></td><td>Intermediate values</td></tr>
<tr><td><b>1/x</b></td><td>Reciprocal: the second item dominates the first by x</td></tr>
</table>
<h2>What is computed</h2>
<p><b>Priorities</b>: the normalized principal eigenvector of each comparison matrix.
<b>Consistency</b>: CI = (λ<sub>max</sub> − n)/(n − 1), CR = CI / RI with Saaty's random index RI.</p>
<p><b>AHP</b>: global weights are the products of local weights down the hierarchy; an alternative's score is
the sum over the lowest-level criteria of global weight × local priority. <i>Distributive</i> synthesis uses the
priorities as they are; <i>ideal</i> synthesis first divides them by the best alternative under each criterion.</p>
<p><b>ANP</b>: local priorities fill the <i>unweighted supermatrix</i>; multiplying each block by the cluster
weights and normalizing columns gives the column-stochastic <i>weighted supermatrix</i>; raising it to powers
gives the <i>limit supermatrix</i> (Cesàro-averaged if it cycles). Nodes that link to nothing are made absorbing,
so a plain hierarchy entered as a network gives exactly the AHP answer.</p>
<p><b>Sensitivity</b>: one element's local weight is swept from 0 to 1 while the other elements of the same
comparison keep their proportions.</p>
"""


class WelcomePage(QWidget):
    def __init__(self, window: MainWindow):
        super().__init__()
        grid = QGridLayout()
        buttons = [
            ("New AHP project", "Goal → criteria hierarchy → alternatives", window.new_ahp),
            ("New ANP project", "Clusters and nodes with feedback and dependence", window.new_anp),
            ("Open project…", "Continue a saved .json project", window.open_dialog),
        ]
        for k, (title, sub, slot) in enumerate(buttons):
            b = QPushButton(f"{title}\n{sub}")
            b.setMinimumSize(300, 64)
            b.clicked.connect(slot)
            grid.addWidget(b, k, 0)
        for k, (title, file) in enumerate(EXAMPLES):
            b = QPushButton(f"Example\n{title}")
            b.setMinimumSize(300, 64)
            b.clicked.connect(lambda _=False, f=file: window.open_example(f))
            grid.addWidget(b, k, 1)

        box = QVBoxLayout(self)
        box.addStretch(1)
        title = heading("AHP / ANP Decision Maker", 1.8)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        sub = note(
            "Structure a decision, compare its elements pairwise on Saaty's 1–9 scale, and get "
            "priorities, consistency checks and sensitivity analysis."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(sub)
        box.addSpacing(16)
        host = QWidget()
        host.setLayout(grid)
        host.setMaximumWidth(720)
        box.addWidget(host, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addStretch(2)
        footer = note(__copyright__)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(footer)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model: AHPModel | ANPModel | None = None
        self.path: Path | None = None
        self.editor = None
        self.settings = QSettings("decisionmaker", "decisionmaker")

        self.stack = QStackedWidget()
        self.welcome = WelcomePage(self)
        self.stack.addWidget(self.welcome)
        self.setCentralWidget(self.stack)
        self._build_menus()
        self._update_title()
        self.resize(1280, 820)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    # ---- menus ---------------------------------------------------------

    def _action(self, menu, text: str, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menus(self) -> None:
        m = self.menuBar().addMenu("&File")
        self._action(m, "New &AHP project", self.new_ahp, QKeySequence.StandardKey.New)
        self._action(m, "New A&NP project", self.new_anp, "Ctrl+Shift+N")
        self._action(m, "&Open…", self.open_dialog, QKeySequence.StandardKey.Open)
        examples = m.addMenu("Open &example")
        for title, file in EXAMPLES:
            self._action(examples, title, lambda _=False, f=file: self.open_example(f))
        self.recent_menu = m.addMenu("Open &recent")
        self._fill_recent()
        m.addSeparator()
        self.save_action = self._action(m, "&Save", self.save, QKeySequence.StandardKey.Save)
        self.save_as_action = self._action(m, "Save &as…", self.save_as, QKeySequence.StandardKey.SaveAs)
        export = m.addMenu("&Export")
        self.export_actions = [
            self._action(export, "Model and matrices as &Excel workbook (.xlsx)…", self.export_xlsx, "Ctrl+E"),
            self._action(export, "Model and matrices as CSV files (&zip)…", self.export_csv_zip),
            self._action(export, "Results &summary (single CSV)…", self.export_csv),
        ]
        self.export_menu = export
        m.addSeparator()
        self._action(m, "&Close project", self.close_project, QKeySequence.StandardKey.Close)
        self._action(m, "&Quit", self.close, QKeySequence.StandardKey.Quit)
        h = self.menuBar().addMenu("&Help")
        self._action(h, "&Guide to AHP and ANP", self.show_guide, QKeySequence.StandardKey.HelpContents)
        self._action(h, "&About", self.show_about)
        self._enable_project_actions(False)

    def _enable_project_actions(self, on: bool) -> None:
        for a in (self.save_action, self.save_as_action, *self.export_actions):
            a.setEnabled(on)
        self.export_menu.setEnabled(on)

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = [p for p in (self.settings.value("recent") or []) if Path(p).exists()]
        for p in recent:
            self._action(self.recent_menu, p, lambda _=False, p=p: self._open_checked(Path(p)))
        self.recent_menu.setEnabled(bool(recent))

    def _remember(self, path: Path) -> None:
        recent = [str(path)] + [p for p in (self.settings.value("recent") or []) if p != str(path)]
        self.settings.setValue("recent", recent[:8])
        self._fill_recent()

    # ---- project lifecycle ---------------------------------------------

    def _set_model(self, model, path: Path | None) -> None:
        self.model, self.path = model, path
        if self.editor is not None:
            self.stack.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = AHPEditor(model) if isinstance(model, AHPModel) else ANPEditor(model)
        self.editor.modified.connect(lambda: self.setWindowModified(True))
        self.editor.message.connect(lambda text: self.statusBar().showMessage(text, 6000))
        self.stack.addWidget(self.editor)
        self.stack.setCurrentWidget(self.editor)
        self.setWindowModified(False)
        self._enable_project_actions(True)
        self._update_title()

    def _update_title(self) -> None:
        if self.model is None:
            self.setWindowTitle("AHP / ANP Decision Maker")
            return
        name = self.path.name if self.path else "Untitled"
        self.setWindowTitle(f"{name}[*] · {self.model.kind.upper()} · AHP / ANP Decision Maker")

    def _maybe_save(self) -> bool:
        """True if it is OK to discard the current project."""
        if self.model is None or not self.isWindowModified():
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Save the changes to the current project first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_ahp(self) -> None:
        if self._maybe_save():
            self._set_model(AHPModel("My decision"), None)

    def new_anp(self) -> None:
        if self._maybe_save():
            self._set_model(ANPModel("My decision"), None)

    def close_project(self) -> None:
        if self._maybe_save():
            if self.editor is not None:
                self.stack.removeWidget(self.editor)
                self.editor.deleteLater()
            self.editor, self.model, self.path = None, None, None
            self.stack.setCurrentWidget(self.welcome)
            self.setWindowModified(False)
            self._enable_project_actions(False)
            self._update_title()

    def open_dialog(self) -> None:
        if not self._maybe_save():
            return
        start = str(self.path.parent) if self.path else str(Path.home())
        file, _ = QFileDialog.getOpenFileName(self, "Open project", start, FILE_FILTER)
        if file:
            self.open_path(Path(file))

    def _open_checked(self, path: Path) -> None:
        if self._maybe_save():
            self.open_path(path)

    def open_path(self, path: Path) -> bool:
        try:
            model = project.load(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.critical(self, "Open project", f"Could not open {path}:\n{e}")
            return False
        self._set_model(model, path)
        self._remember(path)
        self.statusBar().showMessage(f"Opened {path}", 4000)
        return True

    def open_example(self, file: str) -> None:
        if not self._maybe_save():
            return
        model = project.load(EXAMPLES_DIR / file)
        self._set_model(model, None)  # never overwrite the bundled example
        self.statusBar().showMessage("Example loaded; use Save as… to keep your changes.", 6000)

    def save(self) -> bool:
        if self.model is None:
            return False
        if self.path is None:
            return self.save_as()
        try:
            project.save(self.model, self.path)
        except OSError as e:
            QMessageBox.critical(self, "Save project", f"Could not save {self.path}:\n{e}")
            return False
        self.setWindowModified(False)
        self._remember(self.path)
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def save_as(self) -> bool:
        if self.model is None:
            return False
        suggestion = self.path or Path.home() / f"{_slug(self.model.goal) or 'decision'}.json"
        file, _ = QFileDialog.getSaveFileName(self, "Save project", str(suggestion), FILE_FILTER)
        if not file:
            return False
        path = Path(file)
        if path.suffix == "":
            path = path.with_suffix(".json")
        self.path = path
        self._update_title()
        return self.save()

    def _export(self, title: str, suffix: str, file_filter: str, writer) -> None:
        if self.model is None:
            return
        base = self.path.with_suffix("") if self.path else Path.home() / (_slug(self.model.goal) or "decision")
        file, _ = QFileDialog.getSaveFileName(self, title, f"{base}{suffix}", f"{file_filter};;All files (*)")
        if not file:
            return
        try:
            writer(self.model, file)
        except OSError as e:
            QMessageBox.critical(self, title, f"Could not write {file}:\n{e}")
            return
        self.statusBar().showMessage(f"Exported to {file}", 5000)

    def export_csv(self) -> None:
        self._export("Export results summary", "-results.csv", "CSV files (*.csv)", project.export_csv)

    def export_xlsx(self) -> None:
        self._export("Export model and matrices", "-model.xlsx", "Excel workbooks (*.xlsx)", exchange.export_xlsx)

    def export_csv_zip(self) -> None:
        self._export("Export model and matrices", "-model.zip", "Zip of CSV files (*.zip)", exchange.export_csv_zip)

    # ---- help ----------------------------------------------------------

    def show_guide(self) -> None:
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Guide to AHP and ANP")
        browser = QTextBrowser()
        browser.setHtml(GUIDE_HTML)
        browser.setMinimumSize(640, 560)
        dlg.layout().addWidget(browser, 0, 0, 1, dlg.layout().columnCount())
        dlg.setStandardButtons(QMessageBox.StandardButton.Close)
        dlg.exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About",
            f"<b>AHP / ANP Decision Maker</b> {__version__}<br>"
            "Analytic Hierarchy Process and Analytic Network Process (T. L. Saaty) "
            f"with pairwise comparisons on the 1–9 scale.<br><br>{__copyright__}",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._maybe_save():
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
        else:
            event.ignore()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:40]
