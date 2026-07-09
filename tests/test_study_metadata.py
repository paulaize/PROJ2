"""Tests for editable study metadata manifests."""

from __future__ import annotations

from pathlib import Path

from lys_bbb.study_metadata import (
    build_study_metadata_rows,
    source_rows_from_analysis_manifest,
    source_rows_from_input_root,
    validate_study_metadata_rows,
)


def test_source_rows_from_analysis_manifest_preserves_case_identity():
    rows = source_rows_from_analysis_manifest([
        {"case_id": "C25S1_D7"},
        {"case_id": "C25S1_D1", "animal_id": "C25S1", "timepoint": "D1"},
    ])

    assert [row["case_id"] for row in rows] == ["C25S1_D1", "C25S1_D7"]
    assert rows[1]["animal_id"] == "C25S1"
    assert rows[1]["timepoint"] == "D7"


def test_build_study_metadata_preserves_edits_and_propagates_animal_fields():
    source_rows = [
        {"case_id": "C25S1_D1", "animal_id": "C25S1", "timepoint": "D1"},
        {"case_id": "C25S1_D7", "animal_id": "C25S1", "timepoint": "D7"},
    ]
    previous_rows = [{
        "case_id": "C25S1_D1",
        "animal_id": "C25S1",
        "timepoint": "D1",
        "include": "include",
        "group": "treated",
        "stroke_side": "Left",
        "lesion_mask": "lesions/C25S1_D1.nii.gz",
        "review_status": "passed",
        "review_notes": "looks good",
    }]

    rows = build_study_metadata_rows(source_rows, previous_rows=previous_rows)

    assert rows[0]["include"] == "yes"
    assert rows[0]["group"] == "treated"
    assert rows[0]["ipsilateral_side"] == "left"
    assert rows[0]["lesion_mask_path"] == "lesions/C25S1_D1.nii.gz"
    assert rows[0]["review_status"] == "pass"
    assert rows[1]["group"] == "treated"
    assert rows[1]["ipsilateral_side"] == "left"
    assert rows[1]["lesion_mask_path"] == ""


def test_source_rows_from_input_root_requires_converted_pre_and_post(tmp_path: Path):
    converted = tmp_path / "C25S1_D1"
    converted.mkdir()
    (converted / "pre_coronal.nii.gz").touch()
    (converted / "post_coronal.nii.gz").touch()
    incomplete = tmp_path / "C25S1_D7"
    incomplete.mkdir()
    (incomplete / "pre_coronal.nii.gz").touch()

    rows = source_rows_from_input_root(tmp_path)

    assert [row["case_id"] for row in rows] == ["C25S1_D1"]


def test_validate_study_metadata_reports_invalid_values_and_duplicates():
    rows = [
        {
            "case_id": "C25S1_D1",
            "animal_id": "C25S1",
            "timepoint": "D1",
            "include": "maybe",
            "ipsilateral_side": "center",
            "review_status": "unknown",
        },
        {
            "case_id": "C25S1_D1",
            "animal_id": "C25S1",
            "timepoint": "D1",
            "include": "",
            "ipsilateral_side": "",
            "review_status": "",
        },
    ]

    issues = validate_study_metadata_rows(rows)

    fields = {(issue["severity"], issue["field"]) for issue in issues}
    assert ("error", "case_id") in fields
    assert ("warning", "timepoint") in fields
    assert ("error", "include") in fields
    assert ("error", "ipsilateral_side") in fields
    assert ("error", "review_status") in fields
