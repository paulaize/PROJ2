"""Application service for T1 brain-mask correction and approval."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

from lys_bbb.t1_brain_mask_review import validate_t1_brain_mask
from lys_bbb_app.domain.errors import StudyStateError
from lys_bbb_app.domain.scan_import import ScanImportState, ScanRole
from lys_bbb_app.domain.t1_brain_mask import (
    T1BrainMaskArtifactRecord,
    T1CorrectedBrainMaskDraft,
)
from lys_bbb_app.domain.t2_lesion import ArtifactState
from lys_bbb_app.infrastructure.external_viewer import ExternalViewerError, ViewerLaunch
from lys_bbb_app.infrastructure.study_database import StudyRepository


ViewerLauncher = Callable[..., ViewerLaunch]
T1QCBuilder = Callable[[Path, Path, Path], Path]


@dataclass(frozen=True)
class T1BrainMaskEditSession:
    """One managed ITK-SNAP edit copy tied to an immutable T1 artifact."""

    subject_id: str
    source_artifact_id: str
    editable_mask_path: Path
    launch: ViewerLaunch


class T1BrainMaskReviewService:
    """Coordinate review files and persistence outside Qt widgets."""

    def __init__(
        self,
        repository: StudyRepository,
        *,
        viewer_launcher: ViewerLauncher,
        qc_builder: T1QCBuilder,
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
    ) -> T1BrainMaskEditSession:
        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        try:
            validate_t1_brain_mask(
                artifact.mask_path,
                reference_path,
                expected_mask_sha256=artifact.mask_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The T1 brain mask cannot be opened for correction: {exc}"
            ) from exc
        correction_id = str(uuid4())
        work_directory = (
            self._repository.root_path
            / "work"
            / "t1_brain_mask"
            / "corrections"
            / correction_id
        )
        editable_path = work_directory / "brain_mask_editable.nii.gz"
        try:
            work_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(artifact.mask_path, editable_path)
            (work_directory / "correction_manifest.json").write_text(
                json.dumps(
                    {
                        "source_artifact_id": artifact.id,
                        "source_mask_sha256": artifact.mask_sha256,
                        "subject_id": subject_id,
                        "native_pre_t1_path": str(reference_path),
                        "editable_mask_path": str(editable_path),
                        "instructions": (
                            "Save corrections over the editable mask, close ITK-SNAP, "
                            "then choose Use saved mask in LYS BBB. The registered "
                            "source artifact is immutable."
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
                f"Could not prepare the editable T1 brain mask: {exc}"
            ) from exc
        self._repository.record_audit_event(
            "T1_BRAIN_MASK_CORRECTION_COPY_OPENED_IN_ITKSNAP",
            actor=actor,
            subject_id=subject_id,
            details={
                "artifact_id": artifact.id,
                "registered_mask_path": str(artifact.mask_path),
                "editable_mask_path": str(editable_path),
                "source_mask_modified": False,
            },
        )
        return T1BrainMaskEditSession(
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
        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        if artifact.qc_preview_path is None:
            raise StudyStateError(
                "This T1 brain-mask artifact has no QC output location."
            )
        try:
            self._qc_builder(reference_path, artifact.mask_path, artifact.qc_preview_path)
        except (OSError, ValueError) as exc:
            raise StudyStateError(
                f"Could not prepare T1 brain-mask review slices: {exc}"
            ) from exc
        return tuple(
            sorted(
                (artifact.qc_preview_path.parent / "qc_slices").glob("slice_*.png")
            )
        )

    def finish_manual_edit(
        self,
        session: T1BrainMaskEditSession,
        *,
        actor: str,
    ) -> str:
        corrections_root = (
            self._repository.root_path / "work" / "t1_brain_mask" / "corrections"
        ).resolve()
        editable_path = session.editable_mask_path.expanduser().resolve()
        if not editable_path.is_relative_to(corrections_root):
            raise StudyStateError(
                "The selected T1 edit session is not managed by this study."
            )
        manifest_path = editable_path.parent / "correction_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StudyStateError("The managed T1 edit session is incomplete.") from exc
        if (
            manifest.get("subject_id") != session.subject_id
            or manifest.get("source_artifact_id") != session.source_artifact_id
            or Path(str(manifest.get("editable_mask_path", ""))).resolve()
            != editable_path
        ):
            raise StudyStateError("The managed T1 edit session does not match this mask.")
        return self._register_corrected_mask(
            session.subject_id,
            session.source_artifact_id,
            editable_path,
            actor=actor,
        )

    def approve_mask(
        self,
        subject_id: str,
        artifact_id: str,
        *,
        reviewer: str,
    ) -> None:
        artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            artifact_id,
        )
        if artifact.state not in {
            ArtifactState.DRAFT_REVIEW_REQUIRED,
            ArtifactState.CORRECTED_REVIEW_REQUIRED,
        }:
            raise StudyStateError(
                "Only the current T1 brain mask awaiting review can be approved."
            )
        try:
            measurement = validate_t1_brain_mask(
                artifact.mask_path,
                reference_path,
                expected_mask_sha256=artifact.mask_sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The T1 brain mask cannot be approved: {exc}"
            ) from exc
        self._repository.record_t1_brain_mask_approval(
            artifact.id,
            reviewer=reviewer,
            measurement=measurement,
        )

    def _register_corrected_mask(
        self,
        subject_id: str,
        source_artifact_id: str,
        corrected_path: Path,
        *,
        actor: str,
    ) -> str:
        source_artifact, reference_path = self._active_artifact_and_reference(
            subject_id,
            source_artifact_id,
        )
        imported_from = corrected_path.expanduser().resolve()
        try:
            source_measurement = validate_t1_brain_mask(
                imported_from,
                reference_path,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise StudyStateError(
                f"The corrected T1 brain mask is invalid: {exc}"
            ) from exc
        artifact_directory = (
            self._repository.root_path
            / "outputs"
            / "t1_brain_mask"
            / "artifacts"
            / subject_id
            / str(uuid4())
        )
        immutable_mask = artifact_directory / "brain_mask_corrected.nii.gz"
        qc_preview = artifact_directory / "qc_preview.png"
        try:
            artifact_directory.mkdir(parents=True, exist_ok=False)
            shutil.copy2(imported_from, immutable_mask)
            measurement = validate_t1_brain_mask(
                immutable_mask,
                reference_path,
                expected_mask_sha256=source_measurement.mask_sha256,
            )
            self._qc_builder(reference_path, immutable_mask, qc_preview)
            artifact_id = self._repository.create_corrected_t1_brain_mask_artifact(
                T1CorrectedBrainMaskDraft(
                    subject_id=subject_id,
                    source_artifact_id=source_artifact.id,
                    mask_path=immutable_mask,
                    mask_sha256=measurement.mask_sha256,
                    qc_preview_path=qc_preview,
                    foreground_voxels=measurement.foreground_voxels,
                    volume_mm3=measurement.volume_mm3,
                    imported_from=imported_from,
                    metadata={
                        "shape": list(measurement.shape),
                        "spacing_mm": list(measurement.spacing_mm),
                        "axis_codes": list(measurement.axis_codes),
                        "native_affine_preserved": True,
                        "postprocessing": "human correction in ITK-SNAP",
                    },
                ),
                actor=actor,
            )
        except StudyStateError:
            shutil.rmtree(artifact_directory, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(artifact_directory, ignore_errors=True)
            raise StudyStateError(
                f"Could not import the corrected T1 brain mask: {exc}"
            ) from exc
        return artifact_id

    def _active_artifact_and_reference(
        self,
        subject_id: str,
        artifact_id: str,
    ) -> tuple[T1BrainMaskArtifactRecord, Path]:
        snapshot = self._repository.snapshot()
        artifact = next(
            (
                item
                for item in snapshot.t1_brain_masks_for_subject(subject_id)
                if item.id == artifact_id
            ),
            None,
        )
        if artifact is None:
            raise StudyStateError("The selected T1 brain-mask artifact is unavailable.")
        if not artifact.active:
            raise StudyStateError("Use the subject's current T1 brain mask.")
        reference = next(
            (
                record
                for record in snapshot.inputs_for_subject(subject_id)
                if record.id == artifact.source_scan_input_id
                and record.role is ScanRole.T1_PRE
                and record.state is ScanImportState.CONVERTED
                and record.output_path is not None
            ),
            None,
        )
        if reference is None or reference.output_path is None:
            raise StudyStateError(
                "The native pre-Gd T1 used by this brain mask is unavailable."
            )
        return artifact, reference.output_path
