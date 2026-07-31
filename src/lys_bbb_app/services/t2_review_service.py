"""Application service for T2 correction, review, and official measurement."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.t2_review import (
    save_thresholded_t2_probability,
    validate_and_measure_t2_mask,
    validate_t2_probability_map,
)
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import ScanImportState
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    T2CorrectedArtifactDraft,
    T2LesionArtifactRecord,
)
from lys_bbb_app.infrastructure.external_viewer import (
    ExternalViewerError,
    ViewerLaunch,
)
from lys_bbb_app.infrastructure.study_database import StudyRepository


ViewerLauncher = Callable[..., ViewerLaunch]
T2QCBuilder = Callable[[Path, Path, Path], Path]


@dataclass(frozen=True)
class T2ManualEditSession:
    """One managed ITK-SNAP edit copy tied to its immutable source artifact."""

    subject_id: str
    source_artifact_id: str
    editable_mask_path: Path
    launch: ViewerLaunch


class T2ReviewService:
    """Coordinate files and persistence without placing scientific work in Qt."""

    def __init__(
        self,
        repository: StudyRepository,
        *,
        viewer_launcher: ViewerLauncher,
        qc_builder: T2QCBuilder,
    ) -> None:
        self._repository = repository
        self._viewer_launcher = viewer_launcher
        self._qc_builder = qc_builder

    def start_manual_edit(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> T2ManualEditSession:
        """Create a managed edit copy and launch it with the native T2."""

        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        try:
            validate_and_measure_t2_mask(
                artifact.mask_path,
                reference_path,
                expected_mask_sha256=artifact.mask_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The T2 lesion mask cannot be opened for correction: {exc}"
            ) from exc
        correction_id = str(uuid4())
        work_directory = (
            self._repository.root_path
            / "work"
            / "t2_lesion"
            / "corrections"
            / correction_id
        )
        editable_path = work_directory / "lesion_mask_editable.nii.gz"
        try:
            work_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(artifact.mask_path, editable_path)
            (work_directory / "correction_manifest.json").write_text(
                json.dumps(
                    {
                        "source_artifact_id": artifact.id,
                        "source_mask_sha256": artifact.mask_sha256,
                        "subject_id": subject_id,
                        "native_t2_path": str(reference_path),
                        "editable_mask_path": str(editable_path),
                        "instructions": (
                            "Save corrections over the editable mask, close ITK-SNAP, "
                            "then choose Use saved mask in LYS IRM. The registered source "
                            "artifact is immutable."
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            launch = self._viewer_launcher(
                reference_path,
                viewer_path,
                segmentation_path=editable_path,
            )
        except ExternalViewerError as exc:
            shutil.rmtree(work_directory, ignore_errors=True)
            raise StudyStateError(str(exc)) from exc
        except OSError as exc:
            shutil.rmtree(work_directory, ignore_errors=True)
            raise StudyStateError(
                f"Could not prepare the editable T2 lesion mask: {exc}"
            ) from exc
        self._repository.record_audit_event(
            "T2_CORRECTION_COPY_OPENED_IN_ITKSNAP",
            actor=actor,
            subject_id=subject_id,
            details={
                "artifact_id": artifact.id,
                "registered_mask_path": str(artifact.mask_path),
                "editable_mask_path": str(editable_path),
                "source_mask_modified": False,
            },
        )
        return T2ManualEditSession(
            subject_id=subject_id,
            source_artifact_id=artifact.id,
            editable_mask_path=editable_path,
            launch=launch,
        )

    def prepare_review_qc_slices(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> tuple[Path, ...]:
        """Render missing per-slice QC images for an existing review artifact."""

        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        if artifact.qc_preview_path is None:
            raise StudyStateError("This T2 lesion artifact has no QC output location.")
        try:
            self._qc_builder(
                reference_path,
                artifact.mask_path,
                artifact.qc_preview_path,
            )
        except (OSError, ValueError) as exc:
            raise StudyStateError(f"Could not prepare T2 review slices: {exc}") from exc
        return tuple(
            sorted((artifact.qc_preview_path.parent / "qc_slices").glob("slice_*.png"))
        )

    def apply_probability_threshold(
        self,
        subject_id: str,
        artifact_id: str,
        threshold: float,
        *,
        actor: str,
    ) -> str:
        """Create a new review-required mask from one case's saved probabilities."""

        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        if artifact.origin == "CORRECTED":
            raise StudyStateError(
                "A manually corrected mask cannot be regenerated from probabilities."
            )
        try:
            probability = validate_t2_probability_map(
                artifact.probability_path,
                reference_path,
                expected_probability_sha256=artifact.probability_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The case-specific T2 threshold cannot be applied: {exc}"
            ) from exc

        threshold_work = (
            self._repository.root_path
            / "work"
            / "t2_lesion"
            / "threshold_adjustments"
            / str(uuid4())
        )
        thresholded_mask = threshold_work / "lesion_mask_thresholded.nii.gz"
        try:
            save_thresholded_t2_probability(
                probability,
                reference_path,
                thresholded_mask,
                threshold=threshold,
            )
            return self._register_corrected_mask(
                subject_id,
                artifact_id,
                thresholded_mask,
                actor=actor,
                origin="THRESHOLD_ADJUSTED",
                metadata={
                    "threshold": float(threshold),
                    "case_specific_threshold_override": True,
                    "model_default_threshold": float(
                        artifact.metadata.get(
                            "model_default_threshold",
                            artifact.metadata.get("inference_threshold", artifact.threshold),
                        )
                    ),
                    "inference_threshold": float(
                        artifact.metadata.get("inference_threshold", artifact.threshold)
                    ),
                    "threshold_source_artifact_id": artifact.id,
                    "threshold_source_probability_sha256": probability.probability_sha256,
                    "maximum_probability": probability.maximum_probability,
                    "postprocessing": "none",
                },
            )
        except StudyStateError:
            raise
        except (OSError, ValueError) as exc:
            raise StudyStateError(
                f"The case-specific T2 threshold could not be applied: {exc}"
            ) from exc
        finally:
            shutil.rmtree(threshold_work, ignore_errors=True)

    def finish_manual_edit(
        self,
        session: T2ManualEditSession,
        *,
        actor: str,
    ) -> str:
        """Store the saved managed edit as the new active immutable mask version."""

        corrections_root = (
            self._repository.root_path / "work" / "t2_lesion" / "corrections"
        ).resolve()
        editable_path = session.editable_mask_path.expanduser().resolve()
        if not editable_path.is_relative_to(corrections_root):
            raise StudyStateError("The selected T2 edit session is not managed by this study.")
        manifest_path = editable_path.parent / "correction_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StudyStateError("The managed T2 edit session is incomplete.") from exc
        if (
            manifest.get("subject_id") != session.subject_id
            or manifest.get("source_artifact_id") != session.source_artifact_id
            or Path(str(manifest.get("editable_mask_path", ""))).resolve()
            != editable_path
        ):
            raise StudyStateError("The managed T2 edit session does not match this mask.")
        return self._register_corrected_mask(
            session.subject_id,
            session.source_artifact_id,
            editable_path,
            actor=actor,
        )

    def _register_corrected_mask(
        self,
        subject_id: str,
        source_artifact_id: str,
        corrected_path: Path | str,
        *,
        actor: str,
        origin: str = "CORRECTED",
        metadata: dict[str, object] | None = None,
    ) -> str:
        """Validate and copy one managed edit into immutable study-owned storage."""

        source_artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            source_artifact_id,
        )
        imported_from = Path(corrected_path).expanduser().resolve()
        try:
            source_measurement = validate_and_measure_t2_mask(
                imported_from,
                reference_path,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(f"The corrected T2 lesion mask is invalid: {exc}") from exc

        artifact_directory = (
            self._repository.root_path
            / "outputs"
            / "t2_lesion"
            / "artifacts"
            / subject_id
            / str(uuid4())
        )
        immutable_mask = artifact_directory / (
            "lesion_mask_thresholded.nii.gz"
            if origin == "THRESHOLD_ADJUSTED"
            else "lesion_mask_corrected.nii.gz"
        )
        qc_preview = artifact_directory / "qc_preview.png"
        try:
            artifact_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(imported_from, immutable_mask)
            measurement = validate_and_measure_t2_mask(
                immutable_mask,
                reference_path,
                expected_mask_sha256=source_measurement.mask_sha256,
            )
            self._qc_builder(reference_path, immutable_mask, qc_preview)
            artifact_metadata: dict[str, object] = {
                "shape": list(measurement.shape),
                "spacing_mm": list(measurement.spacing_mm),
                "axis_codes": list(measurement.axis_codes),
                "native_affine_preserved": True,
                "postprocessing": (
                    "none"
                    if origin == "THRESHOLD_ADJUSTED"
                    else "human correction in ITK-SNAP"
                ),
            }
            artifact_metadata.update(metadata or {})
            draft = T2CorrectedArtifactDraft(
                subject_id=subject_id,
                source_artifact_id=source_artifact.id,
                mask_path=immutable_mask,
                mask_sha256=measurement.mask_sha256,
                qc_preview_path=qc_preview,
                lesion_voxel_count=measurement.lesion_voxel_count,
                provisional_volume_mm3=measurement.lesion_volume_mm3,
                imported_from=imported_from,
                metadata=artifact_metadata,
                origin=origin,
            )
            artifact_id = self._repository.create_corrected_t2_artifact(
                draft,
                actor=actor,
            )
        except StudyStateError:
            shutil.rmtree(artifact_directory, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(artifact_directory, ignore_errors=True)
            raise StudyStateError(
                f"Could not import the corrected T2 lesion mask: {exc}"
            ) from exc
        return artifact_id

    def approve_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
    ) -> None:
        """Persist an immutable approval and create the official native-space result."""

        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        try:
            measurement = validate_and_measure_t2_mask(
                artifact.mask_path,
                reference_path,
                expected_mask_sha256=artifact.mask_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The T2 lesion mask cannot be approved: {exc}"
            ) from exc
        self._repository.record_t2_approval(
            artifact_id,
            reviewer=reviewer,
            measurement=measurement,
        )

    def _active_artifact_and_reference(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> tuple[T2LesionArtifactRecord, Path]:
        snapshot = self._repository.snapshot()
        if snapshot.subject(subject_id) is None:
            raise StudyStateError("The selected subject is not active in this study.")
        artifact = next(
            (
                item
                for item in snapshot.t2_artifacts_for_subject(subject_id)
                if item.id == artifact_id
            ),
            None,
        )
        if artifact is None:
            raise StudyStateError("The selected T2 lesion artifact is unavailable.")
        if not artifact.active or artifact.state not in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
            ArtifactState.APPROVED,
        }:
            raise StudyStateError(
                "Select the current T2 lesion mask for this subject."
            )
        scan = next(
            (
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.id == artifact.source_scan_input_id
                and record.state is ScanImportState.CONVERTED
                and record.output_path is not None
            ),
            None,
        )
        if scan is None or scan.output_path is None or not scan.output_path.is_file():
            raise StudyStateError("The native T2 input for this artifact is unavailable.")
        return artifact, scan.output_path
