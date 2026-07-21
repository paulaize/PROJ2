"""Qt-free local RS2-Net and M-seam T1 brain-mask draft generation."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to

from lys_bbb.brain_mask_refinement import (
    GapRefinementConfig,
    MSeamCleanupConfig,
    MaskRegularityConfig,
    assess_mask_regularity,
    detect_gap_volume,
    refine_direct_seam,
    robust_normalize,
    stabilize_m_seam_mask,
)
from lys_bbb.t1_brain_mask_release import (
    FrozenT1BrainMaskRelease,
    sha256_file,
)


RawRs2Runner = Callable[
    [FrozenT1BrainMaskRelease, str, Path, Path, str, bool, Path, Path], Path
]


@dataclass(frozen=True)
class T1BrainMaskOutput:
    """Paths and primary QC facts for one automatic, unapproved mask draft."""

    case_id: str
    source_t1: Path
    raw_rs2_mask: Path
    draft_mask: Path
    removed_mask: Path | None
    cleanup_changed_mask: Path | None
    qc_preview: Path
    metadata_path: Path
    raw_mask_sha256: str
    draft_mask_sha256: str
    foreground_voxels: int
    volume_mm3: float
    regularity_warnings: tuple[str, ...]


@dataclass(frozen=True)
class OrientationRecord:
    """Reversible conversion between native array axes and anatomical R/S/A axes."""

    native_axis_codes: tuple[str, str, str]
    order: tuple[int, int, int]
    flips: tuple[bool, bool, bool]


def run_local_t1_brain_mask(
    release: FrozenT1BrainMaskRelease,
    input_path: Path,
    output_root: Path,
    *,
    case_id: str | None = None,
    device_name: str = "auto",
    disable_tta: bool = False,
    gap_config: GapRefinementConfig | None = None,
    cleanup_config: MSeamCleanupConfig | None = None,
    regularity_config: MaskRegularityConfig | None = None,
    rs2_runner: RawRs2Runner | None = None,
) -> T1BrainMaskOutput:
    """Run the frozen RS2 model locally and create an M-seam draft mask.

    The destination must be new.  Raw RS2 output, the refined draft, diagnostics,
    checksums, and QC remain separate, and the result is always marked as requiring
    human review.
    """

    input_path = _validate_t1_input(input_path)
    output_root = output_root.expanduser().resolve()
    if output_root.exists():
        raise FileExistsError(f"T1 brain-mask output already exists: {output_root}")
    case_id = _case_id(case_id or _strip_nifti_suffix(input_path.name))
    use_tta = release.test_time_augmentation and not disable_tta
    device = _select_device(device_name, exact_tta=use_tta)
    _check_rs2_runtime_dependencies()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    runner = rs2_runner or _run_rs2_predict

    with tempfile.TemporaryDirectory(
        dir=output_root.parent, prefix=f".{output_root.name}-work-"
    ) as temporary:
        work_root = Path(temporary)
        input_directory = work_root / "rs2_input"
        input_directory.mkdir()
        staged_input = input_directory / f"{case_id}_0000.nii.gz"
        shutil.copy2(input_path, staged_input)
        rs2_output = work_root / "rs2_output"
        log_path = work_root / "rs2.log"
        raw_prediction = runner(
            release,
            case_id,
            input_directory,
            rs2_output,
            device,
            use_tta,
            log_path,
            work_root,
        )
        result_root = work_root / "result"
        generation = {
            "generator": "RS2-Net",
            "release_id": release.id,
            "source_commit": release.source_commit,
            "weights_sha256": release.weights_sha256,
            "test_time_augmentation": use_tta,
            "generation_variant": (
                "reviewed_eight_way_tta" if use_tta else "explicit_no_tta_local_draft"
            ),
            "device": device,
            "upstream_compatibility_patches": [
                "trusted legacy checkpoint loaded with weights_only=False",
                "compiled-checkpoint _orig_mod prefix normalized",
                "torch.compile disabled for portable local inference",
                "MPS mirrored predictions accumulated on CPU with cache clearing",
            ],
        }
        build_t1_brain_mask_draft(
            input_path,
            raw_prediction,
            result_root,
            case_id=case_id,
            gap_config=gap_config,
            cleanup_config=cleanup_config,
            regularity_config=regularity_config,
            generation_provenance=generation,
        )
        if log_path.is_file():
            destination_log = result_root / "logs/rs2.log"
            destination_log.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(log_path, destination_log)
            metadata_path = result_root / "metadata.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["rs2_log"] = str(destination_log.relative_to(result_root))
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n"
            )
        result_root.replace(output_root)
    return load_t1_brain_mask_output(output_root)


def build_t1_brain_mask_draft(
    input_path: Path,
    raw_mask_path: Path,
    output_root: Path,
    *,
    case_id: str | None = None,
    gap_config: GapRefinementConfig | None = None,
    cleanup_config: MSeamCleanupConfig | None = None,
    regularity_config: MaskRegularityConfig | None = None,
    generation_provenance: dict[str, Any] | None = None,
) -> T1BrainMaskOutput:
    """Create a reviewed-method M-seam draft atomically from an existing raw mask."""

    output_root = output_root.expanduser().resolve()
    if output_root.exists():
        raise FileExistsError(f"T1 brain-mask output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output_root.parent, prefix=f".{output_root.name}-build-"
    ) as temporary:
        result_root = Path(temporary) / "result"
        _build_t1_brain_mask_draft(
            input_path,
            raw_mask_path,
            result_root,
            case_id=case_id,
            gap_config=gap_config,
            cleanup_config=cleanup_config,
            regularity_config=regularity_config,
            generation_provenance=generation_provenance,
        )
        result_root.replace(output_root)
    return load_t1_brain_mask_output(output_root)


def _build_t1_brain_mask_draft(
    input_path: Path,
    raw_mask_path: Path,
    output_root: Path,
    *,
    case_id: str | None = None,
    gap_config: GapRefinementConfig | None = None,
    cleanup_config: MSeamCleanupConfig | None = None,
    regularity_config: MaskRegularityConfig | None = None,
    generation_provenance: dict[str, Any] | None = None,
) -> T1BrainMaskOutput:
    """Build one result inside a caller-owned new temporary directory."""

    input_path = _validate_t1_input(input_path)
    raw_mask_path = raw_mask_path.expanduser().resolve()
    if not raw_mask_path.is_file():
        raise FileNotFoundError(f"Raw RS2 mask is unavailable: {raw_mask_path}")
    output_root = output_root.expanduser().resolve()
    if output_root.exists():
        raise FileExistsError(f"T1 brain-mask output already exists: {output_root}")
    case_id = _case_id(case_id or _strip_nifti_suffix(input_path.name))
    gap_config = gap_config or GapRefinementConfig()
    cleanup_config = cleanup_config or MSeamCleanupConfig()
    regularity_config = regularity_config or MaskRegularityConfig()

    image_object = nib.load(str(input_path))
    image_native = np.asanyarray(image_object.dataobj, dtype=np.float32)
    raw_native, raw_resampled = _standardize_raw_mask(raw_mask_path, image_object)
    image_rsa, orientation = native_to_rsa(image_native, image_object.affine)
    raw_rsa, mask_orientation = native_to_rsa(raw_native, image_object.affine)
    if orientation != mask_orientation:
        raise RuntimeError("T1 and raw RS2 mask orientation records differ.")
    native_spacing = tuple(float(value) for value in image_object.header.get_zooms()[:3])
    spacing_rsa = tuple(native_spacing[axis] for axis in orientation.order)
    normalized = robust_normalize(image_rsa, raw_rsa)
    gaps = detect_gap_volume(normalized, raw_rsa, spacing_rsa, gap_config)
    m_seam_rsa, m_seam_stats = refine_direct_seam(raw_rsa, gaps, gap_config)
    draft_rsa, cleanup_report = stabilize_m_seam_mask(
        m_seam_rsa,
        raw_rsa,
        spacing_rsa,
        cleanup_config,
    )
    raw_regularity = assess_mask_regularity(raw_rsa, spacing_rsa, regularity_config)
    m_seam_regularity = assess_mask_regularity(
        m_seam_rsa, spacing_rsa, regularity_config
    )
    draft_regularity = assess_mask_regularity(
        draft_rsa, spacing_rsa, regularity_config
    )
    draft_native = rsa_to_native(draft_rsa, orientation).astype(np.uint8)
    m_seam_native = rsa_to_native(m_seam_rsa, orientation).astype(bool)

    output_root.mkdir(parents=True)
    raw_output = output_root / "raw_rs2_brain_mask.nii.gz"
    draft_output = output_root / "draft_m_seam_brain_mask.nii.gz"
    _save_mask_like(raw_native, image_object, raw_output)
    _save_mask_like(draft_native, image_object, draft_output)
    removed_native = raw_native & ~draft_native.astype(bool)
    removed_output = _save_optional_mask(
        removed_native,
        image_object,
        output_root / "diagnostics/removed_from_raw_rs2.nii.gz",
    )
    cleanup_changed_native = m_seam_native ^ draft_native.astype(bool)
    cleanup_changed_output = _save_optional_mask(
        cleanup_changed_native,
        image_object,
        output_root / "diagnostics/m_seam_cleanup_changed.nii.gz",
    )
    qc_output = output_root / "qc/draft_mask_qc.png"
    create_t1_brain_mask_qc(
        image_rsa,
        raw_rsa,
        draft_rsa,
        spacing_rsa,
        qc_output,
        preferred_slices=tuple(
            sorted(
                set(m_seam_stats["corrected_slices"])
                | set(cleanup_report.in_plane_cleaned_slices)
                | {
                    index
                    for start, stop in cleanup_report.repaired_slice_runs
                    for index in range(start, stop + 1)
                }
            )
        ),
    )
    foreground_voxels = int(np.count_nonzero(draft_native))
    volume_mm3 = float(foreground_voxels * np.prod(native_spacing))
    metadata_path = output_root / "metadata.json"
    metadata = {
        "schema_version": 1,
        "case_id": case_id,
        "role": "automatic T1 brain-mask draft; human review required",
        "method": "RS2-Net plus T1-guided M-seam and conservative 3-D continuity cleanup",
        "source_t1": str(input_path),
        "source_t1_sha256": sha256_file(input_path),
        "source_raw_mask": (
            None if generation_provenance and generation_provenance.get("release_id") else str(raw_mask_path)
        ),
        "source_raw_mask_sha256": sha256_file(raw_mask_path),
        "raw_mask_resampled_to_input_grid": raw_resampled,
        "raw_rs2_mask": str(raw_output.relative_to(output_root)),
        "raw_rs2_mask_sha256": sha256_file(raw_output),
        "draft_mask": str(draft_output.relative_to(output_root)),
        "draft_mask_sha256": sha256_file(draft_output),
        "removed_mask": (
            str(removed_output.relative_to(output_root)) if removed_output else None
        ),
        "cleanup_changed_mask": (
            str(cleanup_changed_output.relative_to(output_root))
            if cleanup_changed_output
            else None
        ),
        "qc_preview": str(qc_output.relative_to(output_root)),
        "native_shape": list(image_object.shape),
        "native_spacing_mm": list(native_spacing),
        "native_axis_codes": list(orientation.native_axis_codes),
        "orientation_record": {
            "rsa_axis_order": list(orientation.order),
            "flips": list(orientation.flips),
        },
        "foreground_voxels": foreground_voxels,
        "volume_mm3": volume_mm3,
        "m_seam": m_seam_stats,
        "m_seam_cleanup": cleanup_report.to_dict(),
        "regularity_qc": {
            "raw_rs2": raw_regularity.to_dict(),
            "m_seam_before_cleanup": m_seam_regularity.to_dict(),
            "draft_after_cleanup": draft_regularity.to_dict(),
        },
        "gap_configuration": asdict(gap_config),
        "cleanup_configuration": asdict(cleanup_config),
        "regularity_configuration": asdict(regularity_config),
        "generation": generation_provenance or {"generator": "existing raw RS2 mask"},
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime": _runtime_metadata(),
        "project_git_revision": _project_git_revision(),
        "human_review_required": True,
        "approved": False,
        "scientific_warning": (
            "Automatic draft only. Inspect the complete 3-D mask and correct it in "
            "ITK-SNAP before approval or quantification."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return load_t1_brain_mask_output(output_root)


def load_t1_brain_mask_output(output_root: Path) -> T1BrainMaskOutput:
    """Load the stable path contract for a completed local T1 mask run."""

    root = output_root.expanduser().resolve()
    metadata_path = root / "metadata.json"
    payload = json.loads(metadata_path.read_text())

    def optional_path(value: str | None) -> Path | None:
        return root / value if value else None

    regularity = payload["regularity_qc"]["draft_after_cleanup"]
    return T1BrainMaskOutput(
        case_id=payload["case_id"],
        source_t1=Path(payload["source_t1"]),
        raw_rs2_mask=root / payload["raw_rs2_mask"],
        draft_mask=root / payload["draft_mask"],
        removed_mask=optional_path(payload.get("removed_mask")),
        cleanup_changed_mask=optional_path(payload.get("cleanup_changed_mask")),
        qc_preview=root / payload["qc_preview"],
        metadata_path=metadata_path,
        raw_mask_sha256=payload["raw_rs2_mask_sha256"],
        draft_mask_sha256=payload["draft_mask_sha256"],
        foreground_voxels=int(payload["foreground_voxels"]),
        volume_mm3=float(payload["volume_mm3"]),
        regularity_warnings=tuple(regularity["warnings"]),
    )


def native_to_rsa(
    array: np.ndarray, affine: np.ndarray
) -> tuple[np.ndarray, OrientationRecord]:
    """Return an array in R/S/A order and a reversible orientation record."""

    codes = tuple(str(code) for code in nib.aff2axcodes(affine))
    requested = (("R", "L"), ("S", "I"), ("A", "P"))
    order: list[int] = []
    flips: list[bool] = []
    for positive, negative in requested:
        matches = [
            index for index, code in enumerate(codes) if code in (positive, negative)
        ]
        if len(matches) != 1:
            raise ValueError(f"Cannot identify the {positive}/{negative} axis from {codes}.")
        axis = matches[0]
        order.append(axis)
        flips.append(codes[axis] == negative)
    oriented = np.transpose(np.asarray(array), order)
    for axis, should_flip in enumerate(flips):
        if should_flip:
            oriented = np.flip(oriented, axis=axis)
    record = OrientationRecord(
        native_axis_codes=codes,
        order=tuple(order),
        flips=tuple(flips),
    )
    return oriented, record


def rsa_to_native(array_rsa: np.ndarray, orientation: OrientationRecord) -> np.ndarray:
    """Reverse :func:`native_to_rsa` without interpolation."""

    native_ordered = np.asarray(array_rsa)
    for axis, should_flip in enumerate(orientation.flips):
        if should_flip:
            native_ordered = np.flip(native_ordered, axis=axis)
    return np.transpose(native_ordered, np.argsort(orientation.order))


def create_t1_brain_mask_qc(
    image_rsa: np.ndarray,
    raw_mask_rsa: np.ndarray,
    draft_mask_rsa: np.ndarray,
    spacing_rsa: tuple[float, float, float],
    output_path: Path,
    *,
    preferred_slices: tuple[int, ...] = (),
) -> Path:
    """Write a compact multi-slice review aid; it is never an approval decision."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    image = np.asarray(image_rsa, dtype=np.float32)
    raw = np.asarray(raw_mask_rsa, dtype=bool)
    draft = np.asarray(draft_mask_rsa, dtype=bool)
    if image.shape != raw.shape or raw.shape != draft.shape or image.ndim != 3:
        raise ValueError("T1 brain-mask QC requires matching three-dimensional arrays.")
    selected = _select_qc_slices(draft, preferred_slices, maximum=9)
    finite = image[np.isfinite(image)]
    low, high = np.percentile(finite, (1, 99.5)) if finite.size else (0.0, 1.0)
    if high <= low:
        high = low + 1.0
    columns = 3
    rows = int(np.ceil(len(selected) / columns))
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(3.1 * columns, 3.1 * rows),
        facecolor="#101b2b",
        squeeze=False,
    )
    changed = raw ^ draft
    for axis, slice_index in zip(axes.ravel(), selected, strict=False):
        axis.imshow(
            image[:, :, slice_index].T,
            origin="lower",
            cmap="gray",
            vmin=low,
            vmax=high,
        )
        if np.any(changed[:, :, slice_index]):
            overlay = np.zeros((*changed.shape[:2][::-1], 4), dtype=np.float32)
            overlay[changed[:, :, slice_index].T] = (1.0, 0.20, 0.72, 0.42)
            axis.imshow(overlay, origin="lower")
        if np.any(raw[:, :, slice_index]):
            axis.contour(
                raw[:, :, slice_index].T,
                levels=[0.5],
                colors=["#ffd54f"],
                linewidths=0.8,
            )
        if np.any(draft[:, :, slice_index]):
            axis.contour(
                draft[:, :, slice_index].T,
                levels=[0.5],
                colors=["#21d4c2"],
                linewidths=1.0,
            )
        axis.set_title(
            f"A slice {slice_index} · {slice_index * spacing_rsa[2]:.2f} mm",
            color="white",
            fontsize=9,
        )
        axis.axis("off")
    for axis in axes.ravel()[len(selected) :]:
        axis.axis("off")
    figure.suptitle(
        "Draft T1 brain mask · yellow raw RS2 · teal final · pink changed",
        color="white",
        fontsize=12,
    )
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.96), pad=0.7)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output_path,
        dpi=130,
        facecolor=figure.get_facecolor(),
    )
    plt.close(figure)
    return output_path


