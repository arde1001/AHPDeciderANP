"""List of all comparison sets of a model, with the pairwise editor beside it."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..core.pairwise import analyze
from .pairwise_editor import PairwiseEditor
from .theme import status_color
from .widgets import note

_KEY = Qt.ItemDataRole.UserRole


class ComparisonsPage(QWidget):
    changed = Signal()
    message = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Comparison", "Status"])
        self.tree.setColumnWidth(0, 260)
        self.tree.currentItemChanged.connect(self._selected)
        self.empty = note(
            "Nothing to compare yet. A comparison appears here once something has at least two "
            "items to compare (criteria, sub-criteria, alternatives, or linked nodes and clusters)."
        )
        prev = QPushButton("◀ Previous")
        nxt = QPushButton("Next ▶")
        prev.clicked.connect(lambda: self._step(-1))
        nxt.clicked.connect(lambda: self._step(1))
        nav = QHBoxLayout()
        nav.addWidget(prev)
        nav.addWidget(nxt)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.tree, 1)
        ll.addWidget(self.empty)
        ll.addLayout(nav)

        self.editor = PairwiseEditor()
        self.editor.changed.connect(self._edited)
        self.editor.message.connect(self.message)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(self.editor)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([330, 1000])
        lay = QVBoxLayout(self)
        lay.addWidget(split)

    def set_model(self, model) -> None:
        self.model = model
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list from the model, keeping the current selection."""
        current = self._current_key()
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        select = None
        first = None
        for s in self.model.comparison_sets():
            parent = groups.get(s.group)
            if parent is None:
                parent = QTreeWidgetItem(self.tree, [s.group])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
                groups[s.group] = parent
            item = QTreeWidgetItem(parent, [s.title, ""])
            item.setData(0, _KEY, s.key)
            item.setToolTip(0, s.title)
            self._status(item, s)
            first = first or item
            if s.key == current:
                select = item
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.empty.setVisible(first is None)
        target = select or first
        if target is not None:
            self.tree.setCurrentItem(target)
            self._selected(target, None)
        else:
            self.editor.set_comparison(None, None)

    def select_key(self, key: str) -> None:
        for item in self._items():
            if item.data(0, _KEY) == key:
                self.tree.setCurrentItem(item)
                return

    # ---- internals -----------------------------------------------------

    def _items(self) -> list[QTreeWidgetItem]:
        out = []
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            out += [group.child(k) for k in range(group.childCount())]
        return out

    def _current_key(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, _KEY) if item is not None else None

    def _set_for(self, key: str):
        return next((s for s in self.model.comparison_sets() if s.key == key), None)

    def _status(self, item: QTreeWidgetItem, s) -> None:
        comp = self.model.comparisons.get(s.key)
        total = len(s.item_ids) * (len(s.item_ids) - 1) // 2
        made = comp.count_set(s.item_ids) if comp else 0
        result = analyze(comp.matrix(s.item_ids)) if comp else None
        if result is not None and not result.consistent:
            text, color = f"⚠ CR {result.cr:.2f}", status_color(False)
        elif made < total:
            text, color = f"◐ {made}/{total}", status_color(None)
        else:
            cr = "" if result is None or result.cr is None else f" CR {result.cr:.2f}"
            text, color = f"✓{cr}", status_color(True)
        item.setText(1, text)
        item.setForeground(1, QBrush(color))

    def _selected(self, item: QTreeWidgetItem | None, _previous) -> None:
        key = item.data(0, _KEY) if item is not None else None
        s = self._set_for(key) if key else None
        self.editor.set_comparison(s, self.model.comparison(key) if s else None)

    def _edited(self) -> None:
        item = self.tree.currentItem()
        s = self._set_for(item.data(0, _KEY)) if item is not None else None
        if s is not None:
            self._status(item, s)
        self.changed.emit()

    def _step(self, delta: int) -> None:
        items = self._items()
        if not items:
            return
        current = self.tree.currentItem()
        k = items.index(current) if current in items else -delta
        self.tree.setCurrentItem(items[max(0, min(len(items) - 1, k + delta))])
