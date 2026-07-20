"""Focused tests for the non-Qt ITK-SNAP handoff adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from lys_bbb_app.infrastructure import external_viewer


def test_find_itksnap_accepts_a_macos_application_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "ITK-SNAP.app"
    executable = bundle / "Contents" / "MacOS" / "ITK-SNAP"
    executable.parent.mkdir(parents=True)
    executable.write_text("viewer")

    assert external_viewer.find_itksnap(bundle) == executable.resolve()


def test_launch_itksnap_passes_one_existing_image_as_main_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "itksnap"
    executable.write_text("viewer")
    image = tmp_path / "scan.nii.gz"
    image.write_bytes(b"nifti")
    calls: list[tuple[list[str], bool]] = []

    class Process:
        pid = 42

    def popen(command: list[str], *, start_new_session: bool):
        calls.append((command, start_new_session))
        return Process()

    monkeypatch.setattr(external_viewer.subprocess, "Popen", popen)

    launch = external_viewer.launch_itksnap(image, executable)

    assert calls == [
        ([str(executable.resolve()), "-g", str(image.resolve())], True)
    ]
    assert launch.image_path == image.resolve()
    assert launch.process_id == 42


def test_launch_itksnap_rejects_a_missing_image(tmp_path: Path) -> None:
    with pytest.raises(external_viewer.ExternalViewerError, match="unavailable"):
        external_viewer.launch_itksnap(tmp_path / "missing.nii.gz")
