#!/usr/bin/env python3
"""Assemble the offline Windows T2 handoff, or the legacy WSL bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PAYLOAD_ROOT_FILES = ("pyproject.toml", "README.md")
PAYLOAD_PREFIXES = ("src/",)
T1_MODEL_BUNDLE_DIRECTORY = PurePosixPath("models/rs2net-m-seam-v1")
T2_RESOURCE_DIRECTORIES = (
    "lys_v3_standard3d_nnunet",
    "lys_v1_small_ratlesnetv2",
)
IGNORED_MODEL_FILE_NAMES = (".DS_Store",)
IGNORED_MODEL_DIRECTORY_NAMES = ("__pycache__",)


@dataclass(frozen=True, slots=True)
class BundleTarget:
    bundle_root: PurePosixPath
    template_directory: str
    template_files: tuple[str, ...]
    environment_file: str
    archive_label: str
    runtime: str
    graphics: str
    feature_profile: str


TARGETS = {
    "wsl": BundleTarget(
        bundle_root=PurePosixPath("LYS-IRM-Windows"),
        template_directory="packaging/windows",
        template_files=(
            "Setup-LYS-IRM.cmd",
            "Setup-LYS-IRM.ps1",
            "Launch-LYS-IRM.ps1",
            "Install-LYS-IRM.sh",
            "LISEZ-MOI.txt",
        ),
        environment_file="packaging/windows/environment-wsl.yml",
        archive_label="LYS-IRM-Windows",
        runtime="WSL2/Ubuntu with WSLg",
        graphics="integrated Windows desktop via WSLg",
        feature_profile="full",
    ),
    "native": BundleTarget(
        bundle_root=PurePosixPath("LYS-IRM-Windows-Native"),
        template_directory="packaging/windows-native",
        template_files=(
            "Setup-LYS-IRM.cmd",
            "Setup-LYS-IRM.ps1",
            "Launch-LYS-IRM.ps1",
        ),
        environment_file="packaging/windows-native/environment-win64.yml",
        archive_label="LYS-IRM-Windows-T2-Offline",
        runtime="native Windows CPython with ANTsPyx",
        graphics="native Windows desktop",
        feature_profile="t2-only",
    ),
}


def _git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _entry_sha256(content: bytes | Path) -> str:
    if isinstance(content, Path):
        with content.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    return _sha256(content)


def _text_hashes(path: Path) -> set[str]:
    """Git's Windows checkout may use CRLF for the same reviewed source text."""
    text = path.read_text(encoding="utf-8")
    return {_sha256(text.encode()), _sha256(text.replace("\n", "\r\n").encode())}


def _payload_files(source: Path, environment_file: str) -> tuple[str, ...]:
    output = _git(
        source,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    candidates = tuple(line for line in output.splitlines() if line)
    selected = tuple(
        path
        for path in candidates
        if (
            path in PAYLOAD_ROOT_FILES
            or path == environment_file
            or path.startswith(PAYLOAD_PREFIXES)
        )
        and (source / path).is_file()
    )
    return tuple(sorted(selected))


def _model_file_is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORED_MODEL_FILE_NAMES
        or path.suffix == ".pyc"
        or any(part in IGNORED_MODEL_DIRECTORY_NAMES for part in path.parts)
    )


def _all_release_files(
    root: Path, *, ignore_generated_files: bool = True
) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Model release contains a symbolic link: {path}")
        ignored = (
            ignore_generated_files
            and _model_file_is_ignored(path.relative_to(root))
        )
        if path.is_file() and not ignored:
            files.append(path)
    return tuple(sorted(files))


def _add_release_files(
    entries: dict[PurePosixPath, bytes | Path],
    *,
    bundle_root: PurePosixPath,
    bundle_directory: PurePosixPath,
    release_root: Path,
    files: tuple[Path, ...],
) -> None:
    for path in files:
        relative = path.relative_to(release_root)
        destination = bundle_root / bundle_directory / PurePosixPath(relative)
        if destination in entries:
            raise RuntimeError(f"Duplicate model bundle path: {destination}")
        entries[destination] = path


