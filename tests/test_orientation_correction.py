"""Saved orientation corrections and multi-selection validation regressions."""

from dataclasses import replace
import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.mri_import import (
    ImportConfidence, OrientationPolicy, ScanImportAssignment, ScanRole, SourceFormat,
)
from lys_bbb.scan_conversion import convert_scan_assignment
from lys_bbb_app.domain.study import AnalysisScope, CreateStudyRequest
from lys_bbb_app.services.study_service import StudyService


def assignment(tmp_path: Path, name: str = "Mouse-01", role: ScanRole = ScanRole.T2):
    source = tmp_path / f"{name}-{role.value}.nii.gz"
    # Asymmetric anatomy and an oblique, translated but orthogonal affine.
    affine = np.array([[0.08, -0.12, 0, 2], [0.06, 0.16, 0, -3], [0, 0, 0.5, 5], [0, 0, 0, 1]])
    nib.save(nib.Nifti1Image(np.arange(24, dtype=np.float32).reshape(2, 3, 4), affine), source)
    return ScanImportAssignment(
        proposal_id=f"{name}-{role.value}", subject_code=name, role=role,
        source_path=source, source_format=SourceFormat.NIFTI, session_id="test",
        scan_id=None, protocol="test", method="NIfTI", acquisition_orientation="from affine",
        confidence=ImportConfidence.HIGH, orientation_policy=OrientationPolicy.NATIVE,
    )


@pytest.mark.parametrize("axes", [(0,), (1,), (2,), (0, 1, 2)])
def test_correction_reflects_anatomy_without_resampling_and_is_reversible(tmp_path, axes):
    initial = assignment(tmp_path)
    original_bytes = initial.source_path.read_bytes()
    original = nib.load(initial.source_path)
    result = convert_scan_assignment(
        replace(initial, orientation_correction=True, flip_axes=axes),
        output_directory=tmp_path / "v2", work_directory=tmp_path / "work",
    )
    corrected = nib.load(result.output_path)
    np.testing.assert_array_equal(corrected.get_fdata(), original.get_fdata())
    canonical_original = nib.as_closest_canonical(original).get_fdata()
    np.testing.assert_array_equal(
        nib.as_closest_canonical(corrected).get_fdata(), np.flip(canonical_original, axis=axes),
    )
    center = np.r_[(np.array(original.shape) - 1) / 2, 1]
    np.testing.assert_allclose(corrected.affine @ center, original.affine @ center, atol=1e-6)
    np.testing.assert_allclose(corrected.get_qform(), corrected.get_sform(), atol=1e-6)
    assert initial.source_path.read_bytes() == original_bytes
    provenance = json.loads(result.provenance_path.read_text())
    assert provenance["transform"]["orientation_correction_axes"] == list(axes)
    assert provenance["transform"]["storage_axis_flips"] == []
    restored = convert_scan_assignment(
        replace(initial, source_path=result.output_path, orientation_correction=True, flip_axes=axes),
        output_directory=tmp_path / "v3", work_directory=tmp_path / "work",
    )
    np.testing.assert_allclose(nib.load(restored.output_path).affine, original.affine, atol=1e-6)


def test_correction_targets_one_managed_image_and_resets_validation(tmp_path):
    service = StudyService()
    service.create_study(CreateStudyRequest(tmp_path / "study", "Test", "test", actor="Tester"))
    imports = (assignment(tmp_path), assignment(tmp_path, role=ScanRole.T1_PRE))
    snapshot = service.import_confirmed_scans(imports, actor="Tester")
    subject = snapshot.subjects[0]
    service.validate_subject_inputs(subject.id, actor="Tester")
    target = next(r for r in snapshot.scan_inputs if r.role is ScanRole.T2)
    old_bytes = target.output_path.read_bytes()
    # Moving raw data must no longer break correction of the managed version.
    imports[0].source_path.rename(tmp_path / "moved.nii.gz")
    plan = service.plan_orientation_correction((subject.id,), (1,), (ScanRole.T2, ScanRole.T1_PRE), scan_input_id=target.id)
    assert len(plan) == 1
    assert plan[0].source_path == target.output_path
    snapshot = service.import_confirmed_scans(plan, actor="Tester")
    corrected = next(r for r in snapshot.scan_inputs if r.active and r.role is ScanRole.T2)
    assert corrected.version == 2
    assert corrected.validation_state.value == "NOT_RUN"
    assert target.output_path.read_bytes() == old_bytes
    assert next(r for r in snapshot.scan_inputs if r.active and r.role is ScanRole.T1_PRE).version == 1
    assert corrected.output_axis_codes != target.output_axis_codes
    # Reopening preserves the correction and provenance.
    reopened = service.open_study(tmp_path / "study")
    assert next(r for r in reopened.scan_inputs if r.id == corrected.id).output_axis_codes == corrected.output_axis_codes


def test_correction_rejects_changed_managed_source(tmp_path):
    service = StudyService()
    service.create_study(CreateStudyRequest(tmp_path / "study", "Test", "test", actor="Tester"))
    snapshot = service.import_confirmed_scans((assignment(tmp_path),), actor="Tester")
    target = snapshot.scan_inputs[0]
    plan = service.plan_orientation_correction((target.subject_id,), (0,), (ScanRole.T2,))
    image = nib.load(target.output_path)
    nib.save(nib.Nifti1Image(image.get_fdata() + 1, image.affine), target.output_path)
    snapshot = service.import_confirmed_scans(plan, actor="Tester")
    assert next(r for r in snapshot.scan_inputs if r.active).id == target.id
    assert any(r.state.value == "FAILED" for r in snapshot.scan_inputs)


