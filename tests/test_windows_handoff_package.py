"""Verify the colleague-facing Windows handoff archive."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.packaging.build_windows_handoff import _bundle_runtime, build_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts" / "packaging" / "build_windows_handoff.py"
BUNDLE_ROOT = "LYS-IRM-Windows/"
NATIVE_BUNDLE_ROOT = "LYS-IRM-Windows-Native/"


def test_native_colleague_build_requires_runtime_and_excludes_t1(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="requires --runtime-directory"):
        build_bundle(PROJECT_ROOT, tmp_path, allow_dirty=True,
                     bundle_checked_in_t2_models=True)
    with pytest.raises(RuntimeError, match="must not contain a T1"):
        build_bundle(PROJECT_ROOT, tmp_path, allow_dirty=True, t1_model_release=tmp_path)


def test_runtime_cannot_be_reused_after_dependency_changes(tmp_path) -> None:
    from pathlib import PurePosixPath

    (tmp_path / "windows-runtime.zip").write_bytes(b"fixture runtime")
    manifest = {
        "platform": "win-64", "profile": "t2-only", "relocation_test": "passed",
        "pip_check": "passed", "environment_sha256": "old-dependency-specification",
    }
    (tmp_path / "runtime-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="environment_sha256"):
        _bundle_runtime({}, source=PROJECT_ROOT, bundle_root=PurePosixPath("test"),
                        runtime_directory=tmp_path)


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
            "--target",
            "wsl",
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
        assert BUNDLE_ROOT + "Setup-LYS-IRM.cmd" in names
        assert BUNDLE_ROOT + "Setup-LYS-IRM.ps1" in names
        assert BUNDLE_ROOT + "Launch-LYS-IRM.ps1" in names
        assert BUNDLE_ROOT + "Install-LYS-IRM.sh" in names
        assert BUNDLE_ROOT + "lys-irm.ico" in names
        assert BUNDLE_ROOT + "handoff-manifest.json" in names
        assert BUNDLE_ROOT + "app/pyproject.toml" in names
        assert BUNDLE_ROOT + "app/src/lys_bbb_app/main.py" in names
        assert (
            BUNDLE_ROOT + "app/packaging/windows/environment-wsl.yml"
            in names
        )
        environment = archive.read(
            BUNDLE_ROOT + "app/packaging/windows/environment-wsl.yml"
        ).decode().casefold()
        assert "antspyx==0.6.3" in environment
        assert "pyside6-fluent-widgets==1.11.2" in environment
        assert "scipy=1.15.2" in environment
        assert "numpy=1.26.4" in environment
        assert "\n  - ants=" not in environment
        installer = archive.read(BUNDLE_ROOT + "Install-LYS-IRM.sh").decode()
        assert "assert scipy.__version__ == '1.15.2'" in installer

        icon = archive.read(BUNDLE_ROOT + "lys-irm.ico")
        assert icon[:4] == b"\x00\x00\x01\x00"
        assert int.from_bytes(icon[4:6], "little") >= 1

        checksum_lines = archive.read(
            BUNDLE_ROOT + "SHA256SUMS.txt"
        ).decode().splitlines()
        for line in checksum_lines:
            expected, relative = line.split("  ", maxsplit=1)
            content = archive.read(BUNDLE_ROOT + relative)
            assert hashlib.sha256(content).hexdigest() == expected


def test_wsl_installer_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROJECT_ROOT / "packaging/windows/Install-LYS-IRM.sh")],
        check=True,
    )


def test_native_antspyx_bundle_is_windows_only_and_pinned(
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
            "--without-bundled-models",
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert NATIVE_BUNDLE_ROOT + "Setup-LYS-IRM.cmd" in names
        assert NATIVE_BUNDLE_ROOT + "lys-irm.ico" in names
        assert NATIVE_BUNDLE_ROOT + "Install-LYS-IRM.sh" not in names
        environment_path = (
            NATIVE_BUNDLE_ROOT
            + "app/packaging/windows-native/environment-win64.yml"
        )
        environment = archive.read(environment_path).decode().casefold()
        assert "\n  - ants=" not in environment
        assert "pyside6-fluent-widgets==1.11.2" in environment
        assert "scipy==1.15.2" in environment
        assert "torch==2.13.0" in environment
        assert "torchvision==0.28.0" in environment
        assert "pytorch-cpu" not in environment
        assert "monai" not in environment
        assert "gdown" not in environment
        assert "vc14_runtime" in environment
        setup = archive.read(
            NATIVE_BUNDLE_ROOT + "Setup-LYS-IRM.ps1"
        ).decode()
        assert 'Join-Path $env:LOCALAPPDATA "LYS-IRM"' in setup
        assert 'Join-Path $env:LOCALAPPDATA "LYS IRM"' not in setup
        assert "lys_bbb_app.windows_smoke" in setup
        setup = archive.read(
            NATIVE_BUNDLE_ROOT + "Setup-LYS-IRM.ps1"
        ).decode().casefold()
        assert "antspyx==0.6.3" in environment
        assert "invoke-webrequest" not in setup
        assert "pip install" not in setup
        assert "conda env" not in setup
        assert "t1_brain_mask_setup_cli" not in setup
        assert "start-transcript" in setup
        assert "conda-unpack-script.py" in setup
        assert "--models-directory" in setup
        assert "nnunetv2==2.8.1" in environment
        assert "acvl-utils==0.2.6" in environment
        assert "acvl-utils==0.2.1" not in environment
        assert "assert features.atlas_mapping" not in setup

        manifest = json.loads(
            archive.read(
                NATIVE_BUNDLE_ROOT + "handoff-manifest.json"
            )
        )
        assert manifest["application"] == "LYS IRM"
        assert manifest["target"]["runtime"].startswith("native Windows")
        assert manifest["target"]["feature_profile"] == "t2-only"
        assert manifest["target"]["delivery"] == "validation-only"
        assert "t1_brain_mask" not in manifest["models"]
        launcher = archive.read(
            NATIVE_BUNDLE_ROOT + "Launch-LYS-IRM.ps1"
        ).decode()
        assert "$InstallRoot = $PSScriptRoot" in launcher
        assert '$env:LYS_IRM_FEATURE_PROFILE = "t2-only"' in launcher
        assert "wsl.exe" not in launcher.casefold()


def test_native_builder_can_exclude_colleague_readme(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source",
            str(PROJECT_ROOT),
            "--output-directory",
            str(tmp_path),
            "--without-bundled-models",
            "--without-readme",
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert NATIVE_BUNDLE_ROOT + "LISEZ-MOI.txt" not in names
        checksums = archive.read(
            NATIVE_BUNDLE_ROOT + "SHA256SUMS.txt"
        ).decode()
        assert "LISEZ-MOI.txt" not in checksums


def test_native_builder_rejects_external_t2_model_sources(
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
            "native",
            "--t2-model-release",
            str(tmp_path / "Downloads" / "external-model"),
            "--allow-dirty",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unrecognized arguments: --t2-model-release" in result.stderr
