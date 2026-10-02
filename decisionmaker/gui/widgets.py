"""Small widgets shared by the AHP and ANP editors."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.pairwise import CR_THRESHOLD
from .charts import RankingChart
from .theme import status_color


def muted_color() -> str:
    return QApplication.palette().color(QPalette.ColorRole.PlaceholderText).name()


def heading(text: str, scale: float = 1.0) -> QLabel:
    label = QLabel(text)
    f = label.font()
    f.setBold(True)
    if scale != 1.0:
        f.setPointSizeF(f.pointSizeF() * scale)
    label.setFont(f)
    return label


def note(text: str) -> QLabel:
    """Secondary explanatory text."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setStyleSheet(f"color: {muted_color()};")
    return label


def button_bar(*buttons: tuple[str, str, object]) -> tuple[QWidget, dict[str, QPushButton]]:
    """A row of buttons given as (key, label, slot)."""
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    out = {}
    for key, text, slot in buttons:
        b = QPushButton(text)
        b.clicked.connect(slot)
        lay.addWidget(b)
        out[key] = b
    lay.addStretch(1)
    return host, out


def readonly_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    return t


def num_item(value: float, digits: int = 4, pct: bool = False) -> QTableWidgetItem:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        item = QTableWidgetItem("—")
    else:
        text = f"{value:.{digits}f}"
        if pct:
            text += f"  ({value * 100:.1f}%)"
        item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class ConsistencyTable(QTableWidget):
    """Every comparison set with its completion and CR. Double-click jumps to it."""

    jump = Signal(str)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Comparison", "Judged", "CR", "Status"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setToolTip("Double-click a row to open that comparison")
        self.cellDoubleClicked.connect(lambda r, _c: self.jump.emit(self.item(r, 0).data(Qt.ItemDataRole.UserRole)))

    def fill(self, model, result) -> tuple[int, int]:
        """Returns (number of inconsistent sets, number of incomplete sets)."""
        sets = model.comparison_sets()
        self.setRowCount(len(sets))
        bad = incomplete = 0
        for r, s in enumerate(sets):
            res = result.local.get(s.key)
            total = len(s.item_ids) * (len(s.item_ids) - 1) // 2
            made = model.comparisons[s.key].count_set(s.item_ids) if s.key in model.comparisons else 0
            title = QTableWidgetItem(s.title)
            title.setData(Qt.ItemDataRole.UserRole, s.key)
            self.setItem(r, 0, title)
            self.setItem(r, 1, QTableWidgetItem(f"{made}/{total}"))
            self.setItem(r, 2, num_item(res.cr if res and res.cr is not None else float("nan"), 3))
            if res is not None and not res.consistent:
                bad += 1
                status, color = f"⚠ CR > {CR_THRESHOLD:.2f}", status_color(False)
            elif made < total:
                incomplete += 1
                status, color = "◐ incomplete", status_color(None)
            else:
                status, color = "✓ consistent", status_color(True)
            item = QTableWidgetItem(status)
            item.setForeground(QBrush(color))
            self.setItem(r, 3, item)
        return bad, incomplete


class RankingPanel(QWidget):
    """Ranking table next to a bar chart of the alternatives' priorities."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = readonly_table(["Alternative", "Priority", "Rank"])
        self.chart = RankingChart()
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(self.chart)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)

    def fill(self, names: list[str], scores: np.ndarray) -> None:
        order = sorted(range(len(names)), key=lambda k: -scores[k])
        self.table.setRowCount(len(order))
        for r, k in enumerate(order):
            name = QTableWidgetItem(names[k])
            if r == 0:
                f = name.font()
                f.setBold(True)
                name.setFont(f)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, num_item(float(scores[k]), 4, pct=True))
            self.table.setItem(r, 2, num_item(r + 1, 0))
        self.chart.plot(names, scores)


def warnings_label() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def show_warnings(label: QLabel, warnings: list[str]) -> None:
    if not warnings:
        label.hide()
        return
    color = status_color(None).name()
    items = "".join(f"<li>{w}</li>" for w in warnings)
    label.setText(f"<b style='color:{color}'>⚠ Check the model</b><ul style='margin:0'>{items}</ul>")
    label.show()
