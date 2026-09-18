"""Convert confirmed MRI assignments into versioned NIfTI input artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np

from lys_bbb.hashing import sha256_file as _sha256_file

from lys_bbb.mri_import import (
    OrientationPolicy,
    ScanConversionResult,
    ScanImportAssignment,
    SourceFormat,
)


def convert_scan_assignment(
    assignment: ScanImportAssignment,
    *,
    output_directory: Path,
    work_directory: Path,
) -> ScanConversionResult:
    """Create one immutable quantitative NIfTI and its provenance manifest.

    Sources are read only. Import flips preserve anatomy in world coordinates;
    explicit manual orientation corrections change its anatomical mapping.
    """

    output_directory = Path(output_directory)
    work_directory = Path(work_directory)
    if output_directory.exists():
        raise FileExistsError(f"Import output version already exists: {output_directory}")
    staging = work_directory / assignment.proposal_id
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        image, source_hash = _load_source(assignment)
        if assignment.expected_source_sha256 and source_hash != assignment.expected_source_sha256:
            raise ValueError("The managed MRI has changed since import. Restore it before correcting orientation.")
        image = _validate_three_dimensional(image)
        if assignment.orientation_policy is OrientationPolicy.T1_CORONAL:
            from lys_bbb.image_orientation import to_coronal

            image = to_coronal(image)
        if assignment.orientation_correction:
            image = _correct_orientation(image, assignment.flip_axes)
        else:
            image = _apply_storage_axis_flips(image, assignment.flip_axes)
        _validate_image_geometry(image)

        filename = f"{assignment.role.value.casefold()}.nii.gz"
        staged_nifti = staging / filename
        nib.save(image, staged_nifti)
        output_hash = _sha256_file(staged_nifti)
        spacing = tuple(float(value) for value in image.header.get_zooms()[:3])
        axis_codes = tuple(str(value) for value in nib.aff2axcodes(image.affine))
        provenance = {
            "format": "lys-irm-scan-import",
            "version": 1,
            "subject_code": assignment.subject_code,
            "role": assignment.role.value,
            "source": {
                "format": assignment.source_format.value,
                "path": str(assignment.source_path),
                "session_id": assignment.session_id,
                "scan_id": assignment.scan_id,
                "protocol": assignment.protocol,
                "method": assignment.method,
                "sha256": source_hash,
            },
            "transform": {
                "orientation_policy": assignment.orientation_policy.value,
                "storage_axis_flips": [] if assignment.orientation_correction else list(assignment.flip_axes),
                "orientation_correction_axes": list(assignment.flip_axes) if assignment.orientation_correction else [],
                "interpolation": "none",
                "affine_updated": True,
            },
            "output": {
                "filename": filename,
                "sha256": output_hash,
                "shape": [int(value) for value in image.shape],
                "spacing_mm": list(spacing),
                "axis_codes": list(axis_codes),
            },
        }
        staged_provenance = staging / "provenance.json"
        staged_provenance.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")

        output_directory.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(output_directory)
        output_path = output_directory / filename
        return ScanConversionResult(
            output_path=output_path,
            output_sha256=output_hash,
            source_sha256=source_hash,
            shape=tuple(int(value) for value in image.shape),
            spacing_mm=spacing,
            axis_codes=axis_codes,
            provenance_path=output_directory / "provenance.json",
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def inspect_source_axis_codes(
    source_path: Path,
    source_format: SourceFormat,
    scan_id: int | None,
) -> tuple[str, str, str]:
    """Read source geometry without modifying or importing the scan."""

    source = Path(source_path)
    if source_format is SourceFormat.NIFTI:
        if not source.is_file():
            raise FileNotFoundError(f"NIfTI source file is unavailable: {source}")
        image = nib.load(source)
    else:
        image = _load_bruker_image(source, scan_id)
    image = _validate_three_dimensional(image)
    return tuple(str(value) for value in nib.aff2axcodes(image.affine))


def _load_source(assignment: ScanImportAssignment) -> tuple[nib.spatialimages.SpatialImage, str]:
    if assignment.source_format is SourceFormat.NIFTI:
        if not assignment.source_path.is_file():
            raise FileNotFoundError(f"NIfTI source file is unavailable: {assignment.source_path}")
        return nib.load(assignment.source_path), _sha256_file(assignment.source_path)

    session = assignment.source_path
    if assignment.scan_id is None:
        raise ValueError("A Bruker assignment requires a numeric scan ID.")
    scan_directory = session / str(assignment.scan_id)
    if not scan_directory.is_dir():
        raise FileNotFoundError(
            f"Bruker scan {assignment.scan_id} is unavailable below {session}"
        )
    return (
        _load_bruker_image(session, assignment.scan_id),
        _sha256_bruker_scan(scan_directory),
    )


def _load_bruker_image(
    session: Path,
    scan_id: int | None,
) -> nib.spatialimages.SpatialImage:
    if scan_id is None:
        raise ValueError("A Bruker assignment requires a numeric scan ID.")
    scan_directory = session / str(scan_id)
    if not scan_directory.is_dir():
        raise FileNotFoundError(
            f"Bruker scan {scan_id} is unavailable below {session}"
        )
    # Importing conversion applies the compatibility patches required by brkraw 0.5.7.
    from lys_bbb import conversion

    study = conversion.brkraw.load(str(session))
    converted = study.get_nifti1image(scan_id, reco_id=None)
    if isinstance(converted, (list, tuple)):
        if not converted:
            raise ValueError(
                f"Bruker scan {scan_id} produced no reconstructed image."
            )
        converted = converted[0]
    return converted


def _validate_three_dimensional(
    image: nib.spatialimages.SpatialImage,
) -> nib.spatialimages.SpatialImage:
    if len(image.shape) == 3:
        return image
    if len(image.shape) == 4 and image.shape[3] == 1:
        return image.slicer[:, :, :, 0]
    raise ValueError(
        f"Expected one three-dimensional MRI volume; received shape {image.shape}."
    )


def _correct_orientation(
    image: nib.spatialimages.SpatialImage,
    flip_axes: tuple[int, ...],
) -> nib.Nifti1Image:
    """Relabel misoriented anatomy about the volume centre, without resampling.

    Unlike storage reindexing, voxel order is unchanged: an orientation-aware
    viewer will display reflected anatomy. The original file is never modified.
    """
    if not flip_axes or not set(flip_axes) <= {0, 1, 2}:
        raise ValueError("Select valid axes for orientation correction.")
    transform = np.eye(4)
    for axis in set(flip_axes):
        transform[axis, axis] = -1
        transform[axis, 3] = image.shape[axis] - 1
    affine = image.affine @ transform
    corrected = nib.Nifti1Image(np.asanyarray(image.dataobj), affine, image.header.copy())
    # Refuse shear rather than write disagreeing qform/sform orientations.
    corrected.set_qform(affine, code=1, strip_shears=False)
    corrected.set_sform(affine, code=2)
    return corrected


def _apply_storage_axis_flips(
    image: nib.spatialimages.SpatialImage,
    flip_axes: tuple[int, ...],
) -> nib.spatialimages.SpatialImage:
    invalid = sorted(set(flip_axes) - {0, 1, 2})
    if invalid:
        raise ValueError(f"Unsupported storage-axis flips: {invalid}")
    slicing = tuple(
        slice(None, None, -1) if axis in flip_axes else slice(None)
        for axis in range(3)
    )
    if not flip_axes:
        return image
    data = np.asanyarray(image.dataobj)[slicing]
    index_transform = np.eye(4)
    for axis in flip_axes:
        index_transform[axis, axis] = -1
        index_transform[axis, 3] = image.shape[axis] - 1
    affine = image.affine @ index_transform
    header = image.header.copy()
    flipped = nib.Nifti1Image(data, affine, header=header)
    flipped.set_qform(affine, code=1)
    flipped.set_sform(affine, code=2)
    return flipped


def _validate_image_geometry(image: nib.spatialimages.SpatialImage) -> None:
    if any(int(value) <= 0 for value in image.shape):
        raise ValueError(f"The converted image has an invalid shape: {image.shape}")
    if not np.isfinite(image.affine).all():
        raise ValueError("The converted image affine contains non-finite values.")
    spacing = np.asarray(image.header.get_zooms()[:3], dtype=float)
    if spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0):
        raise ValueError(f"The converted image has invalid voxel spacing: {spacing}")

def _sha256_bruker_scan(scan_directory: Path) -> str:
    candidates = [scan_directory / "acqp", scan_directory / "method"]
    candidates.extend(sorted(scan_directory.glob("pdata/*/2dseq")))
    candidates.extend(sorted(scan_directory.glob("pdata/*/reco")))
    candidates.extend(sorted(scan_directory.glob("pdata/*/visu_pars")))
    files = [path for path in candidates if path.is_file()]
    if not files:
        raise FileNotFoundError(f"No hashable Bruker source files found in {scan_directory}")
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(scan_directory)).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()
