"""Shared, interpolation-free NIfTI storage-orientation operations."""

from __future__ import annotations

import nibabel as nib
from nibabel.orientations import axcodes2ornt, io_orientation, ornt_transform


CORONAL_AXCODES = ("R", "S", "A")


def to_coronal(image: nib.spatialimages.SpatialImage) -> nib.spatialimages.SpatialImage:
    """Reorder/flip voxel storage so axis 2 indexes coronal slices.

    The operation is derived from the NIfTI affine and does not interpolate or change
    the represented world-space anatomy.
    """

    target = axcodes2ornt(CORONAL_AXCODES)
    start = io_orientation(image.affine)
    return image.as_reoriented(ornt_transform(start, target))
