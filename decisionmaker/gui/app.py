"""Entry point: `decisionmaker [project.json]` or `python -m decisionmaker`."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("QtAgg")

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AHP / ANP Decision Maker")
    app.setDesktopFileName("decisionmaker")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
    window = MainWindow()
    for arg in app.arguments()[1:]:
        if Path(arg).is_file():
            window.open_path(Path(arg))
            break
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