def test_correction_refuses_shear_instead_of_writing_conflicting_headers(tmp_path):
    initial = assignment(tmp_path)
    image = nib.load(initial.source_path)
    affine = image.affine.copy()
    affine[0, 2] = 0.2
    nib.save(nib.Nifti1Image(image.get_fdata(), affine), initial.source_path)
    with pytest.raises(nib.spatialimages.HeaderDataError, match="Shears"):
        convert_scan_assignment(
            replace(initial, orientation_correction=True, flip_axes=(0,)),
            output_directory=tmp_path / "corrected", work_directory=tmp_path / "work",
        )
    assert not (tmp_path / "corrected").exists()


def test_batch_correction_refuses_different_axis_mappings(tmp_path):
    from lys_bbb_app.domain.errors import StudyStateError

    service = StudyService()
    service.create_study(CreateStudyRequest(tmp_path / "study", "Test", "test", actor="Tester"))
    first, second = assignment(tmp_path, "Mouse-01"), assignment(tmp_path, "Mouse-02")
    image = nib.load(second.source_path)
    affine = image.affine.copy()
    affine[:3, 0] *= -1
    nib.save(nib.Nifti1Image(image.get_fdata(), affine), second.source_path)
    snapshot = service.import_confirmed_scans((first, second), actor="Tester")
    with pytest.raises(StudyStateError, match="different axis orientations"):
        service.plan_orientation_correction(tuple(s.id for s in snapshot.subjects), (0,), (ScanRole.T2,))


def test_multi_selection_validation_stays_visible_and_preserves_selection(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QItemSelectionModel, Qt
    from PySide6.QtWidgets import QApplication
    from lys_bbb_app.application.study_presenter import present_study
    from lys_bbb_app.features import T2_FEATURES
    from lys_bbb_app.ui.main_window import MainWindow
    from lys_bbb_app.services.recent_studies_service import RecentStudiesService

    app = QApplication.instance() or QApplication([])
    service = StudyService(features=T2_FEATURES)
    service.create_study(CreateStudyRequest(tmp_path / "study", "Test", "test", analysis_scope=AnalysisScope.T2_ONLY, actor="Tester"))
    snapshot = service.import_confirmed_scans((assignment(tmp_path, "Mouse-01"), assignment(tmp_path, "Mouse-02")), actor="Tester")
    window = MainWindow(study_service=service, features=T2_FEATURES, recent_studies=RecentStudiesService(tmp_path / "recent.json"))
    window._set_study(present_study(snapshot), page_key="subjects")
    page = window.subjects_page
    page.table.sortByColumn(0, Qt.DescendingOrder)
    for row in range(2):
        page.table.selectionModel().select(page.proxy.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert not page.validate_selected.isHidden()
    assert page.validate_selected.isEnabled()
    assert "(2)" in page.validate_selected.text()
    page.validate_selected.click()
    thread = window._background_jobs.get("input_validation")
    assert thread is not None and thread.wait(10000)
    for _ in range(10):
        app.processEvents()
    assert all(r.validation_state.value == "VALID" for r in service.current_study.scan_inputs)
    assert len(page._selected_subjects()) == 2
    assert not page.validate_selected.isHidden()
    assert not page.validate_selected.isEnabled()
    window.close()


def test_batch_validation_continues_after_one_subject_errors():
    from lys_bbb_app.ui.workers import BatchInputValidationThread

    class Service:
        current_study = object()
        called = []

        def validate_subject_inputs(self, subject_id, *, actor):
            self.called.append(subject_id)
            if subject_id == "bad":
                raise RuntimeError("Unavailable input")

    service = Service()
    worker = BatchInputValidationThread(service, ("bad", "good", "good"), actor="Tester")
    results = []
    worker.validation_completed.connect(lambda snapshot, errors: results.append((snapshot, errors)))
    worker.run()
    assert service.called == ["bad", "good"]
    assert results == [(service.current_study, {"bad": "Unavailable input"})]


def test_correction_dialog_exposes_only_selected_scan_role_and_axis_mapping(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog, QLabel
    from lys_bbb_app.ui.mri_action_dialogs import BulkFlipDialog

    app = QApplication.instance() or QApplication([])
    service = StudyService()
    service.create_study(CreateStudyRequest(tmp_path / "study", "Test", "test", actor="Tester"))
    snapshot = service.import_confirmed_scans((assignment(tmp_path),), actor="Tester")
    dialog = BulkFlipDialog(1, inputs=(snapshot.scan_inputs[0],))
    assert not any("Correct a mislabelled" in label.text() for label in dialog.findChildren(QLabel))
    assert any("Check and validate" in label.text() for label in dialog.findChildren(QLabel))
    assert dialog.scope.count() == 1
    assert dialog.roles() == (ScanRole.T2,)
    assert dialog.axis_boxes[0].text() == "X (R → L)"
    assert dialog.axis_boxes[1].text() == "Y (A → P)"
    dialog.accept()
    assert dialog.result() != QDialog.Accepted
    dialog.axis_boxes[1].setChecked(True)
    dialog.accept()
    assert dialog.result() == QDialog.Accepted
    assert dialog.flip_axes() == (1,)
    dialog.close()
    app.processEvents()
