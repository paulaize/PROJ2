#!/usr/bin/env python3
"""Build the source-bootstrap ZIP handed to a Windows 11 colleague."""

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
T2_MODEL_BUNDLE_DIRECTORY = PurePosixPath("models/ratlesnetv2-lys-v1")
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
        bundle_root=PurePosixPath("LYS-BBB-Windows"),
        template_directory="packaging/windows",
        template_files=(
            "Setup-LYS-BBB.cmd",
            "Setup-LYS-BBB.ps1",
            "Launch-LYS-BBB.ps1",
            "Install-LYS-BBB.sh",
            "LISEZ-MOI.txt",
        ),
        environment_file="packaging/windows/environment-wsl.yml",
        archive_label="LYS-BBB-Windows",
        runtime="WSL2/Ubuntu with WSLg",
        graphics="integrated Windows desktop via WSLg",
        feature_profile="full",
    ),
    "native-no-ants": BundleTarget(
        bundle_root=PurePosixPath("MRI-Tool-Windows-Native-No-ANTs-v1"),
        template_directory="packaging/windows-native",
        template_files=(
            "Setup-MRI-Tool.cmd",
            "Setup-MRI-Tool.ps1",
            "Launch-MRI-Tool.ps1",
            "LISEZ-MOI.txt",
        ),
        environment_file="packaging/windows-native/environment-win64.yml",
        archive_label="MRI-Tool-Windows-Native-No-ANTs",
        runtime="native Windows CPython via Miniforge",
        graphics="native Windows desktop",
        feature_profile="windows_native_no_ants_v1",
    ),
    "native-antspyx-preview": BundleTarget(
        bundle_root=PurePosixPath("MRI-Tool-Windows-Native-ANTsPyx-Preview-v1"),
        template_directory="packaging/windows-native",
        template_files=(
            "Setup-MRI-Tool.cmd",
            "Setup-MRI-Tool.ps1",
            "Launch-MRI-Tool.ps1",
            "LISEZ-MOI-ANTSPYX.txt",
        ),
        environment_file=(
            "packaging/windows-native/environment-win64-antspyx.yml"
        ),
        archive_label="MRI-Tool-Windows-Native-ANTsPyx-Preview",
        runtime="native Windows CPython with ANTsPyx",
        graphics="native Windows desktop",
        feature_profile="windows_native_antspyx_preview_v1",
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
        if path in PAYLOAD_ROOT_FILES
        or path == environment_file
        or path.startswith(PAYLOAD_PREFIXES)
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
    entries: dict[PurePosixPath, bytes],
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
        entries[destination] = path.read_bytes()


def _bundle_t1_model_release(
    entries: dict[PurePosixPath, bytes],
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
            r"%LOCALAPPDATA%\LYS BBB\models\rs2net-m-seam-v1"
        ),
        "source_commit": release.source_commit,
        "weights_sha256": release.weights_sha256,
        "file_count": len(files),
    }


def _bundle_t2_model_release(
    entries: dict[PurePosixPath, bytes],
    *,
    source: Path,
    bundle_root: PurePosixPath,
    release_root: Path,
) -> dict[str, object]:
    sys.path.insert(0, str(source / "src"))
    from lys_bbb.t2_model_release import validate_frozen_t2_model_release

    release = validate_frozen_t2_model_release(release_root)
    files = _all_release_files(release.root_path)
    _add_release_files(
        entries,
        bundle_root=bundle_root,
        bundle_directory=T2_MODEL_BUNDLE_DIRECTORY,
        release_root=release.root_path,
        files=files,
    )
    return {
        "id": release.id,
        "version": release.version,
        "delivery": "bundled",
        "bundle_path": str(T2_MODEL_BUNDLE_DIRECTORY),
        "install_path": (
            r"%LOCALAPPDATA%\LYS BBB\models\ratlesnetv2-lys-v1"
        ),
        "manifest_sha256": release.manifest_sha256,
        "model_sha256": list(release.model_sha256),
        "file_count": len(files),
    }


def windows_icon_bytes(source: Path) -> bytes:
    """Load the checked-in multi-resolution Windows icon."""

    return (source / "packaging" / "assets" / "mri-tool.ico").read_bytes()


def build_bundle(
    source: Path,
    output_directory: Path,
    *,
    allow_dirty: bool = False,
    target_name: str = "wsl",
    t1_model_release: Path | None = None,
    t2_model_release: Path | None = None,
) -> Path:
    source = source.resolve()
    output_directory = output_directory.resolve()
    target = TARGETS[target_name]
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
    suffix = "-dirty" if status else ""
    bundle_name = (
        f"{target.archive_label}-{version}-{commit[:8]}{suffix}.zip"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / bundle_name

    entries: dict[PurePosixPath, bytes] = {}
    template_directory = source / target.template_directory
    for name in target.template_files:
        entries[target.bundle_root / name] = (
            template_directory / name
        ).read_bytes()
    icon_name = (
        "mri-tool.ico" if target_name.startswith("native") else "lys-bbb.ico"
    )
    entries[target.bundle_root / icon_name] = windows_icon_bytes(source)
    for relative in _payload_files(source, target.environment_file):
        entries[target.bundle_root / "app" / PurePosixPath(relative)] = (
            source / relative
        ).read_bytes()
    bundled_models: dict[str, dict[str, object]] = {}
    if t1_model_release is not None:
        bundled_models["t1_brain_mask"] = _bundle_t1_model_release(
            entries,
            source=source,
            bundle_root=target.bundle_root,
            release_root=t1_model_release.expanduser().resolve(),
        )
    if t2_model_release is not None:
        bundled_models["t2_lesion_segmentation"] = _bundle_t2_model_release(
            entries,
            source=source,
            bundle_root=target.bundle_root,
            release_root=t2_model_release.expanduser().resolve(),
        )

    tracked_hashes = {
        str(path.relative_to(target.bundle_root)): _sha256(content)
        for path, content in sorted(entries.items(), key=lambda item: str(item[0]))
    }
    manifest = {
        "schema_version": 1,
        "application": "MRI Tool",
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
        },
        "models": bundled_models,
        "files": tracked_hashes,
    }
    manifest_content = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    entries[target.bundle_root / "handoff-manifest.json"] = manifest_content

    checksum_lines = tuple(
        f"{_sha256(content)}  {path.relative_to(target.bundle_root)}"
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
    parser.add_argument(
        "--target",
        choices=tuple(TARGETS),
        default="wsl",
        help="distribution target; defaults to the original WSL handoff",
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
        "--t2-model-release",
        type=Path,
        help="validated frozen RatLesNetV2 release to include in the archive",
    )
    parser.add_argument(
        "--without-bundled-models",
        action="store_true",
        help="explicitly create a native test archive without local model releases",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    native_target = args.target in {
        "native-no-ants",
        "native-antspyx-preview",
    }
    if (
        native_target
        and args.t1_model_release is None
        and args.t2_model_release is None
        and not args.without_bundled_models
    ):
        print(
            "error: native bundles require model release arguments; "
            "use --without-bundled-models only for packaging tests",
            file=sys.stderr,
        )
        return 1
    try:
        output = build_bundle(
            args.source,
            args.output_directory,
            allow_dirty=args.allow_dirty,
            target_name=args.target,
            t1_model_release=args.t1_model_release,
            t2_model_release=args.t2_model_release,
        )
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    print(f"sha256: {_sha256(output.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