def _select_qc_slices(
    mask: np.ndarray, preferred_slices: tuple[int, ...], *, maximum: int
) -> list[int]:
    occupied = np.flatnonzero(np.any(mask, axis=(0, 1)))
    if occupied.size == 0:
        return [mask.shape[2] // 2]
    valid_preferred = sorted(
        {index for index in preferred_slices if 0 <= index < mask.shape[2]}
    )
    if len(valid_preferred) > maximum:
        positions = np.linspace(0, len(valid_preferred) - 1, maximum).round().astype(int)
        return [valid_preferred[index] for index in positions]
    selected = set(valid_preferred)
    needed = maximum - len(selected)
    if needed:
        positions = np.linspace(0, occupied.size - 1, needed + 2)[1:-1].round().astype(int)
        selected.update(int(occupied[position]) for position in positions)
    return sorted(selected)[:maximum]


def _run_rs2_predict(
    release: FrozenT1BrainMaskRelease,
    case_id: str,
    input_directory: Path,
    output_directory: Path,
    device: str,
    use_tta: bool,
    log_path: Path,
    work_root: Path,
) -> Path:
    runtime_source = work_root / "rs2_runtime"
    shutil.copytree(
        release.source_path,
        runtime_source,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )
    _patch_rs2_runtime(runtime_source / "RS2/inference/predict.py")
    _patch_rs2_mps_tta(
        runtime_source / "RS2/inference/sliding_window_prediction.py"
    )
    command = [
        sys.executable,
        "-c",
        "from RS2.inference.predict import predict_entry_point; predict_entry_point()",
        "-i",
        str(input_directory),
        "-o",
        str(output_directory),
        "-m",
        str(release.weights_path),
        "-device",
        device,
        "-npp",
        "1",
        "-nps",
        "1",
    ]
    if not use_tta:
        command.append("--disable_tta")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(runtime_source), environment.get("PYTHONPATH", "")]
    )
    if device == "mps":
        environment.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=runtime_source,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            f"RS2-Net inference failed with exit code {return_code}. Log: {log_path}"
        )
    log_text = log_path.read_text(errors="replace")
    fatal_runtime_markers = (
        "command buffer exited with error status",
        "kIOGPUCommandBufferCallbackErrorOutOfMemory",
        "MPS backend out of memory",
    )
    if any(marker in log_text for marker in fatal_runtime_markers):
        raise RuntimeError(
            "RS2-Net reported an Apple MPS memory failure even though its process "
            f"returned success. The output was rejected. Log: {log_path}"
        )
    candidates = [
        output_directory / f"{case_id}_0000.nii.gz",
        output_directory / f"{case_id}.nii.gz",
    ]
    outputs = [path for path in candidates if path.is_file()]
    if len(outputs) != 1:
        raise RuntimeError(
            f"RS2-Net created {len(outputs)} expected masks for {case_id!r}; expected one."
        )
    return outputs[0]


