"""Verify the colleague-facing Windows handoff archive."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts" / "packaging" / "build_windows_handoff.py"
BUNDLE_ROOT = "LYS-BBB-Windows/"


def test_windows_handoff_builder_creates_a_verified_one_click_bundle(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source",
            str(PROJECT_ROOT),
            "--output-directory",
            str(tmp_path),
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert BUNDLE_ROOT + "Setup-LYS-BBB.cmd" in names
        assert BUNDLE_ROOT + "Setup-LYS-BBB.ps1" in names
        assert BUNDLE_ROOT + "Launch-LYS-BBB.ps1" in names
        assert BUNDLE_ROOT + "Install-LYS-BBB.sh" in names
        assert BUNDLE_ROOT + "lys-bbb.ico" in names
        assert BUNDLE_ROOT + "handoff-manifest.json" in names
        assert BUNDLE_ROOT + "app/pyproject.toml" in names
        assert BUNDLE_ROOT + "app/src/lys_bbb_app/main.py" in names
        assert (
            BUNDLE_ROOT + "app/packaging/windows/environment-wsl.yml"
            in names
        )

        icon = archive.read(BUNDLE_ROOT + "lys-bbb.ico")
        assert icon[:6] == b"\x00\x00\x01\x00\x01\x00"

        checksum_lines = archive.read(
            BUNDLE_ROOT + "SHA256SUMS.txt"
        ).decode().splitlines()
        for line in checksum_lines:
            expected, relative = line.split("  ", maxsplit=1)
            content = archive.read(BUNDLE_ROOT + relative)
            assert hashlib.sha256(content).hexdigest() == expected


def test_wsl_installer_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROJECT_ROOT / "packaging/windows/Install-LYS-BBB.sh")],
        check=True,
    )
