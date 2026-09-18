"""Anatomical preview geometry and refresh after saved orientation corrections."""

import os
from pathlib import Path
from threading import Event

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.scan_conversion import _correct_orientation
from lys_bbb_app.services.mri_preview import CoronalPreview, render_coronal_preview


def _image(path: Path):
    x, y, z = np.indices((21, 17, 13), dtype=np.float32)
    data = 10 + x**2 + 3 * y + 5 * z**2 + x * y
    image = nib.Nifti1Image(data, np.diag([0.1, 0.2, 0.3, 1]))
    nib.save(image, path)
    return image


def _pixels(preview):
    return np.frombuffer(preview.pixels, dtype=np.uint8).reshape(
        preview.height, preview.width
    )


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_preview_uses_corrected_world_orientation(tmp_path, axis):
    path = tmp_path / "original.nii.gz"
    image = _image(path)
    original_bytes = path.read_bytes()
    corrected_path = tmp_path / "corrected.nii.gz"
    nib.save(_correct_orientation(image, (axis,)), corrected_path)
    original = render_coronal_preview(path, 25 if axis != 1 else 75)
    corrected = render_coronal_preview(corrected_path, 25)
    expected = _pixels(original)
    if axis == 0:
        expected = np.fliplr(expected)
    elif axis == 2:
        expected = np.flipud(expected)
    np.testing.assert_allclose(_pixels(corrected), expected, atol=1)
    assert path.read_bytes() == original_bytes


def test_preview_is_independent_of_storage_order_and_preserves_aspect(tmp_path):
    path = tmp_path / "ras.nii.gz"
    image = _image(path)
    transform = nib.orientations.ornt_transform(
        nib.orientations.axcodes2ornt(("R", "A", "S")),
        nib.orientations.axcodes2ornt(("L", "I", "P")),
    )
    reordered = image.as_reoriented(transform)
    other = tmp_path / "lip.nii.gz"
    nib.save(reordered, other)
    a, b = render_coronal_preview(path), render_coronal_preview(other)
    np.testing.assert_allclose(_pixels(a), _pixels(b), atol=1)
    assert a.width / a.height == pytest.approx(2 / 3.6, abs=0.01)
    # Superior and right are both at the high-intensity top-left corner.
    pixels = _pixels(a)
    assert pixels[0, 0] > pixels[-1, -1]


def test_preview_keeps_highlight_detail_with_a_softer_display_window(tmp_path):
    path = tmp_path / "ramp.nii.gz"
    data = np.broadcast_to(
        np.arange(1, 321, dtype=np.float32)[:, None, None], (320, 3, 320)
    ).copy()
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    original_bytes = path.read_bytes()
    pixels = _pixels(render_coronal_preview(path))
    # Bright tissue stays light gray, with intensity differences still visible.
    assert 210 <= pixels.max() <= 230
    assert pixels[0, 0] > pixels[0, 20] > pixels[0, 40]
    assert pixels.min() == 0
    assert path.read_bytes() == original_bytes


def test_preview_handles_blank_scan_and_rejects_invalid_geometry(tmp_path):
    path = tmp_path / "blank.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((4, 5, 6)), np.eye(4)), path)
    assert not _pixels(render_coronal_preview(path)).any()
    nib.save(nib.Nifti1Image(np.zeros((4, 5, 6, 2)), np.eye(4)), path)
    with pytest.raises(ValueError, match="three-dimensional"):
        render_coronal_preview(path)


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_preview_ignores_stale_results_and_displays_load_errors(qt_app, tmp_path):
    from lys_bbb_app.ui.mri_preview import CoronalPreviewWidget

    widget = CoronalPreviewWidget(tmp_path / "missing.nii.gz")
    current = widget._cancelled
    widget._loaded(Event(), CoronalPreview(bytes([255] * 4), 2, 2), "")
    assert widget.image.pixmap() is None or widget.image.pixmap().isNull()
    widget._loaded(current, None, "File missing")
    assert widget.image.text() == "Preview unavailable"
    assert widget.image.toolTip() == "File missing"
    widget.cancel()
    widget._loaded(current, CoronalPreview(bytes([255] * 4), 2, 2), "")
    assert widget.image.text() == "Preview unavailable"
    widget.close()


