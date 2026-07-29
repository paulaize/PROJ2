"""Application launcher for the LYS IRM desktop app."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from lys_bbb_app.features import active_features
from lys_bbb_app.ui.main_window import MainWindow
from lys_bbb_app.ui.theme import apply_theme


def application_icon_path(
    environ: Mapping[str, str] = os.environ,
) -> Path | None:
    """Return the launcher override or the checked-in cross-platform app icon."""

    override = environ.get("LYS_IRM_ICON")
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_file():
            return override_path

    source_tree_icon = (
        Path(__file__).resolve().parents[2]
        / "packaging"
        / "assets"
        / "lys-irm-icon.png"
    )
    return source_tree_icon if source_tree_icon.is_file() else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the LYS IRM desktop application."
    )
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="optional study directory or project.json manifest to open",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("LYS IRM")
    app.setOrganizationName("LYS IRM")
    icon_path = application_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_theme(app)

    window = MainWindow(features=active_features())
    if args.project is not None:
        window.open_project_path(args.project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
