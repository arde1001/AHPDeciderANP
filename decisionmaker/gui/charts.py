"""Matplotlib charts embedded in Qt: alternative ranking and sensitivity."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy

from ..core.sensitivity import SensitivityResult
from .theme import chart_theme, series_color

_FONT = {"family": "sans-serif", "size": 9}


class ChartCanvas(FigureCanvasQTAgg):
    """A figure that picks up the application's light/dark theme on every draw."""

    def __init__(self, parent=None):
        self.figure = Figure(figsize=(5, 3), layout="constrained")
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)

    def _axes(self) -> tuple:
        theme = chart_theme()
        self.figure.clear()
        self.figure.set_facecolor(theme.surface)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(theme.surface)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(theme.baseline)
        ax.tick_params(colors=theme.muted, labelcolor=theme.text_secondary, labelsize=9, length=0)
        ax.set_axisbelow(True)
        return ax, theme

    def _message(self, text: str) -> None:
        ax, theme = self._axes()
        ax.set_axis_off()
        ax.text(0.5, 0.5, text, ha="center", va="center", color=theme.muted, fontdict=_FONT, transform=ax.transAxes)
        self.draw_idle()


class RankingChart(ChartCanvas):
    """Horizontal bars of alternative scores, best at the top (a single series)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: tuple[list[str], np.ndarray] | None = None

    def plot(self, names: list[str], scores: np.ndarray) -> None:
        self._data = (list(names), np.asarray(scores, float))
        self._redraw()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._redraw()

    def _redraw(self) -> None:
        if not self._data or not len(self._data[0]):
            self._message("Add alternatives to see the ranking")
            return
        names, scores = self._data
        ax, theme = self._axes()
        order = np.argsort(-scores)
        y = np.arange(len(order))[::-1]
        # bars at most ~22 px thick: convert pixels to data units of the y axis
        px_per_unit = max(1.0, self.height() * 0.8 / max(1, len(order)))
        height = min(0.7, 22 / px_per_unit)
        ax.barh(y, scores[order], height=height, color=theme.series[0], linewidth=0)
        top = float(scores.max()) if scores.max() > 0 else 1.0
        for yy, k in zip(y, order, strict=True):
            ax.text(scores[k] + top * 0.015, yy, f"{scores[k]:.3f}", va="center", color=theme.text_primary, fontdict=_FONT)
        ax.set_yticks(y, [names[k] for k in order])
        ax.set_xlim(0, top * 1.18)
        ax.set_ylim(-0.7, len(order) - 0.3)
        ax.xaxis.grid(True, color=theme.grid, linewidth=0.8)
        ax.set_xlabel("Priority", color=theme.text_secondary, fontdict=_FONT)
        self.draw_idle()


class SensitivityChart(ChartCanvas):
    """Alternative scores as one criterion's weight sweeps 0 → 1. Click to move the probe."""

    weightClicked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: SensitivityResult | None = None
        self._probe = None
        self._item_name = ""
        self.mpl_connect("button_press_event", self._on_click)
        self.mpl_connect("motion_notify_event", self._on_drag)

    def plot(self, result: SensitivityResult | None, item_name: str, probe: float) -> None:
        self._result = result
        self._item_name = item_name
        if result is None or result.scores.shape[1] == 0:
            self._message("Choose a comparison and an element to analyze")
            return
        ax, theme = self._axes()
        self._ax, self._theme = ax, theme
        x = result.weights
        n = result.scores.shape[1]
        for k in range(n):
            ax.plot(
                x, result.scores[:, k], color=series_color(theme, k), linewidth=2,
                solid_capstyle="round", solid_joinstyle="round", label=result.alternative_names[k],
            )
        ymax = max(0.05, float(result.scores.max()) * 1.1)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, ymax)
        ax.yaxis.grid(True, color=theme.grid, linewidth=0.8)
        ax.axvline(result.current_weight, color=theme.muted, linewidth=1)
        ax.text(
            result.current_weight, ymax, " current", color=theme.text_secondary, va="top",
            ha="left" if result.current_weight < 0.85 else "right", fontdict=_FONT,
        )
        for rev in result.reversals:
            ax.plot([rev.weight], [np.interp(rev.weight, x, result.scores[:, rev.after])], "o",
                    markersize=6, color=theme.text_primary, markeredgecolor=theme.surface, markeredgewidth=2)
        self._probe = ax.axvline(probe, color=theme.text_primary, linewidth=1.2)
        ax.set_xlabel(f"Weight of “{item_name}”", color=theme.text_secondary, fontdict=_FONT)
        ax.set_ylabel("Alternative priority", color=theme.text_secondary, fontdict=_FONT)
        legend = ax.legend(
            loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False, fontsize=9, labelcolor=theme.text_primary,
            handlelength=1.2,
        )
        legend.set_in_layout(True)
        self.draw_idle()

    def move_probe(self, weight: float) -> None:
        if self._probe is not None:
            self._probe.set_xdata([weight, weight])
            self.draw_idle()

    def _on_click(self, event) -> None:
        if event.inaxes is not None and event.xdata is not None and self._result is not None:
            self.weightClicked.emit(float(np.clip(event.xdata, 0, 1)))

    def _on_drag(self, event) -> None:
        if event.button == 1:
            self._on_click(event)
