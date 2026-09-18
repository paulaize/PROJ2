"""Execute the real offline installer on Windows with tiny model-contract fixtures.

These dummy checkpoints test installation/integrity only, never inference. Only
the runtime artifact is uploaded by CI; these fixtures are never distributed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
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


def run(command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, env=env, cwd=cwd, text=True, encoding="utf-8",
                               errors="replace", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    print(completed.stdout, flush=True)
    return completed


def previous_source_payload(source: Path, extracted: Path, commit: str) -> None:
    """Use the real previous app source for the first installation in the test."""
    payload = subprocess.check_output([
        "git", "archive", commit, "src", "pyproject.toml", "README.md",
        "packaging/windows-native/environment-win64.yml",
    ], cwd=source)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        archive.extractall(extracted / "app", filter="data")
    manifest_path = extracted / "handoff-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_commit"] = commit
    manifest["files"] = {
        name: digest for name, digest in manifest["files"].items()
        if not name.startswith("app/")
    }
    for path in (extracted / "app").rglob("*"):
        if path.is_file():
            manifest["files"][path.relative_to(extracted).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hashes = dict(manifest["files"])
    hashes["handoff-manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (extracted / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())), encoding="utf-8",
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-directory", type=Path, required=True)
    parser.add_argument("--previous-commit")
    parser.add_argument("--test-tools-directory", type=Path)
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
    with tempfile.TemporaryDirectory(prefix="lys-install-test-",
                                     dir=os.environ.get("RUNNER_TEMP")) as temporary:
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
            if any(Path(name).name == "LISEZ-MOI.txt" for name in archive.namelist()):
                raise RuntimeError("The colleague package must not contain LISEZ-MOI.txt")
            archive.extractall(work / "extracted")
        extracted = work / "extracted/LYS-IRM-Windows-Native"
        current_metadata = {
            name: (extracted / name).read_bytes()
            for name in ("handoff-manifest.json", "SHA256SUMS.txt")
        }
        if args.previous_commit:
            (extracted / "app").rename(work / "current-app")
            previous_source_payload(source, extracted, args.previous_commit)
        installed = work / "colleague with spaces"
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(extracted / "Setup-LYS-IRM.ps1"), "-InstallRoot", str(installed),
                   "-Unattended", "-NoShortcuts"]
        env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        installation = run(command, env=env)
        if installation.returncode:
            for log in (installed / "logs").glob("setup-*.log"):
                print(log.read_text(encoding="utf-8-sig"), flush=True)
        installation.check_returncode()
        lines = [line.strip() for line in installation.stdout.splitlines() if line.strip()]
        if lines != ["Verification...", "Installation...", "Finalisation...",
                     "Installation terminee. Lancez LYS IRM depuis le Bureau."]:
            raise RuntimeError(f"Unexpected installer console output: {lines!r}")
        logs = list((installed / "logs").glob("setup-*.log"))
        if len(logs) != 1:
            raise RuntimeError("Expected one installation log")
        diagnostic = logs[0].read_text(encoding="utf-8-sig")
        if '"status": "passed"' not in diagnostic or "Verified T2 model:" not in diagnostic:
            raise RuntimeError("Startup diagnostics were not preserved in the log")
        active = installed / "active-install.json"
        previous = active.read_bytes()
        record = json.loads(previous.decode("utf-8-sig"))
        if record["feature_profile"] != "t2-only":
            raise RuntimeError("Installer selected the wrong feature profile")
        if args.previous_commit:
            # Create a real study with the previous application's code, then upgrade.
            old_release = installed / "releases" / record["release_id"]
            old_env = dict(env, PYTHONHOME=str(old_release / "env"),
                           PYTHONPATH=str(old_release / "app/src"),
                           LYS_IRM_FEATURE_PROFILE="t2-only")
            old_env["PATH"] = f"{old_release / 'env'};{old_release / 'env/Library/bin'};{os.environ['PATH']}"
            study = work / "existing colleague study"
            create_study = (
                "from pathlib import Path; from lys_bbb_app.services.study_service import StudyService; "
                "from lys_bbb_app.domain.study import CreateStudyRequest, CreateSubjectRequest, AnalysisScope; "
                "s=StudyService(); s.create_study(CreateStudyRequest(Path(__import__('sys').argv[1]), "
                "'Existing study','existing',analysis_scope=AnalysisScope.T2_ONLY,actor='Tester')); "
                "s.add_subject(CreateSubjectRequest('Mouse-existing',False,True,actor='Tester'))"
            )
            run([str(old_release / "env/python.exe"), "-c", create_study, str(study)], env=old_env, cwd=work).check_returncode()
            study_hashes = {p.relative_to(study): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in study.rglob("*") if p.is_file()}
            (extracted / "app").rename(work / "previous-app")
            (work / "current-app").rename(extracted / "app")
            for name, content in current_metadata.items():
                (extracted / name).write_bytes(content)
            run(command, env=env).check_returncode()
            if (installed / "active-install.previous.json").read_bytes() != previous:
                raise RuntimeError("Upgrade did not preserve the previous active release")
            updated = active.read_bytes()
            if updated == previous or not (old_release / "env/python.exe").is_file():
                raise RuntimeError("Upgrade did not create a separate release")
            if study_hashes != {p.relative_to(study): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in study.rglob("*") if p.is_file()}:
                raise RuntimeError("Installation modified the existing study")
            previous = updated
            record = json.loads(previous.decode("utf-8-sig"))
        # Also exercise the native Windows Qt plugin from the installed prefix.
        release = installed / "releases" / record["release_id"]
        actual_env = dict(env, PYTHONHOME=str(release / "env"),
                          PYTHONPATH=str(release / "app/src"),
                          LYS_IRM_FEATURE_PROFILE="t2-only", QT_QPA_PLATFORM="windows",
                          LYS_IRM_MODELS_DIRECTORY=str(release / "models"))
        actual_env["PATH"] = f"{release / 'env'};{release / 'env/Library/bin'};{os.environ['PATH']}"
        run([str(release / "env/python.exe"), "-m", "lys_bbb_app.windows_smoke",
             "--models-directory", str(release / "models")], env=actual_env).check_returncode()
        if args.previous_commit:
            open_study = (
                "from pathlib import Path; from lys_bbb_app.services.study_service import StudyService; "
                "s=StudyService().open_study(Path(__import__('sys').argv[1])); "
                "assert s.subjects[0].subject_code == 'Mouse-existing'; print('Previous-version study reopened')"
            )
            run([str(release / "env/python.exe"), "-c", open_study, str(study)], env=actual_env, cwd=work).check_returncode()
        if args.test_tools_directory:
            # Test installed source, not the checkout. No pip changes to its runtime.
            actual_env["PYTHONPATH"] += os.pathsep + str(args.test_tools_directory.resolve())
            actual_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            run([str(release / "env/python.exe"), "-c",
                 "import lys_bbb_app; print('Testing installed source:', lys_bbb_app.__file__)"],
                env=actual_env, cwd=work).check_returncode()
            run([str(release / "env/python.exe"), "-m", "pytest", "-o", "pythonpath=", "-q",
                 *[str(source / "tests" / name) for name in (
                     "test_mri_preview.py", "test_orientation_correction.py",
                     "test_desktop_app.py", "test_scan_import.py", "test_windows_t2_profile.py",
                 )]], env=actual_env, cwd=work).check_returncode()
        # A corrupt subsequent package must fail without changing the active install.
        (extracted / "app/src/lys_bbb_app/features.py").write_text("# corrupt\n", encoding="utf-8")
        failed = run(command, env=env)
        if failed.returncode == 0 or active.read_bytes() != previous:
            raise RuntimeError("Corrupt reinstall was accepted or changed the active installation")
        if "Installation interrompue." not in failed.stdout or "Journal :" not in failed.stdout:
            raise RuntimeError("A failed install must show a concise error and log location")
        if "Traceback" in failed.stdout:
            raise RuntimeError("Technical failure details leaked into the console")
    shutil.rmtree(models)  # Only the test fixtures just created in this CI checkout.
    print("Offline setup, upgrade, installed app checks and failed-reinstall preservation passed on Windows.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
