#!/usr/bin/env python
"""Create an N4-bias-corrected copy of a cloud MouseBrainExtractor package."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np


def copy_cloud_scripts(package_root: Path) -> None:
    source_dir = Path(__file__).resolve().parent
    target_dir = package_root / "scripts" / "cloud_mbe"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "external_mask_utils.py",
        "run_mousebrainextractor.py",
        "run_mbe_batch.py",
    ):
        shutil.copy2(source_dir / name, target_dir / name)


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "image", "manual"])
        writer.writeheader()
        writer.writerows(rows)


def finite_percentiles(data: np.ndarray, percentiles: tuple[float, float]) -> tuple[float, float]:
    values = data[np.isfinite(data)]
    if values.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(values, percentiles)
    if high <= low:
        high = low + 1.0
    return float(low), float(high)


def n4_bias_correct(
    image_path: Path,
    out_path: Path,
    *,
    shrink_factor: int,
    otsu_bins: int,
    iterations: list[int],
) -> dict[str, Any]:
    import SimpleITK as sitk

    image = sitk.Cast(sitk.ReadImage(str(image_path)), sitk.sitkFloat32)
    mask = sitk.OtsuThreshold(image, 0, 1, otsu_bins)
    shrink = [max(1, shrink_factor)] * image.GetDimension()
    image_shrunk = sitk.Shrink(image, shrink)
    mask_shrunk = sitk.Shrink(mask, shrink)

    corrector = sitk.N4BiasFieldCorrectionImageFilter()
    corrector.SetMaximumNumberOfIterations([int(v) for v in iterations])
    corrector.Execute(image_shrunk, mask_shrunk)
    log_bias = corrector.GetLogBiasFieldAsImage(image)
    corrected = image / sitk.Exp(log_bias)

    raw_arr = sitk.GetArrayFromImage(image)
    corr_arr = sitk.GetArrayFromImage(corrected)
    mask_arr = sitk.GetArrayFromImage(mask) > 0
    valid_raw = raw_arr[mask_arr & np.isfinite(raw_arr) & (raw_arr > 0)]
    valid_corr = corr_arr[mask_arr & np.isfinite(corr_arr) & (corr_arr > 0)]
    raw_median = float(np.median(valid_raw)) if valid_raw.size else 1.0
    corr_median = float(np.median(valid_corr)) if valid_corr.size else 1.0
    scale = raw_median / max(corr_median, 1e-6)
    corrected = corrected * scale

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(sitk.Cast(corrected, sitk.sitkFloat32), str(out_path))

    return {
        "input": str(image_path),
        "output": str(out_path),
        "method": "SimpleITK N4BiasFieldCorrection",
        "foreground_mask": "SimpleITK OtsuThreshold on raw pre-Gd T1",
        "shrink_factor": shrink_factor,
        "otsu_bins": otsu_bins,
        "iterations": iterations,
        "foreground_voxels": int(np.count_nonzero(mask_arr)),
        "raw_foreground_median": raw_median,
        "corrected_foreground_median_before_rescale": corr_median,
        "rescale_to_raw_median": scale,
    }


def write_biascorr_qc(raw_path: Path, corr_path: Path, qc_path: Path, *, n_slices: int) -> None:
    raw = nib.load(str(raw_path)).get_fdata(dtype=np.float32)
    corr = nib.load(str(corr_path)).get_fdata(dtype=np.float32)
    vmin, vmax = finite_percentiles(np.concatenate([raw.ravel(), corr.ravel()]), (1.0, 99.5))
    slices = np.linspace(0, raw.shape[2] - 1, n_slices).astype(int)
    fig, axes = plt.subplots(2, len(slices), figsize=(2.0 * len(slices), 4.2))
    for col, k in enumerate(slices):
        axes[0, col].imshow(np.rot90(raw[:, :, k]), cmap="gray", vmin=vmin, vmax=vmax)
        axes[0, col].set_title(f"raw k={k}", fontsize=8)
        axes[1, col].imshow(np.rot90(corr[:, :, k]), cmap="gray", vmin=vmin, vmax=vmax)
        axes[1, col].set_title("N4 bias-corr", fontsize=8)
        for row in (0, 1):
            axes[row, col].set_xticks([])
            axes[row, col].set_yticks([])
    fig.tight_layout()
    qc_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(qc_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def zip_dir(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir.parent))


def parse_iterations(value: str) -> list[int]:
    iterations = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not iterations:
        raise argparse.ArgumentTypeError("at least one N4 iteration count is required")
    return iterations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a parallel MouseBrainExtractor cloud package whose inputs "
            "are pre-segmentation N4 bias-corrected copies of an existing package."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("derivatives/cloud_mbe"))
    parser.add_argument("--package-name", default=None)
    parser.add_argument("--shrink-factor", type=int, default=4)
    parser.add_argument("--otsu-bins", type=int, default=128)
    parser.add_argument("--iterations", type=parse_iterations, default=parse_iterations("50,30,20"))
    parser.add_argument("--qc-slices", type=int, default=7)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_package = args.source_package.expanduser()
    package_name = args.package_name or f"{source_package.name}_biascorr"
    package_root = args.out_dir.expanduser() / package_name
    if package_root.exists():
        if not args.overwrite:
            raise FileExistsError(f"output package already exists: {package_root}")
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)

    source_manifest = source_package / "manifest.csv"
    rows = read_manifest(source_manifest)
    out_rows: list[dict[str, str]] = []
    metadata_rows: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["case_id"]
        source_image = source_package / row["image"]
        out_image = package_root / "inputs" / case_id / "pre_coronal.nii.gz"
        meta = n4_bias_correct(
            source_image,
            out_image,
            shrink_factor=args.shrink_factor,
            otsu_bins=args.otsu_bins,
            iterations=args.iterations,
        )
        meta["case_id"] = case_id
        metadata_rows.append(meta)
        write_biascorr_qc(
            source_image,
            out_image,
            package_root / "qc" / f"{case_id}_raw_vs_n4_biascorr.png",
            n_slices=args.qc_slices,
        )
        manual = row.get("manual", "")
        if manual:
            manual_source = source_package / manual
            manual_out = package_root / manual
            manual_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manual_source, manual_out)
        out_rows.append({
            "case_id": case_id,
            "image": str(out_image.relative_to(package_root)),
            "manual": manual,
        })

    write_manifest(package_root / "manifest.csv", out_rows)
    selection = source_package / "selection.txt"
    if selection.exists():
        shutil.copy2(selection, package_root / "selection.txt")
    else:
        (package_root / "selection.txt").write_text(
            "\n".join(row["case_id"] for row in out_rows) + "\n"
        )
    copy_cloud_scripts(package_root)

    metadata_path = package_root / "biascorr_metadata.json"
    metadata_path.write_text(json.dumps({
        "source_package": str(source_package),
        "package_name": package_name,
        "purpose": (
            "Comparison package for MouseBrainExtractor inference after "
            "pre-segmentation N4 bias correction. Outputs are still pre-labels."
        ),
        "warning": (
            "This is an experimental branch for visual comparison. It is not "
            "the default V1 segmentation preprocessing."
        ),
        "cases": metadata_rows,
    }, indent=2) + "\n")
    (package_root / "README.md").write_text(
        "# Bias-Corrected MouseBrainExtractor Comparison Package\n\n"
        "This package is a parallel version of the source MBE package with N4 "
        "bias correction applied to each pre-Gd T1 `pre_coronal.nii.gz` before "
        "MouseBrainExtractor inference.\n\n"
        "Use it only to visually compare pre-label quality against the raw-input "
        "MouseBrainExtractor package. Any output masks remain pre-labels and "
        "must still be corrected in ITK-SNAP before final quantification or "
        "nnU-Net training.\n\n"
        "Run on the cloud from the package root with:\n\n"
        "```bash\n"
        "python scripts/cloud_mbe/run_mbe_batch.py --manifest manifest.csv "
        "--out-dir derivatives/brain_seg/external/mousebrainextractor_biascorr\n"
        "```\n"
    )

    print(f"package folder: {package_root}")
    print(f"cases: {len(out_rows)}")
    print(f"manifest: {package_root / 'manifest.csv'}")
    print(f"metadata: {metadata_path}")
    if not args.no_zip:
        zip_path = args.out_dir.expanduser() / f"{package_name}.zip"
        zip_dir(package_root, zip_path)
        print(f"zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
