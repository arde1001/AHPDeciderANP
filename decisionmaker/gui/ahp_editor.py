"""AHP project editor: model → comparisons → results → sensitivity."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.ahp import GOAL_ID, AHPModel
from .comparisons_page import ComparisonsPage
from .sensitivity_page import SensitivityPage
from .widgets import ConsistencyTable, RankingPanel, button_bar, heading, note, show_warnings, warnings_label

_ID = Qt.ItemDataRole.UserRole


class AHPModelPage(QWidget):
    """Goal, criteria hierarchy and alternatives."""

    changed = Signal()

    def __init__(self, model: AHPModel, parent=None):
        super().__init__(parent)
        self.model = model

        self.goal = QLineEdit()
        self.goal.setPlaceholderText("What are you deciding? e.g. “Choose a new laptop”")
        self.goal.textEdited.connect(self._goal_edited)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tree.itemChanged.connect(self._criterion_renamed)
        tree_buttons, self.tree_btn = button_bar(
            ("add", "Add criterion", self._add_criterion),
            ("sub", "Add sub-criterion", self._add_subcriterion),
            ("rename", "Rename", lambda: self._rename(self.tree)),
            ("remove", "Remove", self._remove_criterion),
            ("up", "▲", lambda: self._move_criterion(-1)),
            ("down", "▼", lambda: self._move_criterion(1)),
        )
        self.tree_btn["add"].setToolTip("Add a criterion at the same level as the selected one")
        self.tree_btn["sub"].setToolTip("Add a sub-criterion under the selected criterion")
        self.tree_btn["up"].setToolTip("Move up")
        self.tree_btn["down"].setToolTip("Move down")
        crit_box = QGroupBox("Criteria hierarchy")
        cl = QVBoxLayout(crit_box)
        cl.addWidget(self.tree, 1)
        cl.addWidget(tree_buttons)
        cl.addWidget(note(
            "The goal is the root. <i>Add criterion</i> adds one at the selected level; <i>Add sub-criterion</i> "
            "adds one below the selected criterion. "
            "Alternatives are compared under every criterion that has no sub-criteria."
        ))

        self.alts = QListWidget()
        self.alts.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.alts.itemChanged.connect(self._alternative_renamed)
        alt_buttons, _ = button_bar(
            ("add", "Add alternative", self._add_alternative),
            ("rename", "Rename", lambda: self._rename(self.alts)),
            ("remove", "Remove", self._remove_alternative),
            ("up", "▲", lambda: self._move_alternative(-1)),
            ("down", "▼", lambda: self._move_alternative(1)),
        )
        alt_box = QGroupBox("Alternatives (options)")
        al = QVBoxLayout(alt_box)
        al.addWidget(self.alts, 1)
        al.addWidget(alt_buttons)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(crit_box)
        split.addWidget(alt_box)

        goal_row = QHBoxLayout()
        goal_row.addWidget(heading("Goal:"))
        goal_row.addWidget(self.goal, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(goal_row)
        lay.addWidget(split, 1)
        lay.addWidget(note(
            "Next: open <b>Comparisons</b> and judge each pair on the 1–9 scale. Names can be edited in place "
            "(double-click or F2); judgments are kept when you rename, reorder or add items."
        ))
        self.refresh()

    def set_model(self, model: AHPModel) -> None:
        self.model = model
        self.refresh()

    # ---- display -------------------------------------------------------

    def refresh(self, select: str | None = None) -> None:
        if self.goal.text() != self.model.goal:
            self.goal.setText(self.model.goal)
        current = select or self._current_id(self.tree)
        self.tree.blockSignals(True)
        self.tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for node, parent, _depth in self.model.walk():
            if parent is None:
                item = QTreeWidgetItem(self.tree, [f"◎ {node.name}"])
                f = item.font(0)
                f.setBold(True)
                item.setFont(0, f)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip(0, "The goal (edit it in the field above)")
            else:
                item = QTreeWidgetItem(items[parent.id], [node.name])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, _ID, node.id)
            items[node.id] = item
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if current in items:
            self.tree.setCurrentItem(items[current])

        current_alt = self._current_id(self.alts)
        self.alts.blockSignals(True)
        self.alts.clear()
        for a in self.model.alternatives:
            item = QListWidgetItem(a.name)
            item.setData(_ID, a.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.alts.addItem(item)
            if a.id == current_alt:
                self.alts.setCurrentItem(item)
        self.alts.blockSignals(False)

    @staticmethod
    def _current_id(view) -> str | None:
        item = view.currentItem()
        if item is None:
            return None
        return item.data(0, _ID) if isinstance(item, QTreeWidgetItem) else item.data(_ID)

    def _edit_new(self, node_id: str) -> None:
        self.refresh(select=node_id)
        item = self.tree.currentItem()
        if item is not None:
            self.tree.editItem(item, 0)

    # ---- edits ---------------------------------------------------------

    def _goal_edited(self, text: str) -> None:
        self.model.goal = text
        root = self.tree.topLevelItem(0)
        if root is not None:
            self.tree.blockSignals(True)
            root.setText(0, f"◎ {text}")
            self.tree.blockSignals(False)
        self.changed.emit()

    def _add_criterion(self) -> None:
        """Add a criterion at the level of the selected one (top level if the goal is selected)."""
        selected = self._current_id(self.tree)
        parent = self.model.root if selected in (None, GOAL_ID) else self.model.parent_of(selected)
        prefix = "Criterion" if parent is self.model.root else "Sub-criterion"
        node = self.model.add_criterion(f"{prefix} {len(parent.children) + 1}", parent.id)
        self.changed.emit()
        self._edit_new(node.id)

    def _add_subcriterion(self) -> None:
        parent_id = self._current_id(self.tree) or GOAL_ID
        parent = self.model.find(parent_id)
        if parent is not self.model.root and not parent.children and self.model.comparisons.get(parent_id):
            answer = QMessageBox.question(
                self, "Add sub-criterion",
                f"“{parent.name}” will no longer compare alternatives directly, so its alternative "
                "judgments stop being used. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        node = self.model.add_criterion(f"Sub-criterion {len(parent.children) + 1}", parent_id)
        self.changed.emit()
        self._edit_new(node.id)

    def _remove_criterion(self) -> None:
        node_id = self._current_id(self.tree)
        if node_id in (None, GOAL_ID):
            return
        node = self.model.find(node_id)
        if node.children:
            answer = QMessageBox.question(
                self, "Remove criterion", f"Remove “{node.name}” and all of its sub-criteria?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.model.remove_criterion(node_id)
        self.refresh()
        self.changed.emit()

    def _move_criterion(self, delta: int) -> None:
        node_id = self._current_id(self.tree)
        if node_id and node_id != GOAL_ID:
            self.model.move_criterion(node_id, delta)
            self.refresh(select=node_id)
            self.changed.emit()

    def _criterion_renamed(self, item: QTreeWidgetItem, _col: int) -> None:
        node = self.model.find(item.data(0, _ID))
        name = item.text(0).strip()
        if node is None or node.id == GOAL_ID:
            return
        if not name:
            self.tree.blockSignals(True)
            item.setText(0, node.name)
            self.tree.blockSignals(False)
            return
        node.name = name
        self.changed.emit()

    def _rename(self, view) -> None:
        item = view.currentItem()
        if item is None:
            return
        if isinstance(view, QTreeWidget):
            if item.data(0, _ID) == GOAL_ID:
                self.goal.setFocus()
                self.goal.selectAll()
            else:
                view.editItem(item, 0)
        else:
            view.editItem(item)

    def _add_alternative(self) -> None:
        alt = self.model.add_alternative(f"Alternative {len(self.model.alternatives) + 1}")
        self.refresh()
        self.changed.emit()
        for k in range(self.alts.count()):
            if self.alts.item(k).data(_ID) == alt.id:
                self.alts.setCurrentRow(k)
                self.alts.editItem(self.alts.item(k))

    def _remove_alternative(self) -> None:
        alt_id = self._current_id(self.alts)
        if alt_id:
            self.model.remove_alternative(alt_id)
            self.refresh()
            self.changed.emit()

    def _move_alternative(self, delta: int) -> None:
        alt_id = self._current_id(self.alts)
        if alt_id:
            self.model.move_alternative(alt_id, delta)
            self.refresh()
            self.changed.emit()

    def _alternative_renamed(self, item: QListWidgetItem) -> None:
        alt = next((a for a in self.model.alternatives if a.id == item.data(_ID)), None)
        name = item.text().strip()
        if alt is None:
            return
        if not name:
            self.alts.blockSignals(True)
            item.setText(alt.name)
            self.alts.blockSignals(False)
            return
        alt.name = name
        self.changed.emit()


class AHPResultsPage(QWidget):
    changed = Signal()
    jump = Signal(str)

    def __init__(self, model: AHPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.mode = QComboBox()
        self.mode.addItem("Distributive (normal) synthesis", "distributive")
        self.mode.addItem("Ideal synthesis", "ideal")
        self.mode.setToolTip(
            "Distributive: alternative priorities under each criterion sum to 1 (the classic AHP).\n"
            "Ideal: the best alternative under each criterion gets 1; this prevents rank reversal "
            "when alternatives are added or removed."
        )
        self.mode.currentIndexChanged.connect(self._mode_changed)
        top = QHBoxLayout()
        top.addWidget(heading("Ranking of alternatives", 1.15))
        top.addStretch(1)
        top.addWidget(QLabel("Synthesis:"))
        top.addWidget(self.mode)

        self.ranking = RankingPanel()
        self.weights = QTreeWidget()
        self.weights.setHeaderLabels(["Criterion", "Local weight", "Global weight"])
        self.weights.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.consistency = ConsistencyTable()
        self.consistency.jump.connect(self.jump)
        self.warnings = warnings_label()

        lower = QSplitter(Qt.Orientation.Horizontal)
        wbox = QWidget()
        wl = QVBoxLayout(wbox)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(heading("Criteria weights"))
        wl.addWidget(self.weights)
        cbox = QWidget()
        cl = QVBoxLayout(cbox)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(heading("Consistency of judgments"))
        cl.addWidget(self.consistency)
        lower.addWidget(wbox)
        lower.addWidget(cbox)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(self.ranking)
        vsplit.addWidget(lower)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.warnings)
        lay.addWidget(vsplit, 1)

    def set_model(self, model: AHPModel) -> None:
        self.model = model
        self.refresh()

    def _mode_changed(self) -> None:
        self.model.synthesis = self.mode.currentData()
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.model.synthesis)))
        self.mode.blockSignals(False)
        result = self.model.evaluate()
        self.ranking.fill(result.alternative_names, result.alternative_scores)

        self.weights.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for node, parent, _ in self.model.walk():
            if parent is None:
                item = QTreeWidgetItem(self.weights, [node.name, "", "1.0000"])
            else:
                item = QTreeWidgetItem(
                    items[parent.id],
                    [node.name, f"{result.local_weights[node.id]:.4f}", f"{result.global_weights[node.id]:.4f}"],
                )
            for c in (1, 2):
                item.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            items[node.id] = item
        self.weights.expandAll()

        bad, incomplete = self.consistency.fill(self.model, result)
        warnings = self.model.warnings()
        if bad:
            warnings.append(f"{bad} comparison(s) are inconsistent (CR > 0.10). Double-click one below to revise it.")
        if incomplete:
            warnings.append(f"{incomplete} comparison(s) are incomplete; unjudged pairs count as equal.")
        show_warnings(self.warnings, warnings)


class AHPEditor(QTabWidget):
    modified = Signal()
    message = Signal(str)

    def __init__(self, model: AHPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.model_page = AHPModelPage(model)
        self.comparisons = ComparisonsPage(model)
        self.results = AHPResultsPage(model)
        self.sensitivity = SensitivityPage(model)
        self.addTab(self.model_page, "1 · Model")
        self.addTab(self.comparisons, "2 · Comparisons")
        self.addTab(self.results, "3 · Results")
        self.addTab(self.sensitivity, "4 · Sensitivity")
        for page in (self.model_page, self.comparisons, self.results):
            page.changed.connect(self.modified)
        self.comparisons.message.connect(self.message)
        self.results.jump.connect(self.jump_to)
        self.currentChanged.connect(self._tab_changed)

    def set_model(self, model: AHPModel) -> None:
        self.model = model
        for page in (self.model_page, self.comparisons, self.results, self.sensitivity):
            page.model = model
        self.model_page.refresh()
        self._tab_changed(self.currentIndex())

    def _tab_changed(self, index: int) -> None:
        page = self.widget(index)
        if page is not self.model_page:
            page.refresh()

    def jump_to(self, key: str) -> None:
        self.setCurrentWidget(self.comparisons)
        self.comparisons.select_key(key)