def test_subject_preview_refreshes_after_each_correction(qt_app, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog
    from lys_bbb.mri_import import (
        ImportConfidence,
        OrientationPolicy,
        ScanImportAssignment,
        ScanRole,
        SourceFormat,
    )
    from lys_bbb_app.application.study_presenter import present_study
    from lys_bbb_app.domain.study import AnalysisScope, CreateStudyRequest
    from lys_bbb_app.features import T2_FEATURES
    from lys_bbb_app.services.recent_studies_service import RecentStudiesService
    from lys_bbb_app.services.study_service import StudyService
    from lys_bbb_app.ui.main_window import MainWindow
    from lys_bbb_app.ui.mri_action_dialogs import BulkFlipDialog
    from lys_bbb_app.ui.mri_preview import _PREVIEW_POOL

    source = tmp_path / "source.nii.gz"
    _image(source)
    service = StudyService(features=T2_FEATURES)
    service.create_study(
        CreateStudyRequest(
            tmp_path / "study",
            "Preview",
            "preview",
            analysis_scope=AnalysisScope.T2_ONLY,
            actor="Tester",
        )
    )
    assignment = ScanImportAssignment(
        "test",
        "Mouse-01",
        ScanRole.T2,
        source,
        SourceFormat.NIFTI,
        "session",
        None,
        "T2",
        "NIfTI",
        "RAS",
        ImportConfidence.HIGH,
        OrientationPolicy.NATIVE,
    )
    snapshot = service.import_confirmed_scans((assignment,), actor="Tester")
    window = MainWindow(
        study_service=service,
        features=T2_FEATURES,
        recent_studies=RecentStudiesService(tmp_path / "recent.json"),
    )
    window._set_study(present_study(snapshot))
    subject_id = snapshot.subjects[0].id
    window.open_subject(subject_id)
    panel = window.workspace_page.inputs_panel
    window.workspace_page.tabs.setCurrentWidget(panel)
    window.show()

    def wait_preview():
        qt_app.processEvents()
        QTest.qWait(220)
        assert _PREVIEW_POOL.waitForDone(10000)
        qt_app.processEvents()
        assert len(panel.previews) == 1
        assert not panel.previews[0].image.pixmap().isNull()

    try:
        wait_preview()
        panel.previews[0].slider.setValue(30)
        wait_preview()
        last_path = panel.previews[0].path

        def accept_flip(dialog):
            dialog.axis_boxes[0].setChecked(True)
            return QDialog.Accepted

        monkeypatch.setattr(BulkFlipDialog, "exec", accept_flip)
        for version in (2, 3):
            record = service.converted_mri_inputs(subject_id)[0]
            window.bulk_flip_subjects((subject_id,), scan_input_id=record.id)
            thread = window._background_jobs.get("scan_import")
            assert thread is not None and thread.wait(10000)
            for _ in range(10):
                qt_app.processEvents()
            wait_preview()
            record = service.converted_mri_inputs(subject_id)[0]
            assert record.version == version
            assert record.validation_state.value == "NOT_RUN"
            assert panel.previews[0].path == record.output_path != last_path
            assert panel.previews[0].slider.value() == 30
            assert (
                window.content_stack.currentIndex() == window.page_indices["workspace"]
            )
            last_path = record.output_path
        window.validate_subject_inputs(subject_id)
        thread = window._background_jobs.get("input_validation")
        assert thread.wait(10000)
        for _ in range(10):
            qt_app.processEvents()
        wait_preview()
        assert (
            service.converted_mri_inputs(subject_id)[0].validation_state.value
            == "VALID"
        )
        assert panel.previews[0].path == last_path
    finally:
        for preview in panel.previews:
            preview.cancel()
        _PREVIEW_POOL.waitForDone(10000)
        window.close()
