"""Inference-only adapters for packaged LYS T2 lesion models.

LYS v3 uses the inspected nnU-Net v2.8.1 predictor API and thresholds exported
native-grid lesion probabilities itself. The frozen LYS v1 RatLesNetV2 runner is
retained as the selectable small-model option.
"""

from __future__ import annotations

import csv
import importlib
import json
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable

import nibabel as nib
import numpy as np

from lys_bbb.t2_model_release import FrozenT2ModelRelease, sha256_file


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class T2InferenceCaseOutput:
    case_id: str
    source_scan: Path
    prepared_scan: Path
    probability_path: Path
    mask_path: Path
    probability_sha256: str
    mask_sha256: str
    lesion_voxel_count: int
    lesion_volume_mm3: float
    shape: tuple[int, int, int]
    spacing_mm: tuple[float, float, float]
    axis_codes: tuple[str, str, str]


@dataclass(frozen=True)
class T2InferenceOutput:
    release_id: str
    device: str
    threshold: float
    cases: tuple[T2InferenceCaseOutput, ...]
    manifest_path: Path
    summary_path: Path


def run_t2_model_inference(
    release: FrozenT2ModelRelease,
    case_scans: dict[str, Path],
    **kwargs: Any,
) -> T2InferenceOutput:
    """Dispatch a validated model choice to its inference-only runtime."""

    if release.runner == "nnunetv2":
        return run_nnunet_t2_inference(release, case_scans, **kwargs)
    if release.runner == "ratlesnetv2":
        return run_frozen_t2_ensemble(release, case_scans, **kwargs)
    raise ValueError(f"Unsupported T2 inference runner: {release.runner!r}")


