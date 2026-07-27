"""Platform-specific default paths used by the desktop shell."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path


def default_user_data_directory(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the conventional per-user application-data directory."""

    active_platform = platform or sys.platform
    active_environ = environ if environ is not None else os.environ
    active_home = home or Path.home()
    if active_platform == "darwin":
        return active_home / "Library" / "Application Support" / "LYS BBB"
    if active_platform.startswith("win"):
        local_app_data = active_environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else active_home / "AppData" / "Local"
        return base / "LYS BBB"
    xdg_data_home = active_environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else active_home / ".local" / "share"
    return base / "lys-bbb"


def default_t1_brain_mask_release_path() -> Path:
    """Return the expected location of the reviewed local T1 model release."""

    return default_user_data_directory() / "models" / "rs2net-m-seam-v1"


def default_t2_model_release_path() -> Path:
    """Return the expected location of the bundled frozen T2 model release."""

    return default_user_data_directory() / "models" / "ratlesnetv2-lys-v1"


def default_itksnap_editor_path() -> str:
    """Return a usable ITK-SNAP default, or blank to request PATH discovery."""

    on_path = shutil.which("itksnap") or shutil.which("ITK-SNAP")
    if on_path:
        return on_path
    if sys.platform == "darwin":
        return "/Applications/ITK-SNAP.app"
    if sys.platform.startswith("win"):
        roots = tuple(
            Path(value)
            for value in (
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramW6432"),
                os.environ.get("LOCALAPPDATA"),
            )
            if value
        )
        names = ("ITK-SNAP 4.4", "ITK-SNAP 4.2", "ITK-SNAP")
        for root in roots:
            for name in names:
                for relative in (
                    Path(name) / "bin" / "ITK-SNAP.exe",
                    Path(name) / "ITK-SNAP.exe",
                ):
                    candidate = root / relative
                    if candidate.is_file():
                        return str(candidate)
    return ""


def default_t2_model_release_suggestion() -> Path:
    """Return the first plausible generic or legacy T2 release location."""

    downloads = Path.home() / "Downloads"
    candidates = (
        default_t2_model_release_path(),
        downloads / "LYS_v1_RatLesNetV2_inference",
        downloads / "LYS_v1_RatLesNetV2_windows_inference",
        downloads / "LYS_v1_RatLesNetV2_mac_inference",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])
