#!/usr/bin/env python
"""Install pinned MouseBSE, run one native T1, and open an editable mask."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.mask_qc import create_native_mask_qc_preview  # noqa: E402


MOUSEBSE_REPOSITORY = "https://github.com/MouseSuite/MouseBSE.git"
MOUSEBSE_COMMIT = "ef3039c68dde4f3649e454f365a883e2b1c48d2f"
MOUSEBSE_VERSION = "25a"
DEFAULT_CASE = "C23S3_D1_bis"
DEFAULT_TOOL_ROOT = (
    ROOT
    / "derivatives"
    / "brain_extraction"
    / "tools"
    / f"mousebse-v{MOUSEBSE_VERSION}-{MOUSEBSE_COMMIT[:7]}"
)
DEFAULT_OUTPUT_ROOT = ROOT / "derivatives" / "brain_extraction" / "mousebse_tests"
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_path(path: Path) -> Path:
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def machine_type() -> str:
    if platform.system() != "Darwin":
        raise RuntimeError(
            "This one-command installer currently targets macOS. On another OS, "
            "build MouseBSE separately and pass its executable with --mousebse."
        )
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise RuntimeError(f"Unsupported macOS architecture: {architecture}")
    return f"{architecture}-apple-darwin"


def mousebse_binary(source: Path, machtype: str) -> Path:
    return source / "bin" / machtype / f"mousebse{MOUSEBSE_VERSION}_{machtype}"


def checkout_commit(source: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_setup_command(command: list[str], log: list[str], cwd: Path | None = None) -> None:
    log.append(f"$ {shlex.join(command)}\n")
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log.append(completed.stdout)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Setup command failed ({completed.returncode}): {shlex.join(command)}\n"
            f"{completed.stdout[-3000:]}"
        )


def install_mousebse(tool_root: Path, jobs: int = 2) -> tuple[Path, dict[str, Any]]:
    """Install the exact official source revision without replacing an existing release."""

    machtype = machine_type()
    source = tool_root / "source"
    binary = mousebse_binary(source, machtype)
    release_path = tool_root / "release.json"

    if tool_root.exists():
        if not source.is_dir():
            raise RuntimeError(
                f"MouseBSE tool directory exists but is incomplete: {tool_root}"
            )
        commit = checkout_commit(source)
        if commit != MOUSEBSE_COMMIT:
            raise RuntimeError(
                f"Refusing unexpected MouseBSE revision in {source}: {commit}"
            )
        if not binary.exists():
            setup_log: list[str] = []
            _run_setup_command(
                ["make", f"-j{jobs}", f"MACHTYPE={machtype}"],
                setup_log,
                cwd=source,
            )
            (tool_root / "setup.log").write_text("".join(setup_log))
        if not binary.is_file():
            raise RuntimeError(f"MouseBSE build did not create {binary}")
        metadata = (
            json.loads(release_path.read_text()) if release_path.exists() else {}
        )
        metadata.update(
            {
                "repository": MOUSEBSE_REPOSITORY,
                "commit": MOUSEBSE_COMMIT,
                "version": MOUSEBSE_VERSION,
                "machtype": machtype,
                "executable": str(binary),
                "executable_sha256": sha256(binary),
            }
        )
        release_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        return binary, metadata

    tool_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{tool_root.name}-install-", dir=str(tool_root.parent)
        )
    )
    setup_log = []
    try:
        staging_source = staging / "source"
        _run_setup_command(
            ["git", "clone", "--no-checkout", MOUSEBSE_REPOSITORY, str(staging_source)],
            setup_log,
        )
        _run_setup_command(
            ["git", "-C", str(staging_source), "checkout", "--detach", MOUSEBSE_COMMIT],
            setup_log,
        )
        commit = checkout_commit(staging_source)
        if commit != MOUSEBSE_COMMIT:
            raise RuntimeError(
                f"MouseBSE checkout mismatch: expected {MOUSEBSE_COMMIT}, got {commit}"
            )
        _run_setup_command(
            ["make", f"-j{jobs}", f"MACHTYPE={machtype}"],
            setup_log,
            cwd=staging_source,
        )
        staging_binary = mousebse_binary(staging_source, machtype)
        if not staging_binary.is_file():
            raise RuntimeError(f"MouseBSE build did not create {staging_binary}")
        metadata = {
            "repository": MOUSEBSE_REPOSITORY,
            "commit": MOUSEBSE_COMMIT,
            "version": MOUSEBSE_VERSION,
            "machtype": machtype,
            "build_jobs": jobs,
            "installed_at_utc": datetime.now(timezone.utc).isoformat(),
            "executable": str(
                mousebse_binary(tool_root / "source", machtype)
            ),
            "executable_sha256": sha256(staging_binary),
        }
        (staging / "setup.log").write_text("".join(setup_log))
        (staging / "release.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        )
        os.replace(staging, tool_root)
        return mousebse_binary(tool_root / "source", machtype), metadata
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def validate_case_id(case_id: str) -> str:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "Case IDs may contain only letters, numbers, underscore, dash, and dot."
        )
    return case_id


def make_run_directory(output_root: Path, case_id: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{uuid.uuid4().hex[:6]}"
    run_directory = output_root / case_id / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def mousebse_command(
    executable: Path,
    input_path: Path,
    stripped_path: Path,
    raw_mask_path: Path,
    *,
    diffusion_constant: float,
    diffusion_iterations: int,
    edge_sigma: float,
    erosion_radius: int,
    closing_size: int,
    dilation_radius: int,
) -> list[str]:
    return [
        str(executable),
        "-i",
        str(input_path),
        "-o",
        str(stripped_path),
        "-d",
        str(diffusion_constant),
        "-n",
        str(diffusion_iterations),
        "-s",
        str(edge_sigma),
        "-r",
        str(erosion_radius),
        "-c",
        str(closing_size),
        "-p",
        str(dilation_radius),
        "--mask",
        str(raw_mask_path),
        "--norotate",
        "--timer",
    ]


def standardize_mask(
    input_path: Path, raw_mask_path: Path, output_path: Path
) -> dict[str, Any]:
    """Validate native geometry and save a 0/1 uint8 copy without resampling."""

    image = nib.load(str(input_path))
    raw_mask_image = nib.load(str(raw_mask_path))
    if image.ndim != 3 or raw_mask_image.ndim != 3:
        raise ValueError("MouseBSE testing requires three-dimensional NIfTI files.")
    if image.shape != raw_mask_image.shape:
        raise ValueError(
            f"MouseBSE changed the grid shape: {image.shape} -> "
            f"{raw_mask_image.shape}"
        )
    affine_difference = float(
        np.max(np.abs(np.asarray(image.affine) - np.asarray(raw_mask_image.affine)))
    )
    if not np.allclose(image.affine, raw_mask_image.affine, atol=1e-4, rtol=0):
        raise ValueError(
            "MouseBSE changed the image affine; the output was not resampled "
            f"automatically (maximum difference {affine_difference:.6g})."
        )

    raw = np.asanyarray(raw_mask_image.dataobj)
    if not np.all(np.isfinite(raw)):
        raise ValueError("MouseBSE mask contains non-finite values.")
    binary = raw > 0
    voxel_count = int(binary.sum())
    total_voxels = int(binary.size)
    if voxel_count == 0 or voxel_count == total_voxels:
        raise ValueError(
            f"MouseBSE produced a degenerate mask ({voxel_count}/{total_voxels} voxels)."
        )

    header = image.header.copy()
    header.set_data_dtype(np.uint8)
    header["cal_min"] = 0
    header["cal_max"] = 1
    standardized = nib.Nifti1Image(binary.astype(np.uint8), image.affine, header)
    qform, qform_code = image.get_qform(coded=True)
    sform, sform_code = image.get_sform(coded=True)
    standardized.set_qform(qform, int(qform_code))
    standardized.set_sform(sform, int(sform_code))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(standardized, str(output_path))

    labels, component_count = ndimage.label(binary)
    sizes = np.bincount(labels.ravel())[1:]
    largest_component = int(sizes.max()) if sizes.size else 0
    zooms = image.header.get_zooms()[:3]
    voxel_volume_mm3 = float(np.prod(zooms))
    warnings: list[str] = []
    fraction = voxel_count / total_voxels
    if fraction < 0.05 or fraction > 0.80:
        warnings.append(
            f"Unusual mask fraction ({fraction:.1%}); inspect every slice carefully."
        )
    if component_count > 1:
        warnings.append(
            f"Mask has {component_count} connected components before manual correction."
        )
    return {
        "shape": list(image.shape),
        "affine_max_abs_difference": affine_difference,
        "raw_values": [float(value) for value in np.unique(raw).tolist()],
        "binary_values": [0, 1],
        "mask_voxels": voxel_count,
        "mask_fraction": fraction,
        "mask_volume_mm3": voxel_count * voxel_volume_mm3,
        "connected_components": int(component_count),
        "largest_component_voxels": largest_component,
        "largest_component_fraction": (
            largest_component / voxel_count if voxel_count else 0.0
        ),
        "warnings": warnings,
    }


def discover_itksnap(explicit: Path | None = None) -> Path | None:
    candidates = [
        explicit,
        Path(found) if (found := shutil.which("itksnap")) else None,
        Path(found) if (found := shutil.which("ITK-SNAP")) else None,
        Path("/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP"),
        Path("/Applications/ITK-SNAP.app/Contents/bin/itksnap"),
    ]
    return next(
        (candidate for candidate in candidates if candidate and candidate.exists()),
        None,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the pinned official MouseBSE release, test one pre_coronal T1, "
            "create a native-grid editable mask, and open it in ITK-SNAP."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("output/all_mice"),
        help="directory containing <case>/pre_coronal.nii.gz",
    )
    parser.add_argument("--tool-root", type=Path, default=DEFAULT_TOOL_ROOT)
    parser.add_argument(
        "--mousebse",
        type=Path,
        default=None,
        help="use an existing executable instead of installing the pinned release",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--viewer", type=Path, default=None)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="install/validate MouseBSE, then stop before processing an image",
    )
    parser.add_argument("--build-jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--diffusion-constant", type=float, default=50.0)
    parser.add_argument("--diffusion-iterations", type=int, default=10)
    parser.add_argument("--edge-sigma", type=float, default=0.64)
    parser.add_argument("--erosion-radius", type=int, default=1)
    parser.add_argument("--closing-size", type=int, default=8)
    parser.add_argument("--dilation-radius", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not 1 <= args.build_jobs <= 4:
            raise ValueError("--build-jobs must be between 1 and 4.")
        if args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be positive.")

        if args.mousebse:
            executable = project_path(args.mousebse)
            if not executable.is_file():
                raise FileNotFoundError(f"MouseBSE executable not found: {executable}")
            release = {
                "repository": "user-supplied executable",
                "commit": None,
                "version": None,
                "executable": str(executable),
                "executable_sha256": sha256(executable),
            }
        else:
            tool_root = project_path(args.tool_root)
            print(
                "Installing or validating pinned MouseBSE v25a "
                f"({MOUSEBSE_COMMIT[:7]})..."
            )
            executable, release = install_mousebse(
                tool_root, jobs=args.build_jobs
            )
        print(f"MouseBSE: {executable}")
        if args.install_only:
            return 0

        case_id = validate_case_id(args.case)
        input_root = project_path(args.input_root)
        input_path = (input_root / case_id / "pre_coronal.nii.gz").resolve()
        if input_root not in input_path.parents:
            raise ValueError("Resolved input escaped --input-root.")
        if not input_path.is_file():
            raise FileNotFoundError(f"Input T1 not found: {input_path}")

        run_directory = make_run_directory(
            project_path(args.output_root), case_id
        )
        automatic_directory = run_directory / "automatic"
        editable_directory = run_directory / "editable"
        qc_directory = run_directory / "qc"
        automatic_directory.mkdir()
        editable_directory.mkdir()
        qc_directory.mkdir()
        raw_mask = automatic_directory / "mousebse_raw_mask.nii.gz"
        stripped = automatic_directory / "mousebse_skull_stripped.nii.gz"
        standardized = (
            automatic_directory / f"{case_id}_mousebse_binary_mask.nii.gz"
        )
        editable = editable_directory / f"{case_id}_mousebse_editable_mask.nii.gz"
        qc_preview = qc_directory / f"{case_id}_mousebse_overlay.png"
        log_path = run_directory / "mousebse.log"

        command = mousebse_command(
            executable,
            input_path,
            stripped,
            raw_mask,
            diffusion_constant=args.diffusion_constant,
            diffusion_iterations=args.diffusion_iterations,
            edge_sigma=args.edge_sigma,
            erosion_radius=args.erosion_radius,
            closing_size=args.closing_size,
            dilation_radius=args.dilation_radius,
        )
        print(f"Running MouseBSE on {case_id}...")
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=run_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout_seconds,
        )
        elapsed_seconds = time.monotonic() - started
        log_path.write_text(
            f"$ {shlex.join(command)}\n\n{completed.stdout}"
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"MouseBSE failed with code {completed.returncode}. See {log_path}"
            )
        if not raw_mask.is_file() or not stripped.is_file():
            raise RuntimeError(f"MouseBSE did not create its expected outputs. See {log_path}")

        metrics = standardize_mask(input_path, raw_mask, standardized)
        shutil.copy2(standardized, editable)
        create_native_mask_qc_preview(input_path, standardized, qc_preview)
        manifest = {
            "status": "automatic_draft_requires_manual_review",
            "scientific_use": (
                "Do not use for quantification until the editable mask has been "
                "reviewed and explicitly approved."
            ),
            "case_id": case_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed_seconds,
            "input": {
                "path": str(input_path),
                "sha256": sha256(input_path),
            },
            "mousebse_release": release,
            "command": command,
            "parameters": {
                "diffusion_constant": args.diffusion_constant,
                "diffusion_iterations": args.diffusion_iterations,
                "edge_sigma": args.edge_sigma,
                "erosion_radius": args.erosion_radius,
                "closing_size": args.closing_size,
                "dilation_radius": args.dilation_radius,
                "norotate": True,
            },
            "validation": metrics,
            "outputs": {
                "raw_mask": {
                    "path": str(raw_mask),
                    "sha256": sha256(raw_mask),
                },
                "standardized_binary_mask": {
                    "path": str(standardized),
                    "sha256": sha256(standardized),
                },
                "editable_mask": {
                    "path": str(editable),
                    "initial_sha256": sha256(editable),
                },
                "skull_stripped_image": {
                    "path": str(stripped),
                    "sha256": sha256(stripped),
                },
                "qc_preview": str(qc_preview),
                "all_slice_overlays": str(qc_directory / "qc_slices"),
                "log": str(log_path),
            },
        }
        manifest_path = run_directory / "run_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )

        print(f"Completed in {elapsed_seconds:.2f} seconds.")
        print(f"Editable mask: {editable}")
        print(f"QC preview:    {qc_preview}")
        print(f"Run record:    {manifest_path}")
        for warning in metrics["warnings"]:
            print(f"QC warning: {warning}")

        if args.no_open:
            print("ITK-SNAP launch skipped (--no-open).")
            return 0
        viewer = discover_itksnap(
            project_path(args.viewer) if args.viewer else None
        )
        if viewer is None:
            print(
                "ITK-SNAP was not found. Open the input as the main image and "
                f"this editable segmentation manually: {editable}",
                file=sys.stderr,
            )
            return 0
        viewer_command = [
            str(viewer),
            "-g",
            str(input_path),
            "-s",
            str(editable),
        ]
        subprocess.Popen(
            viewer_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"Opened ITK-SNAP: {shlex.join(viewer_command)}")
        print(
            "Edit only the loaded editable mask. Save it in place, and inspect "
            "the full anterior-posterior extent before judging the result."
        )
        return 0
    except subprocess.TimeoutExpired as error:
        print(
            f"ERROR: MouseBSE exceeded the {error.timeout}-second safety timeout.",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