def _patch_rs2_runtime(predict_path: Path) -> None:
    """Apply the two reviewed modern-PyTorch/macOS compatibility changes."""

    source = predict_path.read_text()
    old_load = "torch.load(checkpoint_name, map_location=torch.device('cpu'))"
    new_load = (
        "torch.load(checkpoint_name, map_location=torch.device('cpu'), "
        "weights_only=False)"
    )
    if new_load not in source:
        if source.count(old_load) != 1:
            raise RuntimeError("Cannot apply the trusted RS2 checkpoint compatibility patch.")
        source = source.replace(old_load, new_load)
    old_parameters = "    parameters = checkpoint['state_dict']\n"
    new_parameters = (
        "    parameters = checkpoint['state_dict']\n"
        "    if parameters and all(key.startswith('_orig_mod.') for key in parameters):\n"
        "        parameters = {key.removeprefix('_orig_mod.'): value "
        "for key, value in parameters.items()}\n"
    )
    if new_parameters not in source:
        if source.count(old_parameters) != 1:
            raise RuntimeError("Cannot apply the compiled-checkpoint key compatibility patch.")
        source = source.replace(old_parameters, new_parameters)
    old_compile = "\n    network = torch.compile(network)\n"
    new_compile = "\n    # torch.compile disabled by the portable LYS local adapter.\n"
    if new_compile not in source:
        if source.count(old_compile) != 1:
            raise RuntimeError("Cannot apply the portable RS2 compilation patch.")
        source = source.replace(old_compile, new_compile)
    predict_path.write_text(source)


