"""Choose, per lowest-level criterion, how the alternatives are scored.

Pairwise comparison (the classic AHP), direct values (measured data such as
hours or euros), or ratings (a pairwise-compared scale like Excellent…Poor
and one rating per alternative).
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.ahp import AHPModel, Criterion, levels_key
from .theme import status_color
from .widgets import button_bar, heading, note, num_item, readonly_table

_ID = Qt.ItemDataRole.UserRole
MODE_LABELS = {
    "pairwise": "Pairwise comparison",
    "direct": "Direct values (measured data)",
    "ratings": "Ratings (Excellent … Poor)",
}


def parse_number(text: str) -> float:
    """Accepts 12.5 and 12,5; raises ValueError."""
    value = float(text.strip().replace(" ", "").replace(",", "."))
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _fmt_value(v: float) -> str:
    return f"{v:g}"


class ScoringPage(QWidget):
    changed = Signal()
    jump = Signal(str)
    message = Signal(str)

    def __init__(self, model: AHPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self._updating = False

        self.leaves = QListWidget()
        self.leaves.currentItemChanged.connect(lambda *_: self._show_leaf())

        self.title = heading("", 1.2)
        self.mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.problem = QLabel()
        self.problem.setWordWrap(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._pairwise_panel())
        self.stack.addWidget(self._direct_panel())
        self.stack.addWidget(self._ratings_panel())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Score the alternatives by:"))
        row.addWidget(self.mode)
        row.addStretch(1)
        rl.addLayout(row)
        rl.addWidget(self.problem)
        rl.addWidget(self.stack, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(heading("Lowest-level criteria"))
        ll.addWidget(self.leaves, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([330, 1000])

        lay = QVBoxLayout(self)
        lay.addWidget(note(
            "Choose how the alternatives are scored under each lowest-level criterion. "
            "<b>Pairwise</b> suits judgment (comfort, style). <b>Direct values</b> suit measured data on a ratio "
            "scale: zero means none and twice the number means twice as good, e.g. hours or euros (not °C or years). "
            "<b>Ratings</b> suit many alternatives: compare the rating levels once, then rate each alternative."
        ))
        lay.addWidget(split, 1)

    # ---- panels ----------------------------------------------------------

    def _pairwise_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(note("The alternatives are compared pairwise under this criterion, on the 1–9 scale."))
        button = QPushButton("Open the comparison")
        button.clicked.connect(lambda: self.jump.emit(self._leaf().id))
        lay.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return w

    def _direct_panel(self) -> QWidget:
        w = QWidget()
        self.direction = QComboBox()
        self.direction.addItem("Higher is better (benefit, e.g. battery life)", "benefit")
        self.direction.addItem("Lower is better (cost, e.g. price)", "cost")
        self.direction.currentIndexChanged.connect(self._direction_changed)
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("optional, e.g. h, €, kg")
        self.unit.setMaximumWidth(200)
        self.unit.textEdited.connect(self._unit_edited)
        form = QFormLayout()
        form.addRow("Direction:", self.direction)
        form.addRow("Unit:", self.unit)

        self.values = readonly_table(["Alternative", "Value", "Priority"])
        self.values.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.values.itemChanged.connect(self._value_edited)
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(self.values, 1)
        lay.addWidget(note(
            "Priorities are value / sum (benefit) or (1/value) / sum of 1/values (cost). Scaling all values by "
            "the same factor, e.g. dividing by their mean, gives the same priorities. Don't subtract anything "
            "(deviations from a mean, min–max scaling): that breaks the ratios."
        ))
        return w

    def _ratings_panel(self) -> QWidget:
        w = QWidget()
        self.levels = QListWidget()
        self.levels.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.levels.itemChanged.connect(self._level_renamed)
        buttons, _ = button_bar(
            ("add", "Add level", self._add_level),
            ("remove", "Remove", self._remove_level),
            ("up", "▲", lambda: self._move_level(-1)),
            ("down", "▼", lambda: self._move_level(1)),
        )
        compare = QPushButton("Compare the levels…")
        compare.setToolTip("The level weights come from a pairwise comparison of the levels")
        compare.clicked.connect(lambda: self.jump.emit(levels_key(self._leaf().id)))
        self.level_weights = QLabel()
        self.level_weights.setWordWrap(True)

        levels_box = QWidget()
        lb = QVBoxLayout(levels_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.addWidget(heading("Rating levels (best first)"))
        lb.addWidget(self.levels, 1)
        lb.addWidget(buttons)
        lb.addWidget(compare, 0, Qt.AlignmentFlag.AlignLeft)
        lb.addWidget(self.level_weights)

        self.ratings = readonly_table(["Alternative", "Rating", "Priority"])
        ratings_box = QWidget()
        rb = QVBoxLayout(ratings_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.addWidget(heading("Rate each alternative"))
        rb.addWidget(self.ratings, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(levels_box)
        split.addWidget(ratings_box)
        split.setStretchFactor(1, 2)
        lay = QVBoxLayout(w)
        lay.addWidget(split, 1)
        lay.addWidget(note(
            "Each level's weight is its priority from the level comparison divided by the best level's, so the "
            "best level counts 1. An alternative's score under this criterion is the weight of its rating."
        ))
        return w

    # ---- display ---------------------------------------------------------

    def set_model(self, model: AHPModel) -> None:
        self.model = model
        self.refresh()

    def _leaf(self) -> Criterion | None:
        item = self.leaves.currentItem()
        return self.model.find(item.data(_ID)) if item is not None else None

    def refresh(self) -> None:
        current = self.leaves.currentItem().data(_ID) if self.leaves.currentItem() else None
        self.leaves.blockSignals(True)
        self.leaves.clear()
        select = None
        for leaf in self.model.leaves():
            item = QListWidgetItem()
            item.setData(_ID, leaf.id)
            self._label(item, leaf)
            self.leaves.addItem(item)
            if leaf.id == current:
                select = item
        self.leaves.blockSignals(False)
        self.leaves.setCurrentItem(select or self.leaves.item(0))
        self._show_leaf()

    def _label(self, item: QListWidgetItem, leaf: Criterion) -> None:
        path = " › ".join(self.model.path(leaf.id)) or f"{leaf.name} (goal)"
        mode = self.model.scoring_mode(leaf)
        problem = self.model.scoring_problem(leaf)
        item.setText(f"{'◐' if problem else '✓'}  {path}  ·  {MODE_LABELS[mode].split(' (')[0]}")
        if problem:
            item.setForeground(QBrush(status_color(None)))
        else:
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
        item.setToolTip(problem or "")

    def _show_leaf(self) -> None:
        leaf = self._leaf()
        self._updating = True
        try:
            if leaf is None:
                self.title.setText("Add criteria and alternatives in the Model tab")
                self.mode.setEnabled(False)
                self.stack.hide()
                self.problem.hide()
                return
            self.mode.setEnabled(True)
            self.stack.show()
            self.title.setText(" › ".join(self.model.path(leaf.id)) or leaf.name)
            mode = self.model.scoring_mode(leaf)
            self.mode.setCurrentIndex(self.mode.findData(mode))
            self.stack.setCurrentIndex(list(MODE_LABELS).index(mode))
            if mode == "direct":
                self._fill_direct(leaf)
            elif mode == "ratings":
                self._fill_ratings(leaf)
            self._show_problem(leaf)
        finally:
            self._updating = False

    def _show_problem(self, leaf: Criterion) -> None:
        problem = self.model.scoring_problem(leaf)
        if problem:
            color = status_color(None).name()
            self.problem.setText(f"<span style='color:{color}'>◐</span> {problem} "
                                 "Until then the alternatives count as equal here.")
            self.problem.show()
        else:
            self.problem.hide()
        item = self.leaves.currentItem()
        if item is not None:
            self._label(item, leaf)

    def _priorities(self, leaf: Criterion):
        return self.model.evaluate().local[leaf.id].priorities if self.model.alternatives else []

    def _fill_direct(self, leaf: Criterion) -> None:
        inp = self.model.scoring(leaf.id)
        self.direction.setCurrentIndex(self.direction.findData(inp.direction))
        if self.unit.text() != inp.unit:
            self.unit.setText(inp.unit)
        self._value_header(inp.unit)
        pri = self._priorities(leaf)
        self.values.blockSignals(True)
        self.values.setRowCount(len(self.model.alternatives))
        for r, a in enumerate(self.model.alternatives):
            name = QTableWidgetItem(a.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.values.setItem(r, 0, name)
            value = QTableWidgetItem(_fmt_value(inp.values[a.id]) if a.id in inp.values else "")
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setData(_ID, a.id)
            value.setToolTip("Type a number (decimal point or comma)")
            self.values.setItem(r, 1, value)
            p = num_item(float(pri[r]), 4, pct=True)
            p.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.values.setItem(r, 2, p)
        self.values.blockSignals(False)

    def _fill_ratings(self, leaf: Criterion) -> None:
        inp = self.model.scoring(leaf.id)
        self.levels.blockSignals(True)
        current = self.levels.currentItem().data(_ID) if self.levels.currentItem() else None
        self.levels.clear()
        for lv in inp.levels:
            item = QListWidgetItem(lv.name)
            item.setData(_ID, lv.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.levels.addItem(item)
            if lv.id == current:
                self.levels.setCurrentItem(item)
        self.levels.blockSignals(False)

        result = self.model.level_priorities(leaf.id)
        if result is not None:
            top = result.priorities.max()
            weights = ", ".join(f"{lv.name} {p / top:.2f}" for lv, p in zip(inp.levels, result.priorities, strict=True))
            cr = "" if result.cr is None else f" · CR {result.cr:.3f}{'' if result.consistent else ' ⚠'}"
            self.level_weights.setText(f"Level weights: {weights}{cr}")
        else:
            self.level_weights.setText("Add rating levels.")

        pri = self._priorities(leaf)
        self.ratings.setRowCount(len(self.model.alternatives))
        for r, a in enumerate(self.model.alternatives):
            self.ratings.setItem(r, 0, QTableWidgetItem(a.name))
            combo = QComboBox()
            combo.addItem("— not rated —", None)
            for lv in inp.levels:
                combo.addItem(lv.name, lv.id)
            combo.setCurrentIndex(max(0, combo.findData(inp.ratings.get(a.id))))
            combo.currentIndexChanged.connect(lambda _i, a_id=a.id, c=combo: self._rated(a_id, c.currentData()))
            self.ratings.setCellWidget(r, 1, combo)
            self.ratings.setItem(r, 2, num_item(float(pri[r]), 4, pct=True))

    # ---- edits -----------------------------------------------------------

    def _edited(self, leaf: Criterion, rebuild: bool = True, deferred: bool = False) -> None:
        """After a change: redraw the panel and tell the editor the project is modified.

        `deferred` waits for the event loop, for edits made from a list/table's own
        itemChanged signal (rebuilding it there would delete the item being edited).
        """
        if rebuild and deferred:
            QTimer.singleShot(0, self._show_leaf)
        elif rebuild:
            self._show_leaf()
        else:
            self._show_problem(leaf)
        self.changed.emit()

    def _mode_changed(self) -> None:
        leaf = self._leaf()
        if self._updating or leaf is None:
            return
        self.model.set_scoring_mode(leaf.id, self.mode.currentData())
        self._edited(leaf)

    def _direction_changed(self) -> None:
        leaf = self._leaf()
        if self._updating or leaf is None:
            return
        self.model.scoring(leaf.id).direction = self.direction.currentData()
        self._edited(leaf)

    def _unit_edited(self, text: str) -> None:
        leaf = self._leaf()
        if leaf is not None:
            self.model.scoring(leaf.id).unit = text.strip()
            self._value_header(text.strip())
            self.changed.emit()

    def _value_header(self, unit: str) -> None:
        self.values.setHorizontalHeaderLabels(["Alternative", f"Value ({unit})" if unit else "Value", "Priority"])

    def _value_edited(self, item: QTableWidgetItem) -> None:
        leaf = self._leaf()
        if self._updating or leaf is None or item.column() != 1:
            return
        values = self.model.scoring(leaf.id).values
        alt_id = item.data(_ID)
        text = item.text().strip()
        if not text:
            values.pop(alt_id, None)
        else:
            try:
                values[alt_id] = parse_number(text)
            except ValueError:
                self.message.emit(f"“{text}” is not a number.")
        self._edited(leaf, deferred=True)

    def _rated(self, alt_id: str, level_id: str | None) -> None:
        leaf = self._leaf()
        if leaf is None:
            return
        ratings = self.model.scoring(leaf.id).ratings
        if level_id is None:
            ratings.pop(alt_id, None)
        else:
            ratings[alt_id] = level_id
        pri = self._priorities(leaf)
        for r in range(len(pri)):
            self.ratings.setItem(r, 2, num_item(float(pri[r]), 4, pct=True))
        self._edited(leaf, rebuild=False)

    def _current_level(self) -> str | None:
        item = self.levels.currentItem()
        return item.data(_ID) if item is not None else None

    def _add_level(self) -> None:
        leaf = self._leaf()
        level = self.model.add_level(leaf.id, f"Level {len(self.model.scoring(leaf.id).levels) + 1}")
        self._edited(leaf)
        for k in range(self.levels.count()):
            if self.levels.item(k).data(_ID) == level.id:
                self.levels.setCurrentRow(k)
                self.levels.editItem(self.levels.item(k))

    def _remove_level(self) -> None:
        leaf, level_id = self._leaf(), self._current_level()
        if level_id:
            self.model.remove_level(leaf.id, level_id)
            self._edited(leaf)

    def _move_level(self, delta: int) -> None:
        leaf, level_id = self._leaf(), self._current_level()
        if level_id:
            self.model.move_level(leaf.id, level_id, delta)
            self._edited(leaf)

    def _level_renamed(self, item: QListWidgetItem) -> None:
        leaf = self._leaf()
        level = next((lv for lv in self.model.scoring(leaf.id).levels if lv.id == item.data(_ID)), None)
        name = item.text().strip()
        if level is None:
            return
        if name:
            level.name = name
        self._edited(leaf, deferred=True)
