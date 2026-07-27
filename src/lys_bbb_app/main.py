"""Application launcher for the MRI Tool desktop app."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from lys_bbb_app.features import active_features
from lys_bbb_app.ui.main_window import MainWindow
from lys_bbb_app.ui.theme import apply_theme


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the MRI Tool desktop application."
    )
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="optional study directory/project.json or legacy .lysbbb project to open",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("MRI Tool")
    app.setOrganizationName("MRI Tool")
    icon_path = Path(os.environ.get("LYS_BBB_ICON", ""))
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_theme(app)

    window = MainWindow(features=active_features())
    if args.project is not None:
        window.open_project_path(args.project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
