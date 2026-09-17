"""Execute the real offline installer on Windows with tiny model-contract fixtures.

These dummy checkpoints test installation/integrity only, never inference. Only
the runtime artifact is uploaded by CI; these fixtures are never distributed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def write_fixture(root: Path) -> None:
    runtime = root / "RatLesNetv2"
    (runtime / "lib").mkdir(parents=True)
    (root / "models").mkdir()
    (runtime / "LICENSE").write_text("MIT", encoding="utf-8")
    (runtime / "UPSTREAM_GIT_COMMIT.txt").write_text("test-only", encoding="utf-8")
    for name in ("RatLesNetv2.py", "RatLesNetv2Blocks.py"):
        (runtime / "lib" / name).write_text("# INSTALLER TEST FIXTURE\n", encoding="utf-8")
    models = []
    for fold in range(5):
        data = f"installer-test-only-{fold}".encode()
        relative = f"models/fold_{fold}.model"
        (root / relative).write_bytes(data)
        models.append({"fold": fold, "file": relative,
                       "sha256": hashlib.sha256(data).hexdigest()})
    shared = {"ensemble": "unweighted mean lesion probability", "postprocessing": "none",
              "threshold": 0.4, "ratlesnetv2_git_commit": "test-only"}
    payloads = {
        "bundle_manifest.json": dict(shared, models=models),
        "frozen_spec.json": dict(shared, architecture="RatLesNetV2", dataset="TEST_ONLY",
                                 project_git_commit="test-only", fold_models=models),
        "selected_threshold.json": {"selected_threshold": 0.4,
                                    "selection_data": "out_of_fold_validation_only",
                                    "locked_test_used": False},
    }
    for name, data in payloads.items():
        (root / name).write_text(json.dumps(data), encoding="utf-8")


def run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, env=env, text=True, encoding="utf-8",
                               errors="replace", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    print(completed.stdout, flush=True)
    return completed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-directory", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("This check requires Windows.")
    source = Path(__file__).resolve().parents[1]
    models = source / "resources/models"
    if models.exists():
        parser.error("Use a CI checkout without real model resources for this test.")
    for name in ("lys_v3_standard3d_nnunet", "lys_v3_standard3d_nnunet/variants/folds_0_1",
                 "lys_v1_small_ratlesnetv2"):
        write_fixture(models / name)
    with tempfile.TemporaryDirectory(prefix="lys-install-test-") as temporary:
        work = Path(temporary)
        runtime = work / "build-env"
        with zipfile.ZipFile(args.runtime_directory / "windows-runtime.zip") as archive:
            archive.extractall(runtime)
        env = dict(os.environ, PYTHONPATH=str(source / "src"), PYTHONUTF8="1",
                   PYTHONHOME=str(runtime))
        env["PATH"] = f"{runtime};{runtime / 'Library/bin'};{env['PATH']}"
        python = str(runtime / "python.exe")
        run([python, str(runtime / "Scripts/conda-unpack-script.py")], env=env).check_returncode()
        run([python, str(source / "scripts/packaging/build_windows_handoff.py"),
             "--source", str(source), "--runtime-directory", str(args.runtime_directory),
             "--output-directory", str(work / "bundle"), "--allow-dirty"], env=env).check_returncode()
        bundle = next((work / "bundle").glob("*.zip"))
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(work / "extracted")
        extracted = work / "extracted/LYS-IRM-Windows-Native"
        installed = work / "colleague with spaces"
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(extracted / "Setup-LYS-IRM.ps1"), "-InstallRoot", str(installed),
                   "-Unattended", "-NoShortcuts"]
        env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        run(command, env=env).check_returncode()
        active = installed / "active-install.json"
        previous = active.read_bytes()
        record = json.loads(previous.decode("utf-8-sig"))
        if record["feature_profile"] != "t2-only":
            raise RuntimeError("Installer selected the wrong feature profile")
        # A corrupt subsequent package must fail without changing the active install.
        (extracted / "app/src/lys_bbb_app/features.py").write_text("# corrupt\n", encoding="utf-8")
        if run(command, env=env).returncode == 0 or active.read_bytes() != previous:
            raise RuntimeError("Corrupt reinstall was accepted or changed the active installation")
    shutil.rmtree(models)  # Only the test fixtures just created in this CI checkout.
    print("Offline setup and failed-reinstall preservation passed on Windows.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