def _bundle_t1_model_release(
    entries: dict[PurePosixPath, bytes | Path],
    *,
    source: Path,
    bundle_root: PurePosixPath,
    release_root: Path,
) -> dict[str, object]:
    sys.path.insert(0, str(source / "src"))
    from lys_bbb.t1_brain_mask_release import validate_t1_brain_mask_release

    release = validate_t1_brain_mask_release(release_root)
    files = {
        release.root_path / "release.json",
        release.weights_path,
        *_all_release_files(
            release.source_path,
            ignore_generated_files=False,
        ),
    }
    _add_release_files(
        entries,
        bundle_root=bundle_root,
        bundle_directory=T1_MODEL_BUNDLE_DIRECTORY,
        release_root=release.root_path,
        files=tuple(sorted(files)),
    )
    return {
        "id": release.id,
        "delivery": "bundled",
        "bundle_path": str(T1_MODEL_BUNDLE_DIRECTORY),
        "install_path": (
            r"%LOCALAPPDATA%\LYS-IRM\models\rs2net-m-seam-v1"
        ),
        "source_commit": release.source_commit,
        "weights_sha256": release.weights_sha256,
        "file_count": len(files),
    }


def _bundle_checked_in_t2_resources(
    entries: dict[PurePosixPath, bytes | Path],
    *,
    source: Path,
    bundle_root: PurePosixPath,
) -> dict[str, object]:
    """Bundle deliberate T2 choices from resources/models, the source of truth."""

    sys.path.insert(0, str(source / "src"))
    from lys_bbb.t2_model_release import validate_t2_model_release

    resource_models = source / "resources" / "models"
    standard_root = resource_models / "lys_v3_standard3d_nnunet"
    choice_paths = (
        standard_root,
        standard_root / "variants" / "folds_0_1",
        resource_models / "lys_v1_small_ratlesnetv2",
    )
    choices = [validate_t2_model_release(path) for path in choice_paths]
    file_count = 0
    for directory_name in T2_RESOURCE_DIRECTORIES:
        release_root = resource_models / directory_name
        files = _all_release_files(release_root)
        _add_release_files(
            entries,
            bundle_root=bundle_root,
            bundle_directory=PurePosixPath("models") / directory_name,
            release_root=release_root,
            files=files,
        )
        file_count += len(files)
    return {
        "delivery": "bundled",
        "source": "resources/models",
        "default_id": choices[0].id,
        "choices": [
            {
                "id": choice.id,
                "name": choice.name,
                "folds": list(choice.folds),
                "model_sha256": list(choice.model_sha256),
            }
            for choice in choices
        ],
        "file_count": file_count,
    }


def windows_icon_bytes(source: Path) -> bytes:
    """Load the checked-in multi-resolution Windows icon."""

    return (source / "packaging" / "assets" / "lys-irm.ico").read_bytes()


def _bundle_runtime(
    entries: dict[PurePosixPath, bytes | Path], *, source: Path,
    bundle_root: PurePosixPath, runtime_directory: Path,
) -> None:
    manifest_path = runtime_directory / "runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "platform": "win-64", "profile": "t2-only",
        "relocation_test": "passed", "pip_check": "passed",
        "environment_sha256": _text_hashes(
            source / "packaging/windows-native/environment-win64.yml"),
        "smoke_sha256": _text_hashes(source / "src/lys_bbb_app/windows_smoke.py"),
        "archive_sha256": _entry_sha256(runtime_directory / "windows-runtime.zip"),
    }
    for key, value in expected.items():
        if manifest.get(key) not in (value if isinstance(value, set) else {value}):
            raise RuntimeError(f"Windows runtime validation failed: {key}")
    for name in ("windows-runtime.zip", "runtime-manifest.json",
                 "pip-freeze.txt", "conda-explicit.txt"):
        path = runtime_directory / name
        if not path.is_file():
            raise RuntimeError(f"Runtime build output missing: {path}")
        entries[bundle_root / "runtime" / name] = path