def _patch_rs2_mps_tta(source_path: Path) -> None:
    """Accumulate mirrored predictions on CPU so eight-way TTA fits Apple MPS."""

    source = source_path.read_text()
    start_marker = "def maybe_mirror_and_predict("
    stop_marker = "\ndef predict_sliding_window_return_logits("
    start = source.find(start_marker)
    stop = source.find(stop_marker, start)
    if start < 0 or stop < 0:
        raise RuntimeError("Cannot locate the RS2 mirrored-prediction helper.")
    replacement = '''def maybe_mirror_and_predict(network: nn.Module, x: torch.Tensor, mirror_axes: Tuple[int, ...] = None) \\
        -> torch.Tensor:
    """Run the upstream mirror ensemble with bounded Apple-MPS memory."""
    print(x.shape)
    accumulation_device = torch.device('cpu') if x.device.type == 'mps' else x.device

    def forward(mirror_dimensions=None):
        model_input = torch.flip(x, mirror_dimensions) if mirror_dimensions else x
        result = network(model_input).to(accumulation_device)
        if mirror_dimensions:
            result = torch.flip(result, mirror_dimensions)
        if x.device.type == 'mps':
            torch.mps.synchronize()
            del model_input
            empty_cache(x.device)
        return result

    prediction = forward()
    if mirror_axes is not None:
        assert max(mirror_axes) <= len(x.shape) - 3, 'mirror_axes does not match the input dimensions'
        num_predictions = 2 ** len(mirror_axes)
        if 0 in mirror_axes:
            prediction += forward((2,))
        if 1 in mirror_axes:
            prediction += forward((3,))
        if 2 in mirror_axes:
            prediction += forward((4,))
        if 0 in mirror_axes and 1 in mirror_axes:
            prediction += forward((2, 3))
        if 0 in mirror_axes and 2 in mirror_axes:
            prediction += forward((2, 4))
        if 1 in mirror_axes and 2 in mirror_axes:
            prediction += forward((3, 4))
        if 0 in mirror_axes and 1 in mirror_axes and 2 in mirror_axes:
            prediction += forward((2, 3, 4))
        prediction /= num_predictions
    return prediction
'''
    source = source[:start] + replacement + source[stop:]
    source_path.write_text(source)


