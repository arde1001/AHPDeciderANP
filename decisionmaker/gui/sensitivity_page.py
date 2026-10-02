"""What-if analysis: sweep one element's weight and watch the ranking change."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.sensitivity import SensitivityResult, run_sensitivity
from .charts import SensitivityChart
from .widgets import heading, note, num_item, readonly_table

_STEPS = 1000


class SensitivityPage(QWidget):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.result: SensitivityResult | None = None

        self.set_combo = QComboBox()
        self.set_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.item_combo = QComboBox()
        self.set_combo.currentIndexChanged.connect(self._set_changed)
        self.item_combo.currentIndexChanged.connect(self._recompute)
        form = QFormLayout()
        form.addRow("Comparison:", self.set_combo)
        form.addRow("Vary the weight of:", self.item_combo)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _STEPS)
        self.slider.valueChanged.connect(self._probe_moved)
        self.probe_label = QLabel()
        probe_row = QHBoxLayout()
        probe_row.addWidget(QLabel("What if the weight were:"))
        probe_row.addWidget(self.slider, 1)
        probe_row.addWidget(self.probe_label)

        self.chart = SensitivityChart()
        self.chart.weightClicked.connect(lambda w: self.slider.setValue(round(w * _STEPS)))
        self.table = readonly_table(["Alternative", "Priority at this weight", "Rank"])
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(heading("Ranking at the chosen weight"))
        sl.addWidget(self.table, 1)
        sl.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.chart)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        lay = QVBoxLayout(self)
        lay.addWidget(note(
            "Pick an element and sweep its local weight from 0 to 1. The other elements in the same comparison "
            "keep their relative proportions. Where lines cross, the ranking of those alternatives changes; "
            "dots mark changes of the best alternative. Click or drag on the chart to probe a weight."
        ))
        lay.addLayout(form)
        lay.addLayout(probe_row)
        lay.addWidget(split, 1)

    def set_model(self, model) -> None:
        self.model = model
        self.refresh()

    def refresh(self) -> None:
        key = self.set_combo.currentData()
        item = self.item_combo.currentIndex()
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        for s in self.model.comparison_sets():
            self.set_combo.addItem(s.title, s.key)
        k = self.set_combo.findData(key)
        self.set_combo.setCurrentIndex(k if k >= 0 else 0)
        self.set_combo.blockSignals(False)
        self._set_changed(keep_item=item if k >= 0 else 0)

    def _set_changed(self, _index=None, keep_item: int = 0) -> None:
        key = self.set_combo.currentData()
        s = next((x for x in self.model.comparison_sets() if x.key == key), None)
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        if s is not None:
            self.item_combo.addItems(s.item_names)
            self.item_combo.setCurrentIndex(min(max(keep_item, 0), len(s.item_names) - 1))
        self.item_combo.blockSignals(False)
        self._recompute()

    def _recompute(self) -> None:
        key = self.set_combo.currentData()
        index = self.item_combo.currentIndex()
        if key is None or index < 0:
            self.result = None
            self.chart.plot(None, "", 0)
            self.table.setRowCount(0)
            self.summary.setText("")
            return
        self.result = run_sensitivity(self.model, key, index)
        self.slider.blockSignals(True)
        self.slider.setValue(round(self.result.current_weight * _STEPS))
        self.slider.blockSignals(False)
        self.chart.plot(self.result, self.item_combo.currentText(), self.result.current_weight)
        self._probe_moved(self.slider.value())

    def _probe_moved(self, value: int) -> None:
        weight = value / _STEPS
        self.probe_label.setText(f"{weight:.3f}")
        r = self.result
        if r is None or r.scores.shape[1] == 0:
            return
        self.chart.move_probe(weight)
        scores = r.scores_at(weight)
        order = sorted(range(len(scores)), key=lambda k: -scores[k])
        self.table.setRowCount(len(order))
        for rank, k in enumerate(order):
            self.table.setItem(rank, 0, QTableWidgetItem(r.alternative_names[k]))
            self.table.setItem(rank, 1, num_item(float(scores[k]), 4, pct=True))
            self.table.setItem(rank, 2, num_item(rank + 1, 0))

        name = self.item_combo.currentText()
        lines = [f"Current weight of “{name}”: <b>{r.current_weight:.3f}</b>."]
        if not r.reversals:
            best = r.alternative_names[int(r.scores_at(r.current_weight).argmax())]
            lines.append(f"The best alternative (“{best}”) does not change over the whole range: this result is robust to “{name}”.")
        else:
            lines.append("The best alternative changes at:")
            items = "".join(
                f"<li>weight ≈ {rev.weight:.3f}: “{r.alternative_names[rev.before]}” → “{r.alternative_names[rev.after]}”</li>"
                for rev in r.reversals
            )
            lines.append(f"<ul style='margin:0'>{items}</ul>")
            nearest = min(r.reversals, key=lambda rev: abs(rev.weight - r.current_weight))
            lines.append(f"Nearest change is {abs(nearest.weight - r.current_weight):.3f} away from the current weight.")
        self.summary.setText("<br>".join(lines))