def run_nnunet_t2_inference(
    release: FrozenT2ModelRelease,
    case_scans: dict[str, Path],
    *,
    work_root: Path,
    output_root: Path,
    device_name: str = "auto",
    progress: ProgressCallback | None = None,
) -> T2InferenceOutput:
    """Run LYS v3 nnU-Net and save native lesion probabilities and 0.20 masks."""

    if release.runner != "nnunetv2":
        raise ValueError("The selected release is not an nnU-Net model.")
    if not case_scans:
        raise ValueError("At least one T2 scan is required for inference.")
    if output_root.exists():
        raise FileExistsError(f"T2 inference output already exists: {output_root}")
    if work_root.exists():
        raise FileExistsError(
            f"T2 inference work directory already exists: {work_root}"
        )

    work_root.mkdir(parents=True)
    prepared_root = work_root / "prepared_inputs"
    raw_prediction_root = work_root / "nnunet_predictions"
    prepared: dict[str, Path] = {}
    total = len(case_scans)
    for index, (case_id, scan_path) in enumerate(sorted(case_scans.items()), start=1):
        _validate_case_id(case_id)
        if progress is not None:
            progress(index - 1, total, f"Preparing T2 input {index} of {total}")
        target = prepared_root / f"{case_id}_0000.nii.gz"
        prepare_nnunet_t2_scan(
            Path(scan_path),
            target,
            expected_spacing=release.expected_spacing_mm,
        )
        prepared[case_id] = target

    torch, predictor_class = _load_nnunet_runtime()
    device = _select_device(torch, device_name)
    if progress is not None:
        fold_text = "+".join(str(fold) for fold in release.folds)
        progress(0, total, f"Loading LYS v3 nnU-Net fold {fold_text}")
    predictor = predictor_class(
        tile_step_size=0.5,
        use_gaussian=True,
        use_mirroring=True,
        perform_everything_on_device=device.type == "cuda",
        device=device,
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=False,
    )
    predictor.initialize_from_trained_model_folder(
        str(release.architecture_path),
        use_folds=release.folds,
        checkpoint_name=release.checkpoint_name,
    )
    if progress is not None:
        progress(0, total, "Running native-grid lesion-probability inference")
    predictor.predict_from_files(
        str(prepared_root),
        str(raw_prediction_root),
        save_probabilities=True,
        overwrite=True,
        num_processes_preprocessing=1,
        num_processes_segmentation_export=1,
    )

    output_root.mkdir(parents=True)
    outputs: list[T2InferenceCaseOutput] = []
    manifest_rows: list[dict[str, Any]] = []
    for index, (case_id, prepared_path) in enumerate(
        sorted(prepared.items()), start=1
    ):
        reference = nib.load(str(Path(case_scans[case_id]).expanduser().resolve()))
        native_shape = tuple(int(value) for value in reference.shape[:3])
        probability_archive = raw_prediction_root / f"{case_id}.npz"
        if not probability_archive.is_file():
            raise RuntimeError(
                f"nnU-Net did not export lesion probabilities for case {case_id!r}."
            )
        with np.load(probability_archive) as archive:
            probabilities = np.asarray(archive["probabilities"], dtype=np.float32)
        if probabilities.ndim != 4 or probabilities.shape[0] != 2:
            raise ValueError(
                f"Unexpected nnU-Net probability shape for {case_id!r}: "
                f"{probabilities.shape}."
            )
        lesion_probability = _nnunet_probability_to_native_shape(
            probabilities[1],
            native_shape,
            case_id=case_id,
        )
        lesion_mask = threshold_lesion_probability(
            lesion_probability, release.threshold, case_id=case_id
        )

        case_output = output_root / "cases" / case_id
        case_output.mkdir(parents=True)
        probability_path = case_output / "lesion_probability.nii.gz"
        mask_path = case_output / "draft_lesion_mask.nii.gz"
        _save_nifti_like(probability_path, lesion_probability, reference)
        _save_nifti_like(mask_path, lesion_mask, reference)
        source_scan = Path(case_scans[case_id]).expanduser().resolve()
        _validate_native_output(source_scan, probability_path, mask_path)
        spacing = tuple(float(value) for value in reference.header.get_zooms()[:3])
        voxel_count = int(np.count_nonzero(lesion_mask))
        volume_mm3 = float(voxel_count * np.prod(spacing))
        case_result = T2InferenceCaseOutput(
            case_id=case_id,
            source_scan=source_scan,
            prepared_scan=prepared_path,
            probability_path=probability_path,
            mask_path=mask_path,
            probability_sha256=sha256_file(probability_path),
            mask_sha256=sha256_file(mask_path),
            lesion_voxel_count=voxel_count,
            lesion_volume_mm3=volume_mm3,
            shape=native_shape,
            spacing_mm=spacing,
            axis_codes=tuple(str(value) for value in nib.aff2axcodes(reference.affine)),
        )
        outputs.append(case_result)
        manifest_rows.append(
            {
                "case_id": case_id,
                "input_scan": str(source_scan),
                "prepared_scan": str(prepared_path),
                "lesion_probability": str(probability_path),
                "draft_lesion_mask": str(mask_path),
                "probability_sha256": case_result.probability_sha256,
                "mask_sha256": case_result.mask_sha256,
                "threshold": release.threshold,
                "folds": "+".join(str(fold) for fold in release.folds),
                "postprocessing": "none",
                "lesion_voxel_count": voxel_count,
                "provisional_lesion_volume_mm3": volume_mm3,
            }
        )
        if progress is not None:
            progress(index, total, f"Saved draft lesion mask {index} of {total}")

    manifest_path = output_root / "inference_manifest.csv"
    with manifest_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary_path = output_root / "inference_summary.json"
    summary = {
        "release_id": release.id,
        "architecture": "standard PlainConvUNet",
        "nnunet_version": "2.8.1",
        "device": str(device),
        "n_cases": len(outputs),
        "folds": list(release.folds),
        "fold_ensemble": release.metadata.get("fold_ensemble"),
        "model_sha256": list(release.model_sha256),
        "threshold": release.threshold,
        "threshold_provenance": release.metadata.get("threshold_provenance"),
        "postprocessing": "none",
        "lesion_probabilities_saved": True,
        "native_affine_preserved": True,
        "predictions_are_drafts": True,
        "human_review_required": True,
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return T2InferenceOutput(
        release_id=release.id,
        device=str(device),
        threshold=release.threshold,
        cases=tuple(outputs),
        manifest_path=manifest_path,
        summary_path=summary_path,
    )


def run_frozen_t2_ensemble(
    release: FrozenT2ModelRelease,
    case_scans: dict[str, Path],
    *,
    work_root: Path,
    output_root: Path,
    device_name: str = "auto",
    progress: ProgressCallback | None = None,
) -> T2InferenceOutput:
    """Run a validated release for one or more native-space T2 inputs."""

    if not case_scans:
        raise ValueError("At least one T2 scan is required for inference.")
    if output_root.exists():
        raise FileExistsError(f"T2 inference output already exists: {output_root}")
    if work_root.exists():
        raise FileExistsError(
            f"T2 inference work directory already exists: {work_root}"
        )
    work_root.mkdir(parents=True)
    prepared_root = work_root / "prepared_inputs"
    prepared: dict[str, Path] = {}
    total = len(case_scans)
    for index, (case_id, scan_path) in enumerate(sorted(case_scans.items()), start=1):
        _validate_case_id(case_id)
        if progress is not None:
            progress(index - 1, total, f"Preparing T2 input {index} of {total}")
        target = prepared_root / case_id / "scan.nii.gz"
        prepare_t2_inference_scan(
            Path(scan_path),
            target,
            expected_spacing=release.expected_spacing_mm,
        )
        prepared[case_id] = target

    if progress is not None:
        progress(0, total, "Loading five frozen RatLesNetV2 models")
    torch, model_class = _load_runtime(release)
    device = _select_device(torch, device_name)
    models = []
    for model_path in release.model_paths:
        model = model_class(modalities=1, filters=32)
        model.to(device)
        state = torch.load(model_path, map_location=device, weights_only=True)
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        model.load_state_dict(state)
        model.eval()
        models.append(model)

    output_root.mkdir(parents=True)
    outputs: list[T2InferenceCaseOutput] = []
    manifest_rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for index, (case_id, prepared_path) in enumerate(
            sorted(prepared.items()), start=1
        ):
            if progress is not None:
                progress(index - 1, total, f"Segmenting T2 subject {index} of {total}")
            reference = nib.load(str(prepared_path))
            native_shape = tuple(int(value) for value in reference.shape[:3])
            tensor = _load_normalized_tensor(reference, torch, device)
            model_probabilities = []
            for model in models:
                prediction = model(tensor)[0]
                probability = _lesion_probability_map(prediction)
                probability = _prediction_to_native_shape(probability, native_shape)
                finite = probability[np.isfinite(probability)]
                if (
                    not finite.size
                    or float(finite.min()) < 0.0
                    or float(finite.max()) > 1.0
                ):
                    raise ValueError(
                        f"Invalid lesion probabilities for case {case_id!r}."
                    )
                model_probabilities.append(probability.astype(np.float32, copy=False))

            ensemble_probability = np.mean(
                np.stack(model_probabilities, axis=0), axis=0, dtype=np.float32
            )
            ensemble_mask = (ensemble_probability >= release.threshold).astype(np.uint8)
            case_output = output_root / "cases" / case_id
            case_output.mkdir(parents=True)
            probability_path = case_output / "ensemble_probability.nii.gz"
            mask_path = case_output / "ensemble_mask.nii.gz"
            _save_nifti_like(probability_path, ensemble_probability, reference)
            _save_nifti_like(mask_path, ensemble_mask, reference)
            source_scan = Path(case_scans[case_id]).expanduser().resolve()
            _validate_native_output(source_scan, probability_path, mask_path)
            spacing = tuple(float(value) for value in reference.header.get_zooms()[:3])
            voxel_count = int(np.count_nonzero(ensemble_mask))
            volume_mm3 = float(voxel_count * np.prod(spacing))
            output = T2InferenceCaseOutput(
                case_id=case_id,
                source_scan=source_scan,
                prepared_scan=prepared_path,
                probability_path=probability_path,
                mask_path=mask_path,
                probability_sha256=sha256_file(probability_path),
                mask_sha256=sha256_file(mask_path),
                lesion_voxel_count=voxel_count,
                lesion_volume_mm3=volume_mm3,
                shape=native_shape,
                spacing_mm=spacing,
                axis_codes=tuple(
                    str(value) for value in nib.aff2axcodes(reference.affine)
                ),
            )
            outputs.append(output)
            manifest_rows.append(
                {
                    "case_id": case_id,
                    "input_scan": str(source_scan),
                    "prepared_scan": str(prepared_path),
                    "ensemble_probability": str(probability_path),
                    "ensemble_mask": str(mask_path),
                    "probability_sha256": output.probability_sha256,
                    "mask_sha256": output.mask_sha256,
                    "threshold": release.threshold,
                    "n_models": len(models),
                    "ensemble": "unweighted_mean_lesion_probability",
                    "postprocessing": "none",
                    "lesion_voxel_count": voxel_count,
                    "provisional_lesion_volume_mm3": volume_mm3,
                }
            )
            if progress is not None:
                progress(index, total, f"Saved draft lesion mask {index} of {total}")

    manifest_path = output_root / "inference_manifest.csv"
    with manifest_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary_path = output_root / "inference_summary.json"
    summary = {
        "release_id": release.id,
        "architecture": "RatLesNetV2",
        "device": str(device),
        "n_cases": len(outputs),
        "n_models": len(models),
        "model_sha256": list(release.model_sha256),
        "threshold": release.threshold,
        "ensemble": "unweighted_mean_lesion_probability",
        "postprocessing": "none",
        "expected_spacing_mm": list(release.expected_spacing_mm),
        "input_preparation": "singleton_channel_only",
        "spatial_resampling": "none",
        "reorientation": "none",
        "native_affine_preserved": True,
        "predictions_are_drafts": True,
        "human_review_required": True,
        "project_git_commit": release.project_git_commit,
        "ratlesnetv2_git_commit": release.ratlesnetv2_git_commit,
        "manifest": str(manifest_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return T2InferenceOutput(
        release_id=release.id,
        device=str(device),
        threshold=release.threshold,
        cases=tuple(outputs),
        manifest_path=manifest_path,
        summary_path=summary_path,
    )


def create_t2_qc_preview(
    scan_path: Path,
    mask_path: Path,
    output_path: Path,
) -> Path:
    """Create a reflected coronal montage and one QC PNG for every native slice."""
    from lys_bbb.mask_qc import create_native_mask_qc_preview

    return create_native_mask_qc_preview(scan_path, mask_path, output_path)


def _orient_coronal_qc_slice(array: np.ndarray) -> np.ndarray:
    """Rotate to the established coronal view and reflect vertically (about x)."""
    from lys_bbb.mask_qc import orient_coronal_qc_slice

    return orient_coronal_qc_slice(array)


def prepare_t2_inference_scan(
    source_path: Path,
    target_path: Path,
    *,
    expected_spacing: tuple[float, float, float],
) -> None:
    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Validated T2 input is unavailable: {source}")
    image = nib.load(str(source))
    if image.ndim == 3:
        data = np.asanyarray(image.dataobj)[..., np.newaxis]
    elif image.ndim == 4 and image.shape[-1] == 1:
        data = np.asanyarray(image.dataobj)
    else:
        raise ValueError(f"T2 inference expects a 3-D scan; received {image.shape}.")
    finite = data[np.isfinite(data)]
    if finite.size != data.size:
        raise ValueError(f"T2 input contains non-finite voxels: {source}")
    if not finite.size or float(finite.std()) == 0.0:
        raise ValueError(f"T2 input has zero intensity variance: {source}")
    spacing = tuple(float(value) for value in image.header.get_zooms()[:3])
    if not np.allclose(spacing, expected_spacing, rtol=0, atol=1e-5):
        raise ValueError(
            f"T2 spacing {spacing} does not match release spacing {expected_spacing} mm."
        )
    header = image.header.copy()
    header.set_data_shape(data.shape)
    header.set_zooms((*spacing, 1.0))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, image.affine, header), target_path)


def prepare_nnunet_t2_scan(
    source_path: Path,
    target_path: Path,
    *,
    expected_spacing: tuple[float, float, float],
) -> None:
    """Create the `_0000` 3-D input expected by nnU-Net without reorientation."""

    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Validated T2 input is unavailable: {source}")
    image = nib.load(str(source))
    if image.ndim == 3:
        data = np.asanyarray(image.dataobj)
    elif image.ndim == 4 and image.shape[-1] == 1:
        data = np.asanyarray(image.dataobj)[..., 0]
    else:
        raise ValueError(f"T2 inference expects a 3-D scan; received {image.shape}.")
    finite = data[np.isfinite(data)]
    if finite.size != data.size:
        raise ValueError(f"T2 input contains non-finite voxels: {source}")
    if not finite.size or float(finite.std()) == 0.0:
        raise ValueError(f"T2 input has zero intensity variance: {source}")
    spacing = tuple(float(value) for value in image.header.get_zooms()[:3])
    if not np.allclose(spacing, expected_spacing, rtol=0, atol=1e-5):
        raise ValueError(
            f"T2 spacing {spacing} does not match release spacing {expected_spacing} mm."
        )
    header = image.header.copy()
    header.set_data_shape(data.shape)
    header.set_zooms(spacing)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, image.affine, header), target_path)