def _check_rs2_runtime_dependencies() -> None:
    required = ("torch", "monai", "batchgenerators", "acvl_utils", "einops")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "Local RS2 inference dependencies are missing: "
            f"{', '.join(missing)}. Install the project's t1-inference extra."
        )


def _select_device(requested: str, *, exact_tta: bool = False) -> str:
    if requested not in {"auto", "mps", "cuda", "cpu"}:
        raise ValueError(f"Unsupported T1 inference device: {requested!r}.")
    import torch

    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if (
            not exact_tta
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            return "mps"
        return "cpu"
    if requested == "mps" and not (
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    ):
        raise RuntimeError("Apple MPS was requested but is unavailable in this environment.")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable in this environment.")
    return requested


def _validate_t1_input(path: Path) -> Path:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Pre-Gd T1 image is unavailable: {source}")
    image = nib.load(str(source))
    if image.ndim != 3:
        raise ValueError(f"T1 brain extraction expects a 3-D image; received {image.shape}.")
    data = np.asanyarray(image.dataobj)
    if not np.isfinite(data).all():
        raise ValueError("T1 brain extraction input contains non-finite values.")
    if data.size == 0 or float(np.std(data)) == 0.0:
        raise ValueError("T1 brain extraction input has no intensity variation.")
    if any(code is None for code in nib.aff2axcodes(image.affine)):
        raise ValueError("T1 brain extraction input orientation is undefined.")
    return source


def _standardize_raw_mask(
    mask_path: Path, reference: nib.Nifti1Image
) -> tuple[np.ndarray, bool]:
    mask_image = nib.load(str(mask_path))
    if mask_image.ndim == 4 and mask_image.shape[-1] == 1:
        mask_image = nib.Nifti1Image(
            np.asanyarray(mask_image.dataobj)[..., 0],
            mask_image.affine,
            mask_image.header,
        )
    if mask_image.ndim != 3:
        raise ValueError(f"Raw RS2 mask must be 3-D; received {mask_image.shape}.")
    resampled = False
    if mask_image.shape != reference.shape or not np.allclose(
        mask_image.affine, reference.affine, rtol=1e-5, atol=1e-5
    ):
        mask_image = resample_from_to(mask_image, reference, order=0)
        resampled = True
    values = np.asanyarray(mask_image.dataobj)
    if not np.isfinite(values).all():
        raise ValueError("Raw RS2 mask contains non-finite values.")
    mask = values > 0
    if not mask.any() or mask.all():
        raise ValueError("Raw RS2 mask must be non-empty and contain background.")
    return mask, resampled


def _save_mask_like(
    mask: np.ndarray,
    reference: nib.Nifti1Image,
    destination: Path,
) -> None:
    data = np.asarray(mask, dtype=np.uint8)
    if data.shape != reference.shape or not data.any() or data.all():
        raise ValueError(
            f"Invalid mask for {destination}: shape={data.shape}, foreground={int(data.sum())}."
        )
    header = reference.header.copy()
    header.set_data_dtype(np.uint8)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = nib.Nifti1Image(data, reference.affine, header)
    output.set_qform(reference.affine, code=int(reference.header["qform_code"]))
    output.set_sform(reference.affine, code=int(reference.header["sform_code"]))
    nib.save(output, destination)


def _save_optional_mask(
    mask: np.ndarray,
    reference: nib.Nifti1Image,
    destination: Path,
) -> Path | None:
    if not np.any(mask):
        return None
    _save_mask_like(mask, reference, destination)
    return destination


def _runtime_metadata() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("numpy", "nibabel", "scipy", "torch", "monai"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
    }


def _project_git_revision() -> str | None:
    root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _case_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not normalized:
        raise ValueError("A non-empty T1 case ID is required.")
    return normalized


def _strip_nifti_suffix(name: str) -> str:
    return name[:-7] if name.lower().endswith(".nii.gz") else Path(name).stem
