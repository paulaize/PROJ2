"""Application launcher for the connected desktop MVP preview."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from lys_bbb_app.ui.main_window import MainWindow
from lys_bbb_app.ui.theme import apply_theme


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the LYS BBB scientific workflow desktop application."
    )
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="optional existing legacy .lysbbb project to open",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="open the connected MVP design preview with synthetic subjects",
    )
    args = parser.parse_args(argv)
    if args.demo and args.project is not None:
        parser.error("a project path and --demo cannot be used together")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("LYS BBB Scientific Workflows")
    app.setOrganizationName("LYS BBB")
    apply_theme(app)

    window = MainWindow()
    if args.demo:
        window.open_design_preview()
    elif args.project is not None:
        window.open_project_path(args.project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
