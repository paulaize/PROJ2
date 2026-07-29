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
BUNDLE_ROOT = "LYS-IRM-Windows/"
NATIVE_BUNDLE_ROOT = "LYS-IRM-Windows-Native/"


def _write_tiny_t2_release(root: Path) -> Path:
    models = root / "models"
    runtime = root / "RatLesNetv2" / "lib"
    models.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (root / "RatLesNetv2" / "LICENSE").write_text("MIT")
    (root / "RatLesNetv2" / "UPSTREAM_GIT_COMMIT.txt").write_text(
        "upstream-123\n"
    )
    (runtime / "RatLesNetv2.py").write_text("# runtime")
    (runtime / "RatLesNetv2Blocks.py").write_text("# blocks")
    manifest_models = []
    frozen_models = []
    for fold in range(5):
        model = models / f"fold_{fold}.model"
        model.write_bytes(f"model-{fold}".encode())
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        manifest_models.append(
            {"file": f"models/{model.name}", "fold": fold, "sha256": digest}
        )
        frozen_models.append(
            {"fold": fold, "path": model.name, "sha256": digest}
        )
    (root / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "ensemble": "unweighted mean lesion probability",
                "models": manifest_models,
                "postprocessing": "none",
                "ratlesnetv2_git_commit": "upstream-123",
                "threshold": 0.4,
            }
        )
    )
    (root / "frozen_spec.json").write_text(
        json.dumps(
            {
                "architecture": "RatLesNetV2",
                "dataset": "LYS_v1",
                "ensemble": "unweighted mean lesion probability",
                "fold_models": frozen_models,
                "postprocessing": "none",
                "project_git_commit": "project-456",
                "ratlesnetv2_git_commit": "upstream-123",
                "threshold": 0.4,
            }
        )
    )
    (root / "selected_threshold.json").write_text(
        json.dumps(
            {
                "selected_threshold": 0.4,
                "selection_data": "out_of_fold_validation_only",
                "locked_test_used": False,
            }
        )
    )
    return root


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
        assert "scipy=1.15.2" in environment
        assert "\n  - statsmodels" in environment
        assert "\n  - scikit-learn" in environment
        assert "\n  - pyyaml" in environment
        assert "\n  - webcolors" in environment
        assert "\n  - pillow" in environment
        assert "\n  - requests" in environment
        assert "vc14_runtime" in environment
        setup = archive.read(
            NATIVE_BUNDLE_ROOT + "Setup-LYS-IRM.ps1"
        ).decode()
        assert "assert scipy.__version__ == '1.15.2'" in setup
        setup = archive.read(
            NATIVE_BUNDLE_ROOT + "Setup-LYS-IRM.ps1"
        ).decode().casefold()
        assert "antspyx==0.6.3" in setup
        assert "antspyx-0.6.3-cp311-cp311-win_amd64.whl" in setup
        assert (
            "39a29ba5abbf3475dea70cf0d0a2472e34a5c854f99d2f08204a288f1f5aeac4"
            in setup
        )
        assert "install-bundledmodelrelease" in setup
        assert "rs2net-m-seam-v1" in setup
        assert "ratlesnetv2-lys-v1" in setup
        assert "import ants, scipy, simpleitk, torch, statsmodels" in setup
        assert "import sklearn, yaml, webcolors, pil, requests" in setup

        manifest = json.loads(
            archive.read(
                NATIVE_BUNDLE_ROOT + "handoff-manifest.json"
            )
        )
        assert manifest["application"] == "LYS IRM"
        assert manifest["target"]["runtime"].startswith("native Windows")
        assert manifest["target"]["feature_profile"] == "full"
        launcher = archive.read(
            NATIVE_BUNDLE_ROOT + "Launch-LYS-IRM.ps1"
        ).decode()
        assert '$featureProfile = "full"' in launcher
        assert "wsl.exe" not in launcher.casefold()


def test_native_builder_can_bundle_and_checksum_a_validated_t2_release(
    tmp_path: Path,
) -> None:
    release = _write_tiny_t2_release(tmp_path / "t2-release")
    output = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--source",
            str(PROJECT_ROOT),
            "--output-directory",
            str(output),
            "--target",
            "native",
            "--t2-model-release",
            str(release),
            "--allow-dirty",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    archive_path = Path(result.stdout.splitlines()[0])

    with zipfile.ZipFile(archive_path) as archive:
        model_prefix = (
            NATIVE_BUNDLE_ROOT + "models/ratlesnetv2-lys-v1/"
        )
        names = set(archive.namelist())
        assert model_prefix + "models/fold_4.model" in names
        manifest = json.loads(
            archive.read(NATIVE_BUNDLE_ROOT + "handoff-manifest.json")
        )
        bundled = manifest["models"]["t2_lesion_segmentation"]
        assert bundled["delivery"] == "bundled"
        assert bundled["file_count"] == 12
        assert len(bundled["model_sha256"]) == 5
        checksum_lines = archive.read(
            NATIVE_BUNDLE_ROOT + "SHA256SUMS.txt"
        ).decode().splitlines()
        fold_line = next(
            line
            for line in checksum_lines
            if line.endswith("models/ratlesnetv2-lys-v1/models/fold_4.model")
        )
        expected, relative = fold_line.split("  ", maxsplit=1)
        assert hashlib.sha256(
            archive.read(NATIVE_BUNDLE_ROOT + relative)
        ).hexdigest() == expected
