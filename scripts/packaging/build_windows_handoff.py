#!/usr/bin/env python3
"""Build the source-bootstrap ZIP handed to a Windows 11 colleague."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PAYLOAD_ROOT_FILES = ("pyproject.toml", "README.md")
PAYLOAD_PREFIXES = ("src/",)


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
        bundle_root=PurePosixPath("LYS-BBB-Windows-Native-No-ANTs-v1"),
        template_directory="packaging/windows-native",
        template_files=(
            "Setup-LYS-BBB.cmd",
            "Setup-LYS-BBB.ps1",
            "Launch-LYS-BBB.ps1",
            "LISEZ-MOI.txt",
        ),
        environment_file="packaging/windows-native/environment-win64.yml",
        archive_label="LYS-BBB-Windows-Native-No-ANTs",
        runtime="native Windows CPython via Miniforge",
        graphics="native Windows desktop",
        feature_profile="windows_native_no_ants_v1",
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


def _rounded_square(x: int, y: int, size: int) -> bool:
    margin = size // 32
    radius = size * 3 // 16
    if margin + radius <= x < size - margin - radius:
        return margin <= y < size - margin
    if margin + radius <= y < size - margin - radius:
        return margin <= x < size - margin
    corner_x = margin + radius if x < size // 2 else size - margin - radius - 1
    corner_y = margin + radius if y < size // 2 else size - margin - radius - 1
    return (x - corner_x) ** 2 + (y - corner_y) ** 2 <= radius**2


def _ring(x: int, y: int, cx: int, cy: int, radius: int, width: int) -> bool:
    distance = (x - cx) ** 2 + (y - cy) ** 2
    return (radius - width) ** 2 <= distance <= (radius + width) ** 2


def _ellipse_ring(
    x: int,
    y: int,
    cx: int,
    cy: int,
    radius_x: int,
    radius_y: int,
    width: float,
) -> bool:
    outer = ((x - cx) / radius_x) ** 2 + ((y - cy) / radius_y) ** 2
    inner_x = max(radius_x - width, 1)
    inner_y = max(radius_y - width, 1)
    inner = ((x - cx) / inner_x) ** 2 + ((y - cy) / inner_y) ** 2
    return outer <= 1 and inner >= 1


def windows_icon_bytes(size: int = 256) -> bytes:
    """Create a self-contained 32-bit ICO with the app's teal MRI mark."""

    teal = (117, 123, 8, 255)
    white = (255, 255, 255, 255)
    amber = (34, 165, 239, 255)
    transparent = (0, 0, 0, 0)
    pixels: list[bytes] = []
    center_x = size // 2
    center_y = size * 15 // 32
    for y in range(size - 1, -1, -1):
        for x in range(size):
            colour = teal if _rounded_square(x, y, size) else transparent
            if _ring(x, y, center_x, center_y, size * 5 // 16, size // 48):
                colour = white
            left_lobe = _ellipse_ring(
                x,
                y,
                size * 13 // 32,
                center_y,
                size * 7 // 64,
                size * 3 // 16,
                size / 64,
            )
            right_lobe = _ellipse_ring(
                x,
                y,
                size * 19 // 32,
                center_y,
                size * 7 // 64,
                size * 3 // 16,
                size / 64,
            )
            if left_lobe or right_lobe:
                colour = white
            lesion_radius = size // 32
            if (
                x - size * 39 // 64
            ) ** 2 + (
                y - size * 25 // 64
            ) ** 2 <= lesion_radius**2:
                colour = amber
            pixels.append(bytes(colour))

    bitmap_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        size * size * 4,
        0,
        0,
        0,
        0,
    )
    and_mask_row = ((size + 31) // 32) * 4
    bitmap = bitmap_header + b"".join(pixels) + bytes(and_mask_row * size)
    icon_header = struct.pack("<HHH", 0, 1, 1)
    width_byte = 0 if size >= 256 else size
    height_byte = 0 if size >= 256 else size
    directory_entry = struct.pack(
        "<BBBBHHII",
        width_byte,
        height_byte,
        0,
        0,
        1,
        32,
        len(bitmap),
        22,
    )
    return icon_header + directory_entry + bitmap


def build_bundle(
    source: Path,
    output_directory: Path,
    *,
    allow_dirty: bool = False,
    target_name: str = "wsl",
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
    entries[target.bundle_root / "lys-bbb.ico"] = windows_icon_bytes()
    for relative in _payload_files(source, target.environment_file):
        entries[target.bundle_root / "app" / PurePosixPath(relative)] = (
            source / relative
        ).read_bytes()

    tracked_hashes = {
        str(path.relative_to(target.bundle_root)): _sha256(content)
        for path, content in sorted(entries.items(), key=lambda item: str(item[0]))
    }
    manifest = {
        "schema_version": 1,
        "application": "LYS BBB Scientific Workflows",
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = build_bundle(
            args.source,
            args.output_directory,
            allow_dirty=args.allow_dirty,
            target_name=args.target,
        )
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    print(f"sha256: {_sha256(output.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