def threshold_lesion_probability(
    probability: np.ndarray,
    threshold: float,
    *,
    case_id: str = "unknown",
) -> np.ndarray:
    """Validate and threshold lesion probabilities without any postprocessing."""

    array = np.asarray(probability, dtype=np.float32)
    finite = array[np.isfinite(array)]
    if (
        finite.size != array.size
        or not finite.size
        or float(finite.min()) < 0.0
        or float(finite.max()) > 1.0
    ):
        raise ValueError(f"Invalid lesion probabilities for case {case_id!r}.")
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"Invalid lesion-probability threshold: {threshold}.")
    return (array >= threshold).astype(np.uint8)


def _nnunet_probability_to_native_shape(
    probability: np.ndarray,
    native_shape: tuple[int, int, int],
    *,
    case_id: str,
) -> np.ndarray:
    """Convert nnU-Net NibabelIO order `(z, y, x)` to NIfTI `(x, y, z)`."""

    array = np.asarray(probability, dtype=np.float32)
    expected_nnunet_shape = tuple(reversed(native_shape))
    if tuple(array.shape) != expected_nnunet_shape:
        raise ValueError(
            f"nnU-Net lesion probabilities for {case_id!r} have shape "
            f"{array.shape}; expected NibabelIO shape {expected_nnunet_shape} "
            f"for native NIfTI shape {native_shape}."
        )
    return np.transpose(array, (2, 1, 0))


