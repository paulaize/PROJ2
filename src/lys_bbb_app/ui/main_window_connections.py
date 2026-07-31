"""Signal wiring for the desktop application shell."""

from __future__ import annotations

from typing import Any


def connect_main_window_signals(window: Any) -> None:
    """Connect page requests to the stable MainWindow action API."""

    window.overview_page.navigate_requested.connect(window.show_page)
    window.subjects_page.subject_open_requested.connect(window.open_subject)
    window.subjects_page.subject_mri_open_requested.connect(
        window.open_subject_mri_in_itksnap
    )
    window.subjects_page.subject_validation_requested.connect(
        lambda subject_id: window.validate_subject_inputs(
            subject_id,
            return_page="subjects",
        )
    )
    window.subjects_page.subjects_flip_requested.connect(window.bulk_flip_subjects)
    window.subjects_page.subject_remove_requested.connect(window.remove_subject)
    window.subjects_page.subject_restore_requested.connect(window.restore_subject)
    window.subjects_page.add_subject_requested.connect(window.add_subject)
    window.subjects_page.import_mri_requested.connect(
        window.select_mri_source_folder
    )
    window.subjects_page.group_assignment_requested.connect(window.manage_groups)
    window.subjects_page.audit_history_requested.connect(window.show_audit_history)
    window.subjects_page.t2_inference_requested.connect(
        window.run_t2_inference_for_study
    )
    window.subjects_page.longitudinal_identifiers_requested.connect(
        lambda subject_id, animal_id, time_id: (
            window.update_subject_longitudinal_identifiers(
                subject_id,
                animal_id,
                time_id,
                return_page="subjects",
            )
        )
    )

    window.workspace_page.back_requested.connect(
        lambda: window.show_page("subjects")
    )
    window.workspace_page.open_mri_requested.connect(
        window.open_subject_mri_in_itksnap
    )
    window.workspace_page.input_mri_open_requested.connect(
        window.open_scan_input_in_itksnap
    )
    window.workspace_page.input_validation_requested.connect(
        window.validate_subject_inputs
    )
    window.workspace_page.input_flip_requested.connect(
        lambda subject_id: window.bulk_flip_subjects((subject_id,))
    )
    window.workspace_page.input_import_requested.connect(
        window.select_mri_source_folder
    )
    window.workspace_page.rename_requested.connect(window.rename_subject)
    window.workspace_page.longitudinal_identifiers_requested.connect(
        lambda subject_id, animal_id, time_id: (
            window.update_subject_longitudinal_identifiers(
                subject_id,
                animal_id,
                time_id,
                return_page="workspace",
            )
        )
    )
    window.workspace_page.t2_release_requested.connect(
        window.select_t2_model_release
    )
    window.workspace_page.t2_run_subject_requested.connect(
        lambda subject_id: window.run_t2_inference_for_study((subject_id,))
    )
    window.workspace_page.t2_run_study_requested.connect(
        window.run_t2_inference_for_study
    )
    window.workspace_page.t2_manual_edit_requested.connect(
        window.manually_edit_t2_mask
    )
    window.workspace_page.t2_approve_requested.connect(window.approve_t2_mask)
    window.workspace_page.t1_brain_mask_release_requested.connect(
        window.select_t1_brain_mask_release
    )
    window.workspace_page.t1_brain_mask_run_requested.connect(
        window.run_t1_brain_mask_for_subject
    )
    window.workspace_page.t1_brain_mask_manual_edit_requested.connect(
        window.manually_edit_t1_brain_mask
    )
    window.workspace_page.t1_brain_mask_approve_requested.connect(
        window.approve_t1_brain_mask
    )
    window.workspace_page.t1_registration_run_requested.connect(
        window.run_t1_registration_for_subject
    )
    window.workspace_page.t1_registration_approve_requested.connect(
        window.approve_t1_registration
    )
    window.workspace_page.t1_enhancement_run_requested.connect(
        window.run_t1_enhancement_for_subject
    )
    window.workspace_page.t1_to_t2_run_requested.connect(
        lambda subject_id: window.start_atlas_mapping_stage(
            subject_id,
            "t1_to_t2",
        )
    )
    window.workspace_page.t1_to_t2_approve_requested.connect(
        window.approve_atlas_t1_to_t2
    )

    if window.features.atlas_mapping:
        _connect_atlas_signals(window)

    window.reviews_page.approve_requested.connect(
        lambda subject_id, artifact_id: window.approve_review_mask(
            subject_id,
            artifact_id,
            return_page="reviews",
        )
    )
    window.reviews_page.manual_edit_requested.connect(
        lambda subject_id, artifact_id: window.manually_edit_review_mask(
            subject_id,
            artifact_id,
            return_page="reviews",
        )
    )
    window.reviews_page.subject_requested.connect(window.open_review_subject)
    window.reviews_page.qc_slices_requested.connect(window.prepare_review_qc_slices)
    window.reviews_page.threshold_apply_requested.connect(
        window.apply_review_t2_probability_threshold
    )
    window.results_page.approved_csv_requested.connect(
        window.export_approved_t2_results_csv
    )
    window.results_page.approved_excel_requested.connect(
        window.export_approved_t2_results_excel
    )
    window.settings_page.blinding_changed.connect(window._handle_blinding_toggle)
    window.settings_page.input_folder_requested.connect(window.select_input_folder)
    window.settings_page.t2_model_changed.connect(window._handle_t2_model_choice)


def _connect_atlas_signals(window: Any) -> None:
    window.workspace_page.atlas_resource_requested.connect(
        window.configure_atlas_resource
    )
    window.workspace_page.atlas_scheme_register_requested.connect(
        window.register_major_region_scheme
    )
    window.workspace_page.atlas_scheme_approve_requested.connect(
        window.approve_major_region_scheme
    )
    window.workspace_page.atlas_support_mask_import_requested.connect(
        window.import_t2_registration_support_mask
    )
    window.workspace_page.atlas_support_mask_approve_requested.connect(
        window.approve_t2_registration_support_mask
    )
    window.workspace_page.atlas_to_t1_run_requested.connect(
        lambda subject_id: window.start_atlas_mapping_stage(
            subject_id,
            "atlas_to_t1",
        )
    )
    window.workspace_page.atlas_to_t1_approve_requested.connect(
        window.approve_atlas_to_t1
    )
    window.workspace_page.atlas_composite_create_requested.connect(
        lambda subject_id: window.start_atlas_mapping_stage(
            subject_id,
            "composite",
        )
    )
    window.workspace_page.atlas_composite_approve_requested.connect(
        window.approve_atlas_composite
    )
    window.workspace_page.atlas_result_calculate_requested.connect(
        window.calculate_atlas_result
    )
