"""Launch trusted external image viewers without coupling them to Qt widgets."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ExternalViewerError(RuntimeError):
    """Raised when an external viewer cannot be resolved or launched."""


@dataclass(frozen=True)
class ViewerLaunch:
    executable: Path
    image_path: Path
    process_id: int
    segmentation_path: Path | None = None


def find_itksnap(explicit_path: Path | str | None = None) -> Path:
    """Resolve ITK-SNAP from a configured path, PATH, or the macOS app bundle."""

    if explicit_path is not None and str(explicit_path).strip():
        configured = Path(explicit_path).expanduser()
        candidates = _configured_candidates(configured)
    else:
        candidates = tuple(
            Path(value)
            for value in (
                shutil.which("itksnap"),
                shutil.which("ITK-SNAP"),
                "/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP",
                "/Applications/ITK-SNAP.app/Contents/MacOS/itksnap",
            )
            if value
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    configured_hint = f" at {explicit_path}" if explicit_path else ""
    raise ExternalViewerError(
        "ITK-SNAP was not found"
        f"{configured_hint}. Install it, add itksnap to PATH, or update the external "
        "editor path in Settings."
    )


def launch_itksnap(
    image_path: Path,
    viewer_path: Path | str | None = None,
    segmentation_path: Path | None = None,
) -> ViewerLaunch:
    """Open an MRI image and, optionally, a matching segmentation in ITK-SNAP."""

    image = Path(image_path).expanduser().resolve()
    if not image.is_file():
        raise ExternalViewerError(f"The MRI image is unavailable: {image}")
    segmentation = (
        Path(segmentation_path).expanduser().resolve()
        if segmentation_path is not None
        else None
    )
    if segmentation is not None and not segmentation.is_file():
        raise ExternalViewerError(
            f"The segmentation is unavailable: {segmentation}"
        )
    executable = find_itksnap(viewer_path)
    command = [str(executable), "-g", str(image)]
    if segmentation is not None:
        command.extend(("-s", str(segmentation)))
    try:
        process = subprocess.Popen(
            command,
            start_new_session=True,
        )
    except OSError as exc:
        raise ExternalViewerError(f"ITK-SNAP could not be launched: {exc}") from exc
    return ViewerLaunch(executable, image, process.pid, segmentation)


def _configured_candidates(path: Path) -> tuple[Path, ...]:
    if path.suffix.casefold() == ".app" or path.is_dir() and path.name.endswith(".app"):
        return (
            path / "Contents" / "MacOS" / "ITK-SNAP",
            path / "Contents" / "MacOS" / "itksnap",
        )
    return (path,)
