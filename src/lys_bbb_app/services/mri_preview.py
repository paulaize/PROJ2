"""Read-only anatomical previews of managed MRI inputs."""

from dataclasses import dataclass
from itertools import product
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import map_coordinates


@dataclass(frozen=True)
class CoronalPreview:
    pixels: bytes
    width: int
    height: int


def render_coronal_preview(path: Path, position: int = 50) -> CoronalPreview:
    """Sample a world-coronal plane, radiological R-left / S-up.

    Sampling and contrast adjustment affect only the thumbnail, never the MRI.
    World coordinates (not a fixed stored axis) also handle permuted/oblique scans.
    """
    if not 0 <= position <= 100:
        raise ValueError("Slice position must be between 0 and 100.")
    image = nib.load(path)
    if len(image.shape) != 3 or any(size < 1 for size in image.shape):
        raise ValueError("Preview requires a three-dimensional MRI.")
    affine = image.affine
    if not np.isfinite(affine).all():
        raise ValueError("MRI orientation is invalid.")
    inverse = np.linalg.inv(affine)
    corners = np.array(list(product(*((0, size - 1) for size in image.shape))))
    world = nib.affines.apply_affine(affine, corners)
    low, high = world.min(axis=0), world.max(axis=0)
    extent = high - low
    if extent[0] <= 0 or extent[2] <= 0:
        raise ValueError("MRI has no coronal field of view.")
    step = max(extent[0], extent[2]) / 319
    width = max(2, round(extent[0] / step) + 1)
    height = max(2, round(extent[2] / step) + 1)
    # Positive RAS X is right, positive Z is superior. Both decrease on screen.
    x, z = np.meshgrid(
        np.linspace(high[0], low[0], width), np.linspace(high[2], low[2], height)
    )
    y = np.full_like(x, low[1] + extent[1] * position / 100)
    voxels = nib.affines.apply_affine(inverse, np.stack((x, y, z), axis=-1))
    # Avoid floating-point boundary artefacts for exactly axis-aligned scans.
    for axis, size in enumerate(image.shape):
        coords = voxels[..., axis]
        coords[np.isclose(coords, 0, atol=1e-6)] = 0
        coords[np.isclose(coords, size - 1, atol=1e-6)] = size - 1
    data = image.get_fdata(dtype=np.float32)
    plane = map_coordinates(
        data,
        voxels.transpose(2, 0, 1),
        order=1,
        mode="constant",
        cval=0,
        prefilter=False,
    )
    plane = np.nan_to_num(plane, nan=0, posinf=0, neginf=0)
    foreground = plane[plane != 0]
    if foreground.size:
        dark, bright = np.percentile(foreground, (1, 99.5))
        if bright <= dark:
            dark, bright = min(0, float(dark)), max(1, float(bright))
        # Leave highlight headroom instead of stretching bright tissue to white.
        bright += 0.15 * (bright - dark)
        plane = np.clip((plane - dark) / (bright - dark), 0, 1)
    pixels = np.ascontiguousarray(np.rint(plane * 255), dtype=np.uint8)
    return CoronalPreview(pixels.tobytes(), width, height)
