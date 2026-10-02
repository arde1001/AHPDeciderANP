"""Editor for one pairwise comparison set.

Each pair gets the classic questionnaire row  A [9 … 2 1 2 … 9] B : clicking
a number on A's side means "A dominates B by that much". The full reciprocal
matrix is shown (and editable) next to the derived priorities, the
consistency ratio and suggestions for the most inconsistent judgments.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.pairwise import (
    CR_THRESHOLD,
    Comparison,
    ComparisonSet,
    PairwiseResult,
    analyze,
    describe_judgment,
    format_judgment,
    parse_judgment,
)
from .theme import status_color
from .widgets import heading as _heading
from .widgets import muted_color, note

# Button positions left to right: 9 8 ... 2 1 2 ... 9. Position p maps to a_AB.
_POSITIONS = list(range(17))
_LABELS = [str(9 - p) if p < 8 else str(p - 7) for p in _POSITIONS]


def position_to_value(p: int) -> float:
    return float(9 - p) if p <= 8 else 1.0 / (p - 7)


def value_to_position(v: float) -> int:
    return 9 - round(v) if v >= 1 else 7 + round(1 / v)


class PairRow:
    """Widgets for one pair, placed into the editor's grid."""

    def __init__(self, grid: QGridLayout, row: int, name_a: str, name_b: str, on_change):
        self.name_a, self.name_b = name_a, name_b
        self.label_a = QLabel(name_a)
        self.label_a.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.label_b = QLabel(name_b)
        self.describe = QLabel()
        self.describe.setMinimumWidth(190)
        scale = QWidget()
        box = QHBoxLayout(scale)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        self.group = QButtonGroup(scale)
        self.group.setExclusive(True)
        for p in _POSITIONS:
            b = QToolButton()
            b.setText(_LABELS[p])
            b.setCheckable(True)
            b.setAutoRaise(False)
            b.setFixedSize(26, 24)
            if p == 8:
                f = b.font()
                f.setBold(True)
                b.setFont(f)
            side = name_a if p < 8 else name_b
            b.setToolTip(
                "Equal importance" if p == 8
                else f"“{side}” over “{name_b if p < 8 else name_a}”: {_LABELS[p]} "
                     f"({describe_judgment(float(_LABELS[p]))})"
            )
            self.group.addButton(b, p)
            box.addWidget(b)
        self.group.idClicked.connect(lambda p: on_change(self, position_to_value(p)))
        self.frame_widgets = [self.label_a, scale, self.label_b, self.describe]
        for col, w in enumerate(self.frame_widgets):
            grid.addWidget(w, row, col)

    def show_value(self, value: float, judged: bool) -> None:
        if judged:
            self.group.button(value_to_position(value)).setChecked(True)
            if abs(value - 1) < 1e-9:
                text = "Equal (1)"
            else:
                winner = self.name_a if value > 1 else self.name_b
                text = f"{describe_judgment(value)} ({format_judgment(max(value, 1 / value))}) for “{winner}”"
            self.describe.setText(text)
            self.describe.setStyleSheet("")
        else:
            checked = self.group.checkedButton()
            if checked is not None:
                self.group.setExclusive(False)
                checked.setChecked(False)
                self.group.setExclusive(True)
            self.describe.setText("not judged yet (counts as equal)")
            self.describe.setStyleSheet(f"color: {muted_color()}; font-style: italic;")

    def set_highlight(self, on: bool) -> None:
        style = f"color: {status_color(False).name()}; font-weight: bold;" if on else ""
        self.label_a.setStyleSheet(style)
        self.label_b.setStyleSheet(style)


