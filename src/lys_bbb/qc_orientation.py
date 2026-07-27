"""Interpolation-free anatomical orientation helpers for native-slice QC."""

from __future__ import annotations

import nibabel as nib
import numpy as np


def orient_native_coronal_qc_slice(
    data: np.ndarray, affine: np.ndarray
) -> np.ndarray:
    """Orient a native axis-2 coronal plane with L left and S at the top."""

    if data.ndim != 2:
        raise ValueError("Coronal QC display requires a two-dimensional slice")
    axis_codes = tuple(str(code) for code in nib.aff2axcodes(affine))
    if not has_axis_2_coronal_layout(axis_codes):
        return np.rot90(data)
    left_right_axis = next(
        axis for axis in (0, 1) if axis_codes[axis] in {"L", "R"}
    )
    superior_inferior_axis = next(
        axis for axis in (0, 1) if axis_codes[axis] in {"S", "I"}
    )
    displayed = np.transpose(
        data,
        (
            superior_inferior_axis,
            left_right_axis,
        ),
    )
    if axis_codes[superior_inferior_axis] == "S":
        displayed = np.flip(displayed, axis=0)
    if axis_codes[left_right_axis] == "L":
        displayed = np.flip(displayed, axis=1)
    return displayed


def has_axis_2_coronal_layout(axis_codes: tuple[str, ...]) -> bool:
    return (
        len(axis_codes) == 3
        and axis_codes[2] in {"A", "P"}
        and sum(code in {"L", "R"} for code in axis_codes[:2]) == 1
        and sum(code in {"S", "I"} for code in axis_codes[:2]) == 1
    )


def coronal_display_metadata(affine: np.ndarray) -> dict[str, object]:
    axis_codes = tuple(str(code) for code in nib.aff2axcodes(affine))
    anatomical_coronal = has_axis_2_coronal_layout(axis_codes)
    return {
        "method": (
            "affine_aware_native_slice_no_resampling"
            if anatomical_coronal
            else "legacy_rot90_noncoronal_native_axis_2"
        ),
        "source_axis_codes": "".join(axis_codes),
        "source_slice_axis": 2,
        "anatomical_coronal": anatomical_coronal,
        "left": "L" if anatomical_coronal else None,
        "right": "R" if anatomical_coronal else None,
        "top": "S" if anatomical_coronal else None,
        "bottom": "I" if anatomical_coronal else None,
    }


def annotate_coronal_orientation(axis, affine: np.ndarray) -> None:
    axis_codes = tuple(str(code) for code in nib.aff2axcodes(affine))
    if not has_axis_2_coronal_layout(axis_codes):
        return
    style = {
        "color": "white",
        "fontsize": 6,
        "bbox": {"facecolor": "black", "alpha": 0.5, "pad": 0.7},
        "transform": axis.transAxes,
        "zorder": 10,
    }
    axis.text(0.01, 0.5, "L", ha="left", va="center", **style)
    axis.text(0.99, 0.5, "R", ha="right", va="center", **style)
    axis.text(0.5, 0.99, "S", ha="center", va="top", **style)
    axis.text(0.5, 0.01, "I", ha="center", va="bottom", **style)
