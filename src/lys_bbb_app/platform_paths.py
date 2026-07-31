"""Platform-specific default paths used by the desktop shell."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
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
        return active_home / "Library" / "Application Support" / "LYS IRM"
    if active_platform.startswith("win"):
        local_app_data = active_environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else active_home / "AppData" / "Local"
        return base / "LYS IRM"
    xdg_data_home = active_environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else active_home / ".local" / "share"
    return base / "lys-irm"


def _legacy_user_data_directories() -> tuple[Path, ...]:
    """Return historical product-data roots for read-only release discovery."""

    active_home = Path.home()
    if sys.platform == "darwin":
        return (
            active_home / "Library" / "Application Support" / "LYS BBB",
        )
    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else active_home / "AppData" / "Local"
        )
        return (base / "LYS BBB", base / "LYS_BBB")
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else active_home / ".local" / "share"
    return (base / "lys-bbb",)


def _model_release_path(directory_name: str) -> Path:
    canonical = default_user_data_directory() / "models" / directory_name
    if canonical.is_dir():
        return canonical
    for legacy_root in _legacy_user_data_directories():
        legacy = legacy_root / "models" / directory_name
        if legacy.is_dir():
            return legacy
    return canonical


def default_t1_brain_mask_release_path() -> Path:
    """Return the expected location of the reviewed local T1 model release."""

    return _model_release_path("rs2net-m-seam-v1")


def default_t2_model_release_path() -> Path:
    """Return the visible and internal default: LYS v3 nnU-Net fold 1."""

    return t2_model_choice("lys-v3-standard3d-nnunet-fold1").path


@dataclass(frozen=True, slots=True)
class T2ModelChoice:
    id: str
    label: str
    description: str
    path: Path
    default: bool = False


def _checked_in_model_path(directory_name: str) -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "models"
        / directory_name
    )


def _installed_or_checked_in_model_path(directory_name: str) -> Path:
    installed = _model_release_path(directory_name)
    checked_in = _checked_in_model_path(directory_name)
    return installed if installed.is_dir() else checked_in


def t2_model_choices() -> tuple[T2ModelChoice, ...]:
    """Return all deliberate settings choices with fold 1 first and default."""

    nnunet_root = _installed_or_checked_in_model_path(
        "lys_v3_standard3d_nnunet"
    )
    small = _installed_or_checked_in_model_path("lys_v1_small_ratlesnetv2")
    if not small.is_dir():
        small = _model_release_path("ratlesnetv2-lys-v1")
    return (
        T2ModelChoice(
            id="lys-v3-standard3d-nnunet-fold1",
            label="Standard model",
            description="Default model.",
            path=nnunet_root,
            default=True,
        ),
        T2ModelChoice(
            id="lys-v1-small-ratlesnetv2",
            label="Small model",
            description="Model with a smaller packaged footprint.",
            path=small,
        ),
        T2ModelChoice(
            id="lys-v3-standard3d-nnunet-folds0-1",
            label="Larger model",
            description="Larger optional model.",
            path=nnunet_root / "variants" / "folds_0_1",
        ),
    )


def t2_model_display_label(model_id: str) -> str:
    """Return a non-technical model name for user-facing UI copy."""

    normalized = model_id.casefold()
    if normalized == "lys-v3-standard3d-nnunet-folds0-1":
        return "Larger model"
    if normalized == "lys-v3-standard3d-nnunet-fold1":
        return "Standard model"
    if normalized == "lys-v1-small-ratlesnetv2" or normalized.startswith(
        "ratlesnetv2-"
    ):
        return "Small model"
    return "T2 lesion model"


def t2_model_choice_id_for_release(model_id: str) -> str:
    """Map persisted release IDs back to their deliberate Settings choice."""

    if t2_model_display_label(model_id) == "Small model":
        return "lys-v1-small-ratlesnetv2"
    return model_id


def t2_model_choice(model_id: str) -> T2ModelChoice:
    try:
        return next(choice for choice in t2_model_choices() if choice.id == model_id)
    except StopIteration as exc:
        raise KeyError(f"Unknown T2 model choice: {model_id}") from exc


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
                os.environ.get("Program Files"),
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
        _installed_or_checked_in_model_path("lys_v1_small_ratlesnetv2"),
        downloads / "LYS_v1_RatLesNetV2_inference",
        downloads / "LYS_v1_RatLesNetV2_windows_inference",
        downloads / "LYS_v1_RatLesNetV2_mac_inference",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])
