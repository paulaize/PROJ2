"""Verify the colleague-facing Windows handoff archive."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts" / "packaging" / "build_windows_handoff.py"
BUNDLE_ROOT = "LYS-BBB-Windows/"
NATIVE_BUNDLE_ROOT = "LYS-BBB-Windows-Native-No-ANTs-v1/"
ANTSPYX_BUNDLE_ROOT = "LYS-BBB-Windows-Native-ANTsPyx-Preview-v1/"


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


def test_native_windows_bundle_contains_no_ants_or_wsl_runtime(
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
            "--target",
            "native-no-ants",
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert NATIVE_BUNDLE_ROOT + "Setup-LYS-BBB.cmd" in names
        assert NATIVE_BUNDLE_ROOT + "Setup-LYS-BBB.ps1" in names
        assert NATIVE_BUNDLE_ROOT + "Launch-LYS-BBB.ps1" in names
        assert NATIVE_BUNDLE_ROOT + "Install-LYS-BBB.sh" not in names
        environment_path = (
            NATIVE_BUNDLE_ROOT
            + "app/packaging/windows-native/environment-win64.yml"
        )
        assert environment_path in names
        environment = archive.read(environment_path).decode()
        assert "simpleitk=2.5.5" in environment.casefold()
        assert "\n  - ants" not in environment.casefold()

        launcher = archive.read(
            NATIVE_BUNDLE_ROOT + "Launch-LYS-BBB.ps1"
        ).decode()
        assert "windows_native_no_ants_v1" in launcher
        assert "wsl.exe" not in launcher.casefold()

        manifest = json.loads(
            archive.read(
                NATIVE_BUNDLE_ROOT + "handoff-manifest.json"
            )
        )
        assert manifest["target"]["runtime"].startswith("native Windows")
        assert (
            manifest["target"]["feature_profile"]
            == "windows_native_no_ants_v1"
        )

        checksum_lines = archive.read(
            NATIVE_BUNDLE_ROOT + "SHA256SUMS.txt"
        ).decode().splitlines()
        for line in checksum_lines:
            expected, relative = line.split("  ", maxsplit=1)
            content = archive.read(NATIVE_BUNDLE_ROOT + relative)
            assert hashlib.sha256(content).hexdigest() == expected


def test_native_antspyx_preview_bundle_is_windows_only_and_pinned(
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
            "--target",
            "native-antspyx-preview",
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert ANTSPYX_BUNDLE_ROOT + "Setup-LYS-BBB.cmd" in names
        assert ANTSPYX_BUNDLE_ROOT + "Install-LYS-BBB.sh" not in names
        environment_path = (
            ANTSPYX_BUNDLE_ROOT
            + "app/packaging/windows-native/environment-win64-antspyx.yml"
        )
        environment = archive.read(environment_path).decode().casefold()
        assert "\n  - ants=" not in environment
        assert "vc14_runtime" in environment
        setup = archive.read(
            ANTSPYX_BUNDLE_ROOT + "Setup-LYS-BBB.ps1"
        ).decode().casefold()
        assert "antspyx==0.6.3" in setup
        assert "antspyx-0.6.3-cp311-cp311-win_amd64.whl" in setup
        assert (
            "39a29ba5abbf3475dea70cf0d0a2472e34a5c854f99d2f08204a288f1f5aeac4"
            in setup
        )

        manifest = json.loads(
            archive.read(
                ANTSPYX_BUNDLE_ROOT + "handoff-manifest.json"
            )
        )
        assert manifest["target"]["feature_profile"] == (
            "windows_native_antspyx_preview_v1"
        )
        launcher = archive.read(
            ANTSPYX_BUNDLE_ROOT + "Launch-LYS-BBB.ps1"
        ).decode()
        assert "wsl.exe" not in launcher.casefold()
