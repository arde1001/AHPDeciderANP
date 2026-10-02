"""ANP project editor: network → connections → comparisons → supermatrices → results → sensitivity."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.anp import ANPModel
from .comparisons_page import ComparisonsPage
from .sensitivity_page import SensitivityPage
from .widgets import (
    ConsistencyTable,
    RankingPanel,
    button_bar,
    heading,
    note,
    num_item,
    readonly_table,
    show_warnings,
    warnings_label,
)

_ID = Qt.ItemDataRole.UserRole
_KIND = Qt.ItemDataRole.UserRole + 1


class NetworkPage(QWidget):
    changed = Signal()

    def __init__(self, model: ANPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("What are you deciding?")
        self.goal.textEdited.connect(self._goal_edited)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tree.itemChanged.connect(self._renamed)
        buttons, self.btn = button_bar(
            ("cluster", "Add cluster", self._add_cluster),
            ("node", "Add node", self._add_node),
            ("rename", "Rename", self._rename),
            ("remove", "Remove", self._remove),
            ("up", "▲", lambda: self._move(-1)),
            ("down", "▼", lambda: self._move(1)),
        )
        self.template = QPushButton("Start from template: Goal → Criteria ⇄ Alternatives")
        self.template.clicked.connect(self._template)
        net_box = QGroupBox("Clusters and nodes")
        nl = QVBoxLayout(net_box)
        nl.addWidget(self.tree, 1)
        nl.addWidget(buttons)
        nl.addWidget(self.template)

        self.alt_combo = QComboBox()
        self.alt_combo.currentIndexChanged.connect(self._alt_changed)
        self.start_combo = QComboBox()
        self.start_combo.currentIndexChanged.connect(self._start_changed)
        settings = QGroupBox("Evaluation settings")
        form = QFormLayout(settings)
        form.addRow("Alternatives cluster:", self.alt_combo)
        form.addRow("Start (goal) node:", self.start_combo)
        form.addRow(note(
            "<b>Alternatives cluster</b>: whose nodes are ranked in the results.<br>"
            "<b>Start node</b>: the column of the limit matrix that is read. With feedback (a strongly connected "
            "network) every column gives the same answer. In a network with a goal and nodes that link to "
            "nothing (sinks), read from the goal. <i>Automatic</i> uses the single node that nothing links into, "
            "if there is one, else the average of all columns."
        ))
        form.addRow(note(
            "A <b>cluster</b> groups comparable nodes (e.g. criteria, alternatives, actors). "
            "Next, define in <b>Connections</b> which nodes influence which."
        ))

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(net_box)
        split.addWidget(settings)
        goal_row = QHBoxLayout()
        goal_row.addWidget(heading("Decision:"))
        goal_row.addWidget(self.goal, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(goal_row)
        lay.addWidget(split, 1)
        self.refresh()

    def set_model(self, model: ANPModel) -> None:
        self.model = model
        self.refresh()

    def refresh(self, select: str | None = None) -> None:
        if self.goal.text() != self.model.goal:
            self.goal.setText(self.model.goal)
        current = select or self._current()[0]
        self.tree.blockSignals(True)
        self.tree.clear()
        target = None
        for c in self.model.clusters:
            ci = QTreeWidgetItem(self.tree, [c.name])
            ci.setData(0, _ID, c.id)
            ci.setData(0, _KIND, "cluster")
            ci.setFlags(ci.flags() | Qt.ItemFlag.ItemIsEditable)
            f = ci.font(0)
            f.setBold(True)
            ci.setFont(0, f)
            if c.id == current:
                target = ci
            for n in c.nodes:
                ni = QTreeWidgetItem(ci, [n.name])
                ni.setData(0, _ID, n.id)
                ni.setData(0, _KIND, "node")
                ni.setFlags(ni.flags() | Qt.ItemFlag.ItemIsEditable)
                if n.id == current:
                    target = ni
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if target is not None:
            self.tree.setCurrentItem(target)
        self.template.setVisible(not self.model.clusters)
        self._fill_settings()

    def _fill_settings(self) -> None:
        self.alt_combo.blockSignals(True)
        self.alt_combo.clear()
        auto = self.model.effective_alternatives_cluster() if not self.model.alternatives_cluster else None
        self.alt_combo.addItem(f"Automatic ({auto.name})" if auto else "Automatic", None)
        for c in self.model.clusters:
            self.alt_combo.addItem(c.name, c.id)
        self.alt_combo.setCurrentIndex(max(0, self.alt_combo.findData(self.model.alternatives_cluster)))
        self.alt_combo.blockSignals(False)

        self.start_combo.blockSignals(True)
        self.start_combo.clear()
        detected = None if self.model.start_node else self.model.effective_start_node()
        name = self.model.node(detected).name if detected else "average of all columns"
        self.start_combo.addItem(f"Automatic ({name})", None)
        for n, c in self.model.nodes():
            self.start_combo.addItem(f"{c.name} › {n.name}", n.id)
        self.start_combo.setCurrentIndex(max(0, self.start_combo.findData(self.model.start_node)))
        self.start_combo.blockSignals(False)

    def _current(self) -> tuple[str | None, str | None]:
        item = self.tree.currentItem()
        if item is None:
            return None, None
        return item.data(0, _ID), item.data(0, _KIND)

    def _goal_edited(self, text: str) -> None:
        self.model.goal = text
        self.changed.emit()

    def _alt_changed(self) -> None:
        self.model.alternatives_cluster = self.alt_combo.currentData()
        self._fill_settings()
        self.changed.emit()

    def _start_changed(self) -> None:
        self.model.start_node = self.start_combo.currentData()
        self._fill_settings()
        self.changed.emit()

    def _edit(self, item_id: str) -> None:
        self.refresh(select=item_id)
        item = self.tree.currentItem()
        if item is not None:
            self.tree.editItem(item, 0)

    def _add_cluster(self) -> None:
        c = self.model.add_cluster(f"Cluster {len(self.model.clusters) + 1}")
        self.changed.emit()
        self._edit(c.id)

    def _add_node(self) -> None:
        item_id, kind = self._current()
        if kind == "node":
            item_id = self.model.cluster_of(item_id).id
        if item_id is None:
            if not self.model.clusters:
                QMessageBox.information(self, "Add node", "Add a cluster first; every node belongs to a cluster.")
                return
            item_id = self.model.clusters[-1].id
        cluster = self.model.cluster(item_id)
        n = self.model.add_node(item_id, f"{cluster.name} {len(cluster.nodes) + 1}")
        self.changed.emit()
        self._edit(n.id)

    def _rename(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.tree.editItem(item, 0)

    def _remove(self) -> None:
        item_id, kind = self._current()
        if item_id is None:
            return
        if kind == "cluster":
            c = self.model.cluster(item_id)
            if c.nodes and QMessageBox.question(
                self, "Remove cluster", f"Remove cluster “{c.name}” with its {len(c.nodes)} node(s)?"
            ) != QMessageBox.StandardButton.Yes:
                return
            self.model.remove_cluster(item_id)
        else:
            self.model.remove_node(item_id)
        self.refresh()
        self.changed.emit()

    def _move(self, delta: int) -> None:
        item_id, kind = self._current()
        if item_id is None:
            return
        if kind == "cluster":
            self.model.move_cluster(item_id, delta)
        else:
            self.model.move_node(item_id, delta)
        self.refresh(select=item_id)
        self.changed.emit()

    def _renamed(self, item: QTreeWidgetItem, _col: int) -> None:
        obj = (self.model.cluster if item.data(0, _KIND) == "cluster" else self.model.node)(item.data(0, _ID))
        name = item.text(0).strip()
        if obj is None:
            return
        if not name:
            self.tree.blockSignals(True)
            item.setText(0, obj.name)
            self.tree.blockSignals(False)
            return
        obj.name = name
        self._fill_settings()
        self.changed.emit()

    def _template(self) -> None:
        m = self.model
        goal_c = m.add_cluster("Goal")
        goal = m.add_node(goal_c.id, m.goal or "Goal")
        crit = m.add_cluster("Criteria")
        alts = m.add_cluster("Alternatives")
        cs = [m.add_node(crit.id, f"Criterion {k}") for k in (1, 2, 3)]
        xs = [m.add_node(alts.id, f"Alternative {k}") for k in (1, 2, 3)]
        for c in cs:
            m.set_link(goal.id, c.id, True)
            for x in xs:
                m.set_link(c.id, x.id, True)  # alternatives compared w.r.t. each criterion
                m.set_link(x.id, c.id, True)  # feedback: criteria compared w.r.t. each alternative
        m.alternatives_cluster = alts.id
        self.refresh()
        self.changed.emit()


class ConnectionsPage(QWidget):
    changed = Signal()

    def __init__(self, model: ANPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.table = QTableWidget()
        self.table.itemChanged.connect(self._toggled)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.src = QComboBox()
        self.dst = QComboBox()
        link_all = QPushButton("Link all")
        unlink_all = QPushButton("Unlink all")
        link_all.clicked.connect(lambda: self._bulk(True))
        unlink_all.clicked.connect(lambda: self._bulk(False))
        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Compare every node of"))
        bulk.addWidget(self.dst)
        bulk.addWidget(QLabel("with respect to every node of"))
        bulk.addWidget(self.src)
        bulk.addWidget(link_all)
        bulk.addWidget(unlink_all)
        bulk.addStretch(1)
        self.count = QLabel()

        lay = QVBoxLayout(self)
        lay.addWidget(note(
            "Tick <b>row i, column j</b> when element <i>i</i> should be compared with respect to element <i>j</i> "
            "(i influences j, or j depends on i). That is exactly where i's priority appears in column j of the "
            "supermatrix. Links inside one cluster model inner dependence; links back from alternatives to "
            "criteria model feedback."
        ))
        lay.addLayout(bulk)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.count)

    def set_model(self, model: ANPModel) -> None:
        self.model = model
        self.refresh()

    def refresh(self) -> None:
        pairs = self.model.nodes()
        n = len(pairs)
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setRowCount(n)
        self.table.setColumnCount(n)
        self.table.setVerticalHeaderLabels([f"{c.name} › {x.name}" for x, c in pairs])
        self.table.setHorizontalHeaderLabels([x.name for x, _ in pairs])
        for j, (x, c) in enumerate(pairs):
            self.table.horizontalHeaderItem(j).setToolTip(f"with respect to {c.name} › {x.name}")
        cluster_index = {c.id: k for k, c in enumerate(self.model.clusters)}
        shade = QBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
        for i, (xi, ci) in enumerate(pairs):
            for j, (xj, cj) in enumerate(pairs):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if self.model.is_linked(xj.id, xi.id) else Qt.CheckState.Unchecked
                )
                item.setToolTip(f"Compare “{xi.name}” with respect to “{xj.name}”")
                if (cluster_index[ci.id] + cluster_index[cj.id]) % 2:
                    item.setBackground(shade)
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)
        for combo in (self.src, self.dst):
            current = combo.currentData()
            combo.clear()
            for c in self.model.clusters:
                combo.addItem(c.name, c.id)
            k = combo.findData(current)
            if k >= 0:
                combo.setCurrentIndex(k)
        self._count()

    def _count(self) -> None:
        self.count.setText(f"{len(self.model.links)} connection(s), {len(self.model.comparison_sets())} comparison(s) to make.")

    def _toggled(self, item: QTableWidgetItem) -> None:
        pairs = self.model.nodes()
        target, control = pairs[item.row()][0], pairs[item.column()][0]
        self.model.set_link(control.id, target.id, item.checkState() == Qt.CheckState.Checked)
        self._count()
        self.changed.emit()

    def _bulk(self, on: bool) -> None:
        src, dst = self.model.cluster(self.src.currentData()), self.model.cluster(self.dst.currentData())
        if src is None or dst is None:
            return
        for j in src.nodes:
            for i in dst.nodes:
                if i.id != j.id:
                    self.model.set_link(j.id, i.id, on)
        self.refresh()
        self.changed.emit()


class SupermatrixPage(QWidget):
    def __init__(self, model: ANPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.which = QComboBox()
        self.which.addItem("Unweighted supermatrix", "unweighted")
        self.which.addItem("Cluster weight matrix", "cluster_matrix")
        self.which.addItem("Weighted supermatrix", "weighted")
        self.which.addItem("Limit supermatrix", "limit")
        self.which.currentIndexChanged.connect(self.refresh)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.info = QLabel()
        self.info.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(QLabel("Show:"))
        top.addWidget(self.which)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.info)
        lay.addWidget(self.table, 1)

    def set_model(self, model: ANPModel) -> None:
        self.model = model
        self.refresh()

    def refresh(self) -> None:
        r = self.model.evaluate()
        kind = self.which.currentData()
        if kind == "cluster_matrix":
            labels = r.cluster_names
            short = labels
        else:
            labels = [f"{c} › {n}" for c, n in zip(r.node_clusters, r.node_names, strict=True)]
            short = r.node_names
        m: np.ndarray = getattr(r, kind)
        self.table.clear()
        self.table.setRowCount(len(labels))
        self.table.setColumnCount(len(labels))
        self.table.setVerticalHeaderLabels(labels)
        self.table.setHorizontalHeaderLabels(short)
        muted = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
        for i in range(len(labels)):
            for j in range(len(labels)):
                item = num_item(float(m[i, j]), 4)
                if abs(m[i, j]) < 1e-12:
                    item.setText("0")
                    item.setForeground(muted)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        texts = {
            "unweighted": "Column j holds the local priorities of the nodes compared with respect to node j, "
                          "block by cluster. Each block column sums to 1.",
            "cluster_matrix": "Column D holds the weights of the clusters compared with respect to cluster D.",
            "weighted": "Unweighted blocks multiplied by their cluster weights, columns renormalized to sum to 1 "
                        "(column stochastic).",
            "limit": f"The weighted supermatrix raised to powers until it stabilizes: {r.limit_status}.",
        }
        text = texts[kind]
        if r.sinks and kind in ("weighted", "limit"):
            names = ", ".join(r.node_names[r.node_ids.index(s)] for s in r.sinks)
            text += f" Nodes that link to nothing were made absorbing (1 on the diagonal): {names}."
        self.info.setText(text)


class ANPResultsPage(QWidget):
    jump = Signal(str)

    def __init__(self, model: ANPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.ranking = RankingPanel()
        self.nodes = readonly_table(["Node", "Cluster", "Limit priority", "Normalized by cluster"])
        self.consistency = ConsistencyTable()
        self.consistency.jump.connect(self.jump)
        self.info = note("")
        self.warnings = warnings_label()

        lower = QSplitter(Qt.Orientation.Horizontal)
        nb = QWidget()
        nl = QVBoxLayout(nb)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(heading("All nodes"))
        nl.addWidget(self.nodes)
        cb = QWidget()
        cl = QVBoxLayout(cb)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(heading("Consistency of judgments"))
        cl.addWidget(self.consistency)
        lower.addWidget(nb)
        lower.addWidget(cb)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(self.ranking)
        vsplit.addWidget(lower)

        lay = QVBoxLayout(self)
        lay.addWidget(heading("Ranking of alternatives", 1.15))
        lay.addWidget(self.info)
        lay.addWidget(self.warnings)
        lay.addWidget(vsplit, 1)

    def set_model(self, model: ANPModel) -> None:
        self.model = model
        self.refresh()

    def refresh(self) -> None:
        r = self.model.evaluate()
        self.ranking.fill(r.alternative_names, r.alternative_scores)
        self.nodes.setRowCount(len(r.node_ids))
        for k in range(len(r.node_ids)):
            self.nodes.setItem(k, 0, QTableWidgetItem(r.node_names[k]))
            self.nodes.setItem(k, 1, QTableWidgetItem(r.node_clusters[k]))
            self.nodes.setItem(k, 2, num_item(float(r.priorities[k])))
            self.nodes.setItem(k, 3, num_item(float(r.normalized[k])))
        start = self.model.node(r.start_node).name if r.start_node else "average of all columns"
        alt = self.model.effective_alternatives_cluster()
        self.info.setText(
            f"Alternatives cluster: <b>{alt.name if alt else '—'}</b> · read from: <b>{start}</b> · "
            f"limit matrix: {r.limit_status}."
        )
        bad, incomplete = self.consistency.fill(self.model, r)
        warnings = self.model.warnings()
        if bad:
            warnings.append(f"{bad} comparison(s) are inconsistent (CR > 0.10). Double-click one below to revise it.")
        if incomplete:
            warnings.append(f"{incomplete} comparison(s) are incomplete; unjudged pairs count as equal.")
        show_warnings(self.warnings, warnings)


class ANPEditor(QTabWidget):
    modified = Signal()
    message = Signal(str)

    def __init__(self, model: ANPModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.network = NetworkPage(model)
        self.connections = ConnectionsPage(model)
        self.comparisons = ComparisonsPage(model)
        self.supermatrix = SupermatrixPage(model)
        self.results = ANPResultsPage(model)
        self.sensitivity = SensitivityPage(model)
        self.addTab(self.network, "1 · Network")
        self.addTab(self.connections, "2 · Connections")
        self.addTab(self.comparisons, "3 · Comparisons")
        self.addTab(self.supermatrix, "4 · Supermatrices")
        self.addTab(self.results, "5 · Results")
        self.addTab(self.sensitivity, "6 · Sensitivity")
        for page in (self.network, self.connections, self.comparisons):
            page.changed.connect(self.modified)
        self.comparisons.message.connect(self.message)
        self.results.jump.connect(self.jump_to)
        self.currentChanged.connect(self._tab_changed)

    def set_model(self, model: ANPModel) -> None:
        self.model = model
        for k in range(self.count()):
            self.widget(k).model = model
        self.network.refresh()
        self._tab_changed(self.currentIndex())

    def _tab_changed(self, index: int) -> None:
        page = self.widget(index)
        if page is not self.network:
            page.refresh()
        else:
            self.network.refresh()

    def jump_to(self, key: str) -> None:
        self.setCurrentWidget(self.comparisons)
        self.comparisons.select_key(key)
