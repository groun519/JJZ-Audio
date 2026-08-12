from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from jang_app.qt_app.separation_incremental_review import (
    IncrementalSeparationReviewWindow,
)
from jang_app.qt_app.theme import build_stylesheet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open the incremental separation review window."
    )
    parser.add_argument("review", type=Path)
    parser.add_argument("--theme", choices=("dark", "white"), default="dark")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyleSheet(build_stylesheet(args.theme))
    window = IncrementalSeparationReviewWindow(args.review)
    window.set_theme_mode(args.theme)
    if args.screenshot is not None:
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    if args.screenshot is not None:
        app.processEvents()
        target = args.screenshot.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(target)):
            raise RuntimeError(f"Could not save review screenshot: {target}")
        window.close()
        print(target)
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
