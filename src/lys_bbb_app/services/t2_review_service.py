"""Application service for T2 correction, review, and official measurement."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.t2_review import validate_and_measure_t2_mask
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import ScanImportState
from lys_bbb_app.domain.t2_lesion import (
    ArtifactState,
    ReviewDecision,
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

    def open_editable_copy_in_itksnap(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        actor: str,
        viewer_path: Path | str | None = None,
    ) -> ViewerLaunch:
        """Create a disposable correction copy and launch it with the native T2."""

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
                            "Save corrections to the editable mask, then import that "
                            "file in LYS BBB. The registered source artifact is immutable."
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
        return launch

    def import_corrected_mask(
        self,
        subject_id: str,
        source_artifact_id: str,
        corrected_path: Path | str,
        *,
        actor: str,
    ) -> str:
        """Validate and copy one correction into immutable study-owned storage."""

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
        immutable_mask = artifact_directory / "lesion_mask_corrected.nii.gz"
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
            draft = T2CorrectedArtifactDraft(
                subject_id=subject_id,
                source_artifact_id=source_artifact.id,
                mask_path=immutable_mask,
                mask_sha256=measurement.mask_sha256,
                qc_preview_path=qc_preview,
                lesion_voxel_count=measurement.lesion_voxel_count,
                provisional_volume_mm3=measurement.lesion_volume_mm3,
                imported_from=imported_from,
                metadata={
                    "shape": list(measurement.shape),
                    "spacing_mm": list(measurement.spacing_mm),
                    "axis_codes": list(measurement.axis_codes),
                    "native_affine_preserved": True,
                    "postprocessing": "human correction in ITK-SNAP",
                },
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

    def review_mask(
        self,
        subject_id: str,
        artifact_id: str,
        decision: ReviewDecision,
        *,
        reviewer: str,
        issue_code: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Persist an immutable review and create a result only on approval."""

        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        measurement = None
        if decision is ReviewDecision.APPROVED:
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
        self._repository.record_t2_review(
            artifact_id,
            decision,
            reviewer=reviewer,
            issue_code=issue_code,
            notes=notes,
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