def _load_nnunet_runtime() -> tuple[Any, Any]:
    try:
        installed_version = version("nnunetv2")
        import torch
        from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    except (ImportError, PackageNotFoundError) as exc:
        raise RuntimeError(
            "nnU-Net v2.8.1 and PyTorch are required for LYS v3 T2 inference. "
            "Install the t2-inference dependencies."
        ) from exc
    if installed_version != "2.8.1":
        raise RuntimeError(
            "LYS v3 T2 inference requires nnU-Net v2.8.1; "
            f"found {installed_version}."
        )
    return torch, nnUNetPredictor


def _load_runtime(release: FrozenT2ModelRelease) -> tuple[Any, Any]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for T2 model inference. Install the t2-inference extra."
        ) from exc
    source = str(release.architecture_path)
    previous_lib_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "lib" or name.startswith("lib.")
    }
    for name in previous_lib_modules:
        del sys.modules[name]
    sys.path.insert(0, source)
    try:
        module = importlib.import_module("lib.RatLesNetv2")
    finally:
        sys.path.remove(source)
        for name in tuple(sys.modules):
            if name == "lib" or name.startswith("lib."):
                del sys.modules[name]
        sys.modules.update(previous_lib_modules)
    return torch, module.RatLesNetv2


def _select_device(torch: Any, requested: str) -> Any:
    if requested == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            requested = "mps"
        elif torch.cuda.is_available():
            requested = "cuda"
        else:
            requested = "cpu"
    if requested == "mps" and not (
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    ):
        raise RuntimeError("Apple MPS was requested but is unavailable.")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable.")
    if requested not in {"mps", "cuda", "cpu"}:
        raise ValueError(f"Unsupported inference device: {requested}")
    return torch.device(requested)


