# ruff: noqa: E402
"""Bruker T1 FLASH conversion utilities for the LYS BBB MRI pipeline.

The quantitative output is the native-resolution coronal NIfTI. Fiji-oriented
display copies and slab outputs are optional visualization products and should
not be used for analysis.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

import numpy as np

_cache_root = Path(tempfile.gettempdir()) / "lys_bbb_mri_cache"
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
for _cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    _cache_dir.mkdir(parents=True, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


import nibabel as nib
from nibabel.affines import rescale_affine
from nibabel.processing import resample_to_output

import brkraw

from lys_bbb.image_orientation import to_coronal

import brkraw.apps.loader.core as _brk_core

# (1) numpy is imported only under TYPE_CHECKING, but get_nifti1image() uses np at
#     runtime -> "NameError: name 'np' is not defined". Inject it.
if not hasattr(_brk_core, "np"):
    _brk_core.np = np

# (2) single-slice-pack scans (e.g. 3D FLASH, NumSlicePack=1) hand the image
#     builder a BARE array + BARE 4x4 instead of 1-tuples, so it indexes a row of
#     the affine -> "Affine should be shape 4,4". Wrap bare inputs in a 1-tuple.
if not getattr(_brk_core, "_single_pack_patched", False):
    _orig_get_nii = _brk_core._get_nifti1image

    def _get_nii_safe(self, reco_id, dataobjs, affines, **kw):
        if not isinstance(dataobjs, tuple):
            dataobjs = (dataobjs,)
        if not isinstance(affines, tuple):
            affines = (affines,)
        return _orig_get_nii(self, reco_id, dataobjs, affines, **kw)

    _brk_core._get_nifti1image = _get_nii_safe
    _brk_core._single_pack_patched = True


# use regex to find the appropriate files in brucker folder
PROTOCOL_PATTERN = r"T1_FLASH_3D"


def _first_str(obj):
    """
    useful to find all all text in brkraw info
    serves the objective of detecting where the protocole name is to
    then detect the T1 FLASH from the rest
    """
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            s = _first_str(v)
            if s:
                return s
    if isinstance(obj, (list, tuple)):
        for v in obj:
            s = _first_str(v)
            if s:
                return s
    return None


def protocol_name(study, sid):
    """looks for the protocole name"""
    return _first_str(study.search_params("ACQ_protocol_name", scan_id=sid)) or ""


def _all_scan_ids(study):
    avail = study.avail
    return list(avail.keys()) if isinstance(avail, dict) else list(avail)


def find_scans_by_protocol(study):
    """Return (targets, all_ids): scans that have an ACQ_protocol_name that contains T1_FLASH_3D"""
    all_ids = _all_scan_ids(study)
    pat = re.compile(PROTOCOL_PATTERN, re.IGNORECASE)
    targets = sorted(sid for sid in all_ids if pat.search(protocol_name(study, sid)))
    return targets, all_ids


def voxel_sizes(img):
    """Return voxel size for each image axis from the affine, in mm."""
    return np.linalg.norm(img.affine[:3, :3], axis=0)


def fmt_vox(img):
    return "x".join(f"{v:.4f}" for v in voxel_sizes(img))


def slab_width_vox(img, slab_mm):
    """Convert a coronal slab thickness in mm to an odd number of slices."""
    if slab_mm is None or slab_mm <= 0:
        return 1
    spacing = voxel_sizes(img)[2]
    width = max(1, int(round(slab_mm / spacing)))
    if width % 2 == 0:
        width += 1
    return width


def moving_average_axis(vol, axis, width):
    """Centered moving average along one axis, keeping the original shape."""
    if width <= 1:
        return vol.astype(np.float32, copy=False)
    half = width // 2
    moved = np.moveaxis(vol.astype(np.float32, copy=False), axis, 0)
    pad_width = [(half, half)] + [(0, 0)] * (moved.ndim - 1)
    padded = np.pad(moved, pad_width, mode="edge")
    cumsum = np.cumsum(padded, axis=0, dtype=np.float64)
    zeros = np.zeros_like(cumsum[:1])
    cumsum = np.concatenate([zeros, cumsum], axis=0)
    averaged = (cumsum[width:] - cumsum[:-width]) / width
    return np.moveaxis(averaged.astype(np.float32, copy=False), 0, axis)


def slabbed_volume(img, slab_mm):
    """Return data averaged through coronal slice axis for visual QC."""
    width = slab_width_vox(img, slab_mm)
    vol = img.get_fdata(dtype=np.float32)
    if width > 1:
        vol = moving_average_axis(vol, axis=2, width=width)
    return vol, width


def slabbed_image(img, slab_mm):
    """Return a same-grid NIfTI where every coronal slice is a moving slab."""
    vol, width = slabbed_volume(img, slab_mm)
    out = nib.Nifti1Image(vol, img.affine, header=img.header.copy())
    out.set_data_dtype(np.float32)
    out.header["descrip"] = f"moving coronal slab average, {width} slices"
    return out, width


def fiji_display_image(img, target_xy_mm=None, order=1):
    """Return a Fiji-friendly coronal display copy.

    The regular coronal NIfTI keeps native geometry for quantitative work. Fiji
    display copies intentionally flip the vertical image axis and upsample the
    thicker in-plane axis to square pixels so the slice looks like the QC PNGs
    even when Fiji displays raw pixels. These outputs are visualization only.
    """
    flipped = img.slicer[:, ::-1, :]
    vox = voxel_sizes(flipped)
    if target_xy_mm is None:
        target_xy_mm = float(min(vox[0], vox[1]))
    if target_xy_mm <= 0:
        raise ValueError("--fiji-display-xy-mm must be positive")

    shape = np.array(flipped.shape[:3], dtype=int)
    new_shape = shape.copy()
    new_shape[0] = max(1, int(round(shape[0] * vox[0] / target_xy_mm)))
    new_shape[1] = max(1, int(round(shape[1] * vox[1] / target_xy_mm)))

    data = flipped.get_fdata(dtype=np.float32)
    zoom_factors = new_shape / shape
    if not np.allclose(zoom_factors, 1.0):
        from scipy.ndimage import zoom
        data = zoom(data, zoom_factors, order=order)

    new_zooms = (float(target_xy_mm), float(target_xy_mm), float(vox[2]))
    new_affine = rescale_affine(flipped.affine, shape, new_zooms, new_shape)
    header = flipped.header.copy()
    out = nib.Nifti1Image(data.astype(np.float32, copy=False), new_affine, header)
    out.set_data_dtype(np.float32)
    out.header.set_zooms(new_zooms)
    out.set_qform(new_affine, code=1)
    out.set_sform(new_affine, code=2)
    out.header["descrip"] = "FIJI display copy; vertical flip + square XY; not quantitative"
    return out, {
        "source_shape": tuple(int(v) for v in shape),
        "display_shape": tuple(int(v) for v in new_shape),
        "source_vox": tuple(float(v) for v in vox),
        "display_vox": new_zooms,
    }


def percentile_window(vol, low=1.0, high=99.5):
    finite = vol[np.isfinite(vol)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.percentile(finite, [low, high])
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
    if vmin == vmax:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def coronal_extent(img):
    """Physical extent for a displayed coronal plane after np.rot90."""
    vox = voxel_sizes(img)
    nx = img.shape[0]  # left-right in the coronal volume
    ny = img.shape[1]  # inferior-superior in the coronal volume
    return [0, nx * vox[0], 0, ny * vox[1]]


def show_coronal_plane(ax, vol, k, img, *, cmap, vmin, vmax):
    # rot90 is display-only; the saved NIfTI orientation stays in the affine.
    ax.imshow(
        np.rot90(vol[:, :, k]),
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        origin="lower",
        extent=coronal_extent(img),
        aspect="equal",
    )
    ax.set_xticks([])
    ax.set_yticks([])


def qc_montage(img, png_path, n=9, slab_mm=0.4):
    """Save an n-slice coronal montage with correct physical pixel aspect."""
    vol, width = slabbed_volume(img, slab_mm)
    ks = np.linspace(vol.shape[2] * 0.2, vol.shape[2] * 0.8, n).astype(int)
    ks = np.clip(ks, 0, vol.shape[2] - 1)
    vmin, vmax = percentile_window(vol)
    side = int(np.ceil(np.sqrt(n)))
    fig, axes = plt.subplots(side, side, figsize=(9, 9))
    slab_text = ""
    if width > 1:
        slab_text = f"; QC slab={width} slices (~{width * voxel_sizes(img)[2]:.2f} mm)"
    for ax, k in zip(axes.ravel(), ks):
        show_coronal_plane(ax, vol, k, img, cmap="gray", vmin=vmin, vmax=vmax)
        ax.set_title(f"k={k}", fontsize=8)
    for ax in axes.ravel()[len(ks):]:
        ax.axis("off")
    fig.suptitle(f"{png_path.stem}{slab_text}", fontsize=9)
    fig.tight_layout()
    fig.savefig(png_path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def qc_pre_post_diff(pre_img, post_img, png_path, n=6, slab_mm=0.4):
    """Visual pre/post/difference QC for matching pre/post T1 FLASH scans."""
    if pre_img.shape != post_img.shape:
        print("  skip pair QC: pre/post shapes differ", file=sys.stderr)
        return
    if not np.allclose(pre_img.affine, post_img.affine, atol=1e-3):
        print("  skip pair QC: pre/post affines differ", file=sys.stderr)
        return

    pre, width = slabbed_volume(pre_img, slab_mm)
    post, _ = slabbed_volume(post_img, slab_mm)
    diff = post - pre
    vmin, vmax = percentile_window(np.concatenate([pre.ravel(), post.ravel()]))
    diff_lim = np.percentile(np.abs(diff[np.isfinite(diff)]), 99.0)
    if not np.isfinite(diff_lim) or diff_lim <= 0:
        diff_lim = 1.0

    ks = np.linspace(pre.shape[2] * 0.25, pre.shape[2] * 0.75, n).astype(int)
    ks = np.clip(ks, 0, pre.shape[2] - 1)
    fig, axes = plt.subplots(n, 3, figsize=(8, max(7, n * 2.1)))
    if n == 1:
        axes = axes.reshape(1, 3)
    for row, k in enumerate(ks):
        show_coronal_plane(axes[row, 0], pre, k, pre_img,
                           cmap="gray", vmin=vmin, vmax=vmax)
        show_coronal_plane(axes[row, 1], post, k, post_img,
                           cmap="gray", vmin=vmin, vmax=vmax)
        show_coronal_plane(axes[row, 2], diff, k, pre_img,
                           cmap="coolwarm", vmin=-diff_lim, vmax=diff_lim)
        axes[row, 0].set_ylabel(f"k={k}", fontsize=8)
        if row == 0:
            axes[row, 0].set_title("pre", fontsize=9)
            axes[row, 1].set_title("post", fontsize=9)
            axes[row, 2].set_title("post - pre", fontsize=9)
    slab_text = ""
    if width > 1:
        slab_text = f"; slab={width} slices (~{width * voxel_sizes(pre_img)[2]:.2f} mm)"
    fig.suptitle(f"{png_path.stem}{slab_text}", fontsize=9)
    fig.tight_layout()
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def process_scan(study, sid, out_dir, tag, iso, do_qc, qc_slab_mm,
                 write_slab_mm, write_fiji_display, fiji_display_xy_mm):
    """Convert one scan to NIfTI, reslice to coronal, write files (+ QC)."""
    stem = f"{tag}_scan-{sid}_T1FLASH3D"
    sag_path = out_dir / f"{stem}_sag.nii.gz"
    cor_path = out_dir / f"{stem}_coronal.nii.gz"

    # brkraw -> sagittal NIfTI (subject-RAS affine by default)
    conv = study.get_nifti1image(sid, reco_id=None)
    if isinstance(conv, (list, tuple)):           # multi-reco safety net
        conv = conv[0]
    conv.to_filename(str(sag_path))

    img = nib.load(sag_path)
    if iso is not None:
        src_vox = voxel_sizes(img)
        if iso < max(src_vox):
            print(f"  warning scan {sid}: --iso {iso:g} upsamples native "
                  f"{fmt_vox(img)} mm voxels and can add blur",
                  file=sys.stderr)
        img = resample_to_output(img, voxel_sizes=iso, order=1)
    img_cor = to_coronal(img)
    nib.save(img_cor, cor_path)

    if write_fiji_display:
        fiji_img, fiji_info = fiji_display_image(
            img_cor, target_xy_mm=fiji_display_xy_mm)
        fiji_path = out_dir / f"{stem}_coronal_fijiDisplay.nii.gz"
        nib.save(fiji_img, fiji_path)
    else:
        fiji_path = None
        fiji_info = None

    slab_path = None
    slab_width = 1
    slab_fiji_path = None
    slab_fiji_info = None
    if write_slab_mm is not None and write_slab_mm > 0:
        slab_img, slab_width = slabbed_image(img_cor, write_slab_mm)
        safe_mm = str(write_slab_mm).replace(".", "p")
        slab_path = out_dir / f"{stem}_coronal_slab{safe_mm}mm.nii.gz"
        nib.save(slab_img, slab_path)
        if write_fiji_display:
            slab_fiji_img, slab_fiji_info = fiji_display_image(
                slab_img, target_xy_mm=fiji_display_xy_mm)
            slab_fiji_path = out_dir / f"{stem}_coronal_slab{safe_mm}mm_fijiDisplay.nii.gz"
            nib.save(slab_fiji_img, slab_fiji_path)

    if do_qc:
        qc_montage(img_cor, out_dir / f"{stem}_coronalQC.png",
                   slab_mm=qc_slab_mm)

    print(f"  scan {sid}: {img.shape} {nib.aff2axcodes(img.affine)}"
          f"  ->  {img_cor.shape} {nib.aff2axcodes(img_cor.affine)}"
          f" vox={fmt_vox(img_cor)} mm"
          f"  [{protocol_name(study, sid)}]")
    if fiji_path is not None:
        print(f"    Fiji display: {fiji_path.name} "
              f"{fiji_info['source_shape']} -> {fiji_info['display_shape']} "
              f"vox={fiji_info['display_vox'][0]:.4f}x"
              f"{fiji_info['display_vox'][1]:.4f}x"
              f"{fiji_info['display_vox'][2]:.4f} mm "
              f"(vertical flip + square XY; visualization only)")
    if slab_path is not None:
        print(f"    slab volume: {slab_path.name} "
              f"({slab_width} moving slices, visualization only)")
    if slab_fiji_path is not None:
        print(f"    slab Fiji display: {slab_fiji_path.name} "
              f"{slab_fiji_info['source_shape']} -> {slab_fiji_info['display_shape']} "
              f"(visualization only)")

    return {
        "sid": sid,
        "stem": stem,
        "cor_path": cor_path,
    }


def process_session(bruker_dir, out_base, iso, do_qc, qc_slab_mm,
                    write_slab_mm, do_pair_qc, write_fiji_display,
                    fiji_display_xy_mm):
    """Process every target scan in one Bruker session folder; return out_dir."""
    out_dir = (out_base / bruker_dir.name if out_base
               else bruker_dir.parent / "coronal_out" / bruker_dir.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    study = brkraw.load(str(bruker_dir))
    targets, all_ids = find_scans_by_protocol(study)
    print(f"session : {bruker_dir.name}")
    print(f"scans   : {all_ids}")
    print(f"T1 FLASH 3D scans : {targets}")
    if not targets:
        raise RuntimeError(f"no scans matched /{PROTOCOL_PATTERN}/i in {bruker_dir.name}")

    tag = re.sub(r"[^A-Za-z0-9]+", "_", bruker_dir.name)
    results = []
    for sid in targets:
        results.append(process_scan(study, sid, out_dir, tag, iso, do_qc,
                                    qc_slab_mm, write_slab_mm,
                                    write_fiji_display, fiji_display_xy_mm))

    if len(targets) == 2:
        lo, hi = targets
        print(f"  likely: scan {lo} = PRE-contrast, scan {hi} = POST-contrast "
              f"(POST has bright vessels + Harderian glands; swap if reversed)")
        if do_qc and do_pair_qc:
            pre = nib.load(results[0]["cor_path"])
            post = nib.load(results[1]["cor_path"])
            pair_png = out_dir / f"{tag}_scan-{lo}_vs_scan-{hi}_T1FLASH3D_pre_post_diffQC.png"
            qc_pre_post_diff(pre, post, pair_png, slab_mm=qc_slab_mm)
    print(f"  -> {out_dir}")
    return out_dir


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Convert Bruker T1 FLASH 3D sagittal scans to coronal-primary NIfTI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("bruker_dirs", nargs="+", type=Path,
                   help="one or more raw Bruker session folders")
    p.add_argument("-o", "--out-dir", type=Path, default=None,
                   help="base output dir (default: <session>/../coronal_out/<session>)")
    p.add_argument("--iso", type=float, default=None,
                   help="isotropic voxel size in mm; omit to keep native resolution. "
                        "For these data, --iso below 0.15 mm upsamples and can blur.")
    p.add_argument("--qc-slab-mm", type=float, default=0.4,
                   help="moving slab thickness in mm for QC PNGs; use 0 for thin slices")
    p.add_argument("--write-slab-mm", type=float, default=None,
                   help="also write a same-grid moving-slab coronal NIfTI for visual review; "
                        "not for quantification")
    p.add_argument("--write-fiji-display", action="store_true",
                   help="write an additional vertically flipped, square-pixel NIfTI for "
                        "Fiji viewing only; never use it for quantification")
    p.add_argument("--fiji-display-xy-mm", type=float, default=None,
                   help="target X/Y pixel size in mm for Fiji display copies. "
                        "Default: min(native coronal X/Y voxel size).")
    p.add_argument("--no-pair-qc", action="store_true",
                   help="skip pre/post/difference QC when exactly two T1 FLASH scans are found")
    p.add_argument("--no-qc", action="store_true", help="skip writing QC montage PNGs")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.fiji_display_xy_mm is not None and not args.write_fiji_display:
        raise ValueError("--fiji-display-xy-mm requires --write-fiji-display")
    failures = []
    for d in args.bruker_dirs:
        d = d.expanduser()
        if not d.is_dir():
            print(f"skip (not a directory): {d}", file=sys.stderr)
            failures.append(d.name)
            continue
        try:
            process_session(d, args.out_dir, args.iso, not args.no_qc,
                            args.qc_slab_mm, args.write_slab_mm,
                            not args.no_pair_qc, args.write_fiji_display,
                            args.fiji_display_xy_mm)
        except Exception as exc:                  # keep the batch going; report at end
            print(f"FAILED {d.name}: {exc}", file=sys.stderr)
            failures.append(d.name)

    if failures:
        print(f"\n{len(failures)} session(s) failed: {', '.join(failures)}",
              file=sys.stderr)
        return 1
    print("\nall sessions done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
