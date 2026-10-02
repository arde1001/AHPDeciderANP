"""Colors for charts and status indicators, following the Qt light/dark palette."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ChartTheme:
    dark: bool
    surface: str
    text_primary: str
    text_secondary: str
    muted: str
    grid: str
    baseline: str
    series: tuple[str, ...]


# Categorical slots in fixed order (validated for colorblind separation on the
# adjacent pairlist); the dark column is the same hues stepped for dark surfaces.
_SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
_SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")

STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"
STATUS_CRITICAL = "#d03b3b"


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def chart_theme() -> ChartTheme:
    app = QApplication.instance()
    surface = app.palette().color(QPalette.ColorRole.Base).name() if app else "#fcfcfb"
    if is_dark():
        return ChartTheme(True, surface, "#ffffff", "#c3c2b7", "#898781", "#2c2c2a", "#383835", _SERIES_DARK)
    return ChartTheme(False, surface, "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", _SERIES_LIGHT)


def series_color(theme: ChartTheme, index: int) -> str:
    """Color for the entity at `index`. Past eight series, extras fold into muted gray."""
    return theme.series[index] if index < len(theme.series) else theme.muted


# The fill-strength good/warning steps are too light to read as text on a light
# surface, so light mode uses darker text steps of the same hues.
_STATUS_TEXT_LIGHT = {True: "#006300", None: "#8f5f00", False: STATUS_CRITICAL}
_STATUS_TEXT_DARK = {True: STATUS_GOOD, None: STATUS_WARNING, False: "#e66767"}


def status_color(ok: bool | None) -> QColor:
    """Text color for a status: green consistent, red inconsistent, amber incomplete.

    Always shown next to an icon and a label, never as the only signal.
    """
    return QColor((_STATUS_TEXT_DARK if is_dark() else _STATUS_TEXT_LIGHT)[ok])