def _load_normalized_tensor(reference: Any, torch: Any, device: Any) -> Any:
    data = np.asanyarray(reference.dataobj, dtype=np.float32)
    normalized = (data - data.mean()) / data.std()
    normalized = np.moveaxis(normalized, -1, 0)
    normalized = np.moveaxis(normalized, -1, 1)
    normalized = np.expand_dims(normalized, axis=0)
    return torch.from_numpy(normalized.astype(np.float32, copy=False)).to(device)


def _lesion_probability_map(prediction: Any) -> np.ndarray:
    array = prediction.detach().cpu().numpy()
    if array.ndim != 5 or array.shape[1] != 2:
        raise ValueError(f"Unexpected RatLesNetV2 output shape: {array.shape}")
    return np.squeeze(array[:, 1, ...])


def _prediction_to_native_shape(
    array: np.ndarray,
    target_shape: tuple[int, int, int],
) -> np.ndarray:
    expected_model_shape = (target_shape[2], target_shape[0], target_shape[1])
    if tuple(array.shape) != expected_model_shape:
        raise ValueError(
            "Unexpected RatLesNetV2 lesion-map shape: "
            f"{array.shape}; expected {expected_model_shape}."
        )
    return np.transpose(array, (1, 2, 0))


def _save_nifti_like(path: Path, data: np.ndarray, reference: Any) -> None:
    header = reference.header.copy()
    header.set_data_shape(data.shape)
    header.set_data_dtype(data.dtype)
    header.set_zooms(tuple(float(value) for value in reference.header.get_zooms()[:3]))
    nib.save(nib.Nifti1Image(data, reference.affine, header), path)


def _validate_native_output(source: Path, probability: Path, mask: Path) -> None:
    source_image = nib.load(str(source))
    probability_image = nib.load(str(probability))
    mask_image = nib.load(str(mask))
    for image, label in ((probability_image, "probability"), (mask_image, "mask")):
        if tuple(image.shape) != tuple(source_image.shape[:3]):
            raise ValueError(f"T2 {label} shape does not match its native input.")
        if not np.allclose(image.affine, source_image.affine, rtol=0, atol=1e-7):
            raise ValueError(f"T2 {label} affine does not match its native input.")
    mask_data = np.asanyarray(mask_image.dataobj)
    if not np.isin(np.unique(mask_data), (0, 1)).all():
        raise ValueError("T2 draft mask is not binary.")


def _validate_case_id(case_id: str) -> None:
    if not case_id or case_id in {".", ".."} or Path(case_id).name != case_id:
        raise ValueError(f"Invalid inference case ID: {case_id!r}")
