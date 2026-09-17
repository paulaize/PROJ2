"""Focused tests for cross-platform desktop defaults."""

from __future__ import annotations

from pathlib import Path

from lys_bbb_app import platform_paths
from lys_bbb_app.platform_paths import default_user_data_directory


def test_offline_models_take_precedence_over_an_old_install(tmp_path, monkeypatch) -> None:
    models = tmp_path / "release" / "models"
    standard = models / "lys_v3_standard3d_nnunet"
    standard.mkdir(parents=True)
    monkeypatch.setenv("LYS_IRM_MODELS_DIRECTORY", str(models))
    assert platform_paths.default_t2_model_release_path() == standard


def test_default_user_data_directory_uses_macos_convention() -> None:
    assert default_user_data_directory(
        platform="darwin",
        environ={},
        home=Path("/Users/researcher"),
    ) == Path("/Users/researcher/Library/Application Support/LYS IRM")


def test_default_user_data_directory_uses_windows_local_app_data() -> None:
    assert default_user_data_directory(
        platform="win32",
        environ={"LOCALAPPDATA": r"C:\Users\researcher\AppData\Local"},
        home=Path("/unused"),
    ) == Path(r"C:\Users\researcher\AppData\Local") / "LYS-IRM"


def test_default_user_data_directory_uses_linux_xdg_convention() -> None:
    assert default_user_data_directory(
        platform="linux",
        environ={"XDG_DATA_HOME": "/home/researcher/data"},
        home=Path("/home/researcher"),
    ) == Path("/home/researcher/data/lys-irm")


def test_model_release_discovery_falls_back_to_historical_product_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    legacy_release = (
        tmp_path
        / "Library"
        / "Application Support"
        / "LYS BBB"
        / "models"
        / "rs2net-m-seam-v1"
    )
    legacy_release.mkdir(parents=True)
    monkeypatch.setattr(platform_paths.sys, "platform", "darwin")
    monkeypatch.setattr(platform_paths.Path, "home", lambda: tmp_path)

    assert platform_paths.default_t1_brain_mask_release_path() == legacy_release
