"""Focused tests for cross-platform desktop defaults."""

from __future__ import annotations

from pathlib import Path

from lys_bbb_app.platform_paths import default_user_data_directory


def test_default_user_data_directory_uses_macos_convention() -> None:
    assert default_user_data_directory(
        platform="darwin",
        environ={},
        home=Path("/Users/researcher"),
    ) == Path("/Users/researcher/Library/Application Support/LYS BBB")


def test_default_user_data_directory_uses_windows_local_app_data() -> None:
    assert default_user_data_directory(
        platform="win32",
        environ={"LOCALAPPDATA": r"C:\Users\researcher\AppData\Local"},
        home=Path("/unused"),
    ) == Path(r"C:\Users\researcher\AppData\Local") / "LYS BBB"


def test_default_user_data_directory_uses_linux_xdg_convention() -> None:
    assert default_user_data_directory(
        platform="linux",
        environ={"XDG_DATA_HOME": "/home/researcher/data"},
        home=Path("/home/researcher"),
    ) == Path("/home/researcher/data/lys-bbb")