class PairwiseEditor(QWidget):
    changed = Signal()
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._set: ComparisonSet | None = None
        self._comparison: Comparison | None = None
        self._rows: dict[tuple[int, int], PairRow] = {}
        self._updating = False

        self.title = QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.2)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        self.help = note(
            "For each pair, click how strongly the left or the right item dominates (is more important, "
            "preferred or likely): 1 equal · 3 moderate · 5 strong · 7 very strong · 9 extreme, even numbers "
            "in between. You can also type values such as 3 or 1/5 into the matrix."
        )

        # pair rows
        self.rows_host = QWidget()
        self.grid = QGridLayout(self.rows_host)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rows_host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        # matrix
        self.matrix = QTableWidget()
        self.matrix.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.matrix.itemChanged.connect(self._matrix_edited)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # results
        self.priorities = QTableWidget(0, 2)
        self.priorities.setHorizontalHeaderLabels(["Item", "Priority"])
        self.priorities.verticalHeader().setVisible(False)
        self.priorities.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.priorities.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.priorities.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.consistency = QLabel()
        self.consistency.setWordWrap(True)
        self.hints_box = QVBoxLayout()
        self.hints_box.setSpacing(4)

        results = QWidget()
        rl = QVBoxLayout(results)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(_heading("Priorities"))
        rl.addWidget(self.priorities, 1)

        matrix_box = QWidget()
        ml = QVBoxLayout(matrix_box)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(_heading("Comparison matrix (row over column)"))
        ml.addWidget(self.matrix, 1)

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(matrix_box)
        bottom.addWidget(results)
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(scroll)
        split.addWidget(bottom)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 260])

        # the consistency verdict and fix-it hints span the full width below
        status = QWidget()
        sl = QVBoxLayout(status)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.consistency)
        sl.addLayout(self.hints_box)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.help)
        layout.addWidget(split, 1)
        layout.addWidget(status)
        self.set_comparison(None, None)

    # ---- public --------------------------------------------------------

    def set_comparison(self, cset: ComparisonSet | None, comparison: Comparison | None) -> None:
        self._set, self._comparison = cset, comparison
        self._build_rows()
        self._refresh()

    # ---- building ------------------------------------------------------

    def _build_rows(self) -> None:
        _clear_layout(self.grid)
        self._rows.clear()
        if self._set is None:
            self.title.setText("Select a comparison on the left")
            return
        self.title.setText(self._set.title)
        names = self._set.item_names
        n = len(names)
        r = 0
        for i in range(n):
            for j in range(i + 1, n):
                self._rows[(i, j)] = PairRow(self.grid, r, names[i], names[j], self._row_changed)
                r += 1

    def _refresh(self) -> None:
        self._updating = True
        try:
            if self._set is None or self._comparison is None:
                self.matrix.clear()
                self.matrix.setRowCount(0)
                self.matrix.setColumnCount(0)
                self.priorities.setRowCount(0)
                self.consistency.setText("")
                self._show_hints(None)
                return
            ids = self._set.item_ids
            comp = self._comparison
            for (i, j), row in self._rows.items():
                row.show_value(comp.get(ids[i], ids[j]), comp.is_set(ids[i], ids[j]))
            m = comp.matrix(ids)
            result = analyze(m)
            self._fill_matrix(m, result)
            self._fill_results(result)
        finally:
            self._updating = False

    def _fill_matrix(self, m, result: PairwiseResult) -> None:
        ids, names = self._set.item_ids, self._set.item_names
        n = len(ids)
        worst = self._worst_pair(result)
        self.matrix.clear()
        self.matrix.setRowCount(n)
        self.matrix.setColumnCount(n)
        self.matrix.setHorizontalHeaderLabels(names)
        self.matrix.setVerticalHeaderLabels(names)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        alt_bg = self.palette().color(QPalette.ColorRole.AlternateBase)
        for i in range(n):
            for j in range(n):
                item = QTableWidgetItem(format_judgment(m[i, j]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if i == j:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    item.setBackground(QBrush(alt_bg))
                    item.setForeground(QBrush(muted))
                elif not self._comparison.is_set(ids[i], ids[j]):
                    item.setForeground(QBrush(muted))
                    item.setToolTip("Not judged yet")
                if worst and {i, j} == set(worst):
                    bad = QColor(status_color(False))
                    bad.setAlpha(70)
                    item.setBackground(QBrush(bad))
                    item.setToolTip("Most inconsistent judgment")
                self.matrix.setItem(i, j, item)

    def _fill_results(self, result: PairwiseResult) -> None:
        names = self._set.item_names
        self.priorities.setRowCount(len(names))
        order = sorted(range(len(names)), key=lambda k: -result.priorities[k])
        for r, k in enumerate(order):
            self.priorities.setItem(r, 0, QTableWidgetItem(names[k]))
            p = QTableWidgetItem(f"{result.priorities[k]:.4f}  ({result.priorities[k] * 100:.1f}%)")
            p.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.priorities.setItem(r, 1, p)

        ids = self._set.item_ids
        total = len(ids) * (len(ids) - 1) // 2
        made = self._comparison.count_set(ids)
        parts = [f"Judged {made} of {total} pairs."]
        if result.cr is None:
            parts.append("Consistency is not an issue with two items.")
            color, verdict = status_color(True), "✓ Consistent"
        else:
            parts.append(f"λmax {result.lambda_max:.4f} · CI {result.ci:.4f} · RI {result.ri:.2f} · CR {result.cr:.4f}")
            if result.consistent:
                color, verdict = status_color(True), f"✓ Consistent (CR ≤ {CR_THRESHOLD:.2f})"
            else:
                color, verdict = status_color(False), f"⚠ Inconsistent (CR > {CR_THRESHOLD:.2f}): revise the judgments below"
        if made < total:
            color = status_color(None) if result.consistent else color
        self.consistency.setText(
            f"{'<br>'.join(parts)}<br><b style='color:{color.name()}'>{verdict}</b>"
        )
        for row in self._rows.values():
            row.set_highlight(False)
        worst = self._worst_pair(result)
        if worst:
            self._rows[worst].set_highlight(True)
        self._show_hints(result)

    def _worst_pair(self, result: PairwiseResult) -> tuple[int, int] | None:
        if result.consistent or not result.hints:
            return None
        h = result.hints[0]
        return (h.i, h.j)

    def _show_hints(self, result: PairwiseResult | None) -> None:
        _clear_layout(self.hints_box)
        if result is None or result.consistent:
            return
        names = self._set.item_names
        self.hints_box.addWidget(_heading("Most inconsistent judgments"))
        for h in result.hints[:3]:
            if abs(h.suggested - h.current) < 1e-9:
                continue
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            text = QLabel(
                f"“{names[h.i]}” vs “{names[h.j]}”: you gave {format_judgment(h.current)}, "
                f"the other judgments suggest ≈ {format_judgment(h.suggested)}"
            )
            text.setWordWrap(True)
            text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            button = QPushButton("Apply")
            button.setToolTip("Replace this judgment with the suggested value")
            button.clicked.connect(lambda _=False, h=h: self._apply_hint(h.i, h.j, h.suggested))
            hl.addWidget(text, 1)
            hl.addWidget(button)
            self.hints_box.addWidget(row)

    # ---- edits ---------------------------------------------------------

    def _set_judgment(self, i: int, j: int, value: float) -> None:
        ids = self._set.item_ids
        self._comparison.set(ids[i], ids[j], value)
        self._refresh()
        self.changed.emit()

    def _row_changed(self, row: PairRow, value: float) -> None:
        if self._updating:
            return
        (i, j) = next(k for k, r in self._rows.items() if r is row)
        self._set_judgment(i, j, value)

    def _apply_hint(self, i: int, j: int, value: float) -> None:
        self._set_judgment(i, j, value)

    def _matrix_edited(self, item: QTableWidgetItem) -> None:
        if self._updating or self._set is None:
            return
        i, j = item.row(), item.column()
        if i == j:
            return
        try:
            value = parse_judgment(item.text())
        except ValueError as e:
            self.message.emit(f"Invalid judgment “{item.text()}”: {e}. Use 1–9 or 1/2–1/9.")
            self._refresh()
            return
        self._set_judgment(i, j, value)


def _clear_layout(layout) -> None:
    """Remove and delete a layout's widgets, hiding them now rather than at the next event loop pass."""
    while layout.count():
        w = layout.takeAt(0).widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()