def build_bundle(
    source: Path,
    output_directory: Path,
    *,
    allow_dirty: bool = False,
    target_name: str = "native",
    t1_model_release: Path | None = None,
    bundle_checked_in_t2_models: bool = False,
    include_readme: bool = True,
    runtime_directory: Path | None = None,
) -> Path:
    source = source.resolve()
    output_directory = output_directory.resolve()
    target = TARGETS[target_name]
    if target_name == "native":
        if t1_model_release is not None:
            raise RuntimeError("The Windows colleague edition must not contain a T1 model.")
        if bundle_checked_in_t2_models and runtime_directory is None:
            raise RuntimeError("An offline Windows build requires --runtime-directory.")
        if runtime_directory is not None and not bundle_checked_in_t2_models:
            raise RuntimeError("An offline Windows build must include its T2 models.")
    status = _git(source, "status", "--porcelain", "--untracked-files=all")
    if status and not allow_dirty:
        raise RuntimeError(
            "Refusing to create a release bundle from a dirty working tree. "
            "Commit the snapshot first or pass --allow-dirty for a test build."
        )

    commit = _git(source, "rev-parse", "HEAD")
    branch = _git(source, "branch", "--show-current") or "detached"
    project = tomllib.loads((source / "pyproject.toml").read_text())
    version = str(project["project"]["version"])
    variant = "" if include_readme else "-no-readme"
    suffix = "-dirty" if status else ""
    bundle_name = (
        f"{target.archive_label}-{version}-{commit[:8]}{variant}{suffix}.zip"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / bundle_name

    entries: dict[PurePosixPath, bytes | Path] = {}
    template_directory = source / target.template_directory
    for name in target.template_files:
        if not include_readme and name == "LISEZ-MOI.txt":
            continue
        entries[target.bundle_root / name] = (
            template_directory / name
        ).read_bytes()
    icon_name = "lys-irm.ico"
    entries[target.bundle_root / icon_name] = windows_icon_bytes(source)
    for relative in _payload_files(source, target.environment_file):
        entries[target.bundle_root / "app" / PurePosixPath(relative)] = (
            source / relative
        ).read_bytes()
    bundled_models: dict[str, dict[str, object]] = {}
    if runtime_directory is not None:
        if target_name != "native":
            raise RuntimeError("A packed Windows runtime is only valid for the native target.")
        _bundle_runtime(entries, source=source, bundle_root=target.bundle_root,
                        runtime_directory=runtime_directory.resolve())
    if t1_model_release is not None:
        bundled_models["t1_brain_mask"] = _bundle_t1_model_release(
            entries,
            source=source,
            bundle_root=target.bundle_root,
            release_root=t1_model_release.expanduser().resolve(),
        )
    if bundle_checked_in_t2_models:
        bundled_models["t2_lesion_segmentation"] = (
            _bundle_checked_in_t2_resources(
                entries,
                source=source,
                bundle_root=target.bundle_root,
            )
        )

    tracked_hashes = {
        str(path.relative_to(target.bundle_root)): _entry_sha256(content)
        for path, content in sorted(entries.items(), key=lambda item: str(item[0]))
    }
    manifest = {
        "schema_version": 1,
        "application": "LYS IRM",
        "application_version": version,
        "source_branch": branch,
        "source_commit": commit,
        "source_dirty": bool(status),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": {
            "host": "Windows 11 x86_64",
            "runtime": target.runtime,
            "graphics": target.graphics,
            "ml_device": "CPU",
            "feature_profile": target.feature_profile,
            "delivery": "offline" if runtime_directory else "validation-only"
            if target_name == "native" else "bootstrap",
        },
        "models": bundled_models,
        "files": tracked_hashes,
    }
    manifest_content = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    entries[target.bundle_root / "handoff-manifest.json"] = manifest_content

    checksum_lines = tuple(
        f"{_entry_sha256(content)}  {path.relative_to(target.bundle_root)}"
        for path, content in sorted(entries.items(), key=lambda item: str(item[0]))
    )
    entries[target.bundle_root / "SHA256SUMS.txt"] = (
        "\n".join(checksum_lines) + "\n"
    ).encode()

    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, content in sorted(entries.items(), key=lambda item: str(item[0])):
            if isinstance(content, Path):
                # conda-pack's Windows ZIP contains many stored entries. Compress
                # the transport layer without changing the tested runtime bytes.
                archive.write(content, str(path), compress_type=zipfile.ZIP_DEFLATED,
                              compresslevel=6)
                continue
            info = zipfile.ZipInfo(str(path), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (
                (0o755 if path.suffix == ".sh" else 0o644) & 0xFFFF
            ) << 16
            archive.writestr(info, content)
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output-directory", type=Path, default=Path("dist"))
    parser.add_argument("--runtime-directory", type=Path,
                        help="verified output from build_windows_runtime.py on Windows")
    parser.add_argument(
        "--target",
        choices=tuple(TARGETS),
        default="native",
        help="distribution target; defaults to native Windows with ANTsPyx",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="create a test bundle even when the source snapshot is not committed",
    )
    parser.add_argument(
        "--t1-model-release",
        type=Path,
        help="validated RS2-Net/M-seam release to include in the archive",
    )
    parser.add_argument(
        "--without-bundled-models",
        action="store_true",
        help="explicitly create a native test archive without local model releases",
    )
    parser.add_argument(
        "--without-readme",
        action="store_true",
        help="exclude the colleague-facing LISEZ-MOI.txt file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    native_target = args.target == "native"
    try:
        output = build_bundle(
            args.source,
            args.output_directory,
            allow_dirty=args.allow_dirty,
            target_name=args.target,
            t1_model_release=args.t1_model_release,
            bundle_checked_in_t2_models=(
                native_target
                and not args.without_bundled_models
            ),
            include_readme=not args.without_readme,
            runtime_directory=args.runtime_directory,
        )
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    print(f"sha256: {_entry_sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
