"""Tests for V1 pipeline readiness summaries."""

from __future__ import annotations

from pathlib import Path

from lys_bbb.pipeline_status import build_status, write_markdown


def test_status_reports_brain_mask_blocker_and_dry_run_command():
    status = build_status(
        qc_summary={"n_cases": 2},
        manual_worklist_rows=[
            {"manual_status": "needs_prelabel_or_manual_mask"},
            {"manual_status": "needs_correction_or_review"},
        ],
        analysis_manifest_rows=[
            {"case_id": "C1_D1", "qc_gate": "missing_brain_mask", "include": "no"},
            {"case_id": "C2_D1", "qc_gate": "mask_needs_review", "include": "no"},
        ],
        nnunet_manifest_rows=[
            {"case_id": "C1_D1", "split": "test"},
            {"case_id": "C2_D1", "split": "test"},
        ],
        registration_rows=[],
    )

    assert status["analysis_included"] == 0
    assert status["analysis_gate_counts"] == {"mask_needs_review": 1, "missing_brain_mask": 1}
    assert any("brain masks" in blocker for blocker in status["blockers"])
    assert any("--dry-run" in command for command in status["next_commands"])


def test_status_unlocks_real_cohort_command_when_cases_are_included():
    status = build_status(
        qc_summary={},
        manual_worklist_rows=[{"manual_status": "ready_candidate"}],
        analysis_manifest_rows=[
            {"case_id": "C1_D1", "qc_gate": "ready_for_provisional_quantification", "include": "yes"}
        ],
        nnunet_manifest_rows=[{"case_id": "C1_D1", "split": "train"} for _ in range(8)],
        registration_rows=[
            {"case_id": "C1_D1", "before_xcorr": "0.4", "after_xcorr": "0.8"},
            {"case_id": "C2_D1", "before_xcorr": "0.5", "after_xcorr": "0.7"},
        ],
    )

    assert status["analysis_included"] == 1
    assert status["registration"]["n_improved"] == 2
    assert status["registration"]["min_after_xcorr"] == 0.7
    assert any("prepare_nnunet" in command for command in status["next_commands"])
    cohort_commands = [command for command in status["next_commands"] if "quantify_flash_cohort.py" in command]
    assert len(cohort_commands) == 1
    assert "--dry-run" not in cohort_commands[0]


def test_write_markdown_includes_counts_and_commands(tmp_path: Path):
    status = build_status(
        qc_summary={},
        manual_worklist_rows=[{"manual_status": "needs_prelabel_or_manual_mask"}],
        analysis_manifest_rows=[{"case_id": "C1_D1", "qc_gate": "missing_brain_mask", "include": "no"}],
        nnunet_manifest_rows=[{"case_id": "C1_D1", "split": "test"}],
        registration_rows=[{"case_id": "C1_D1", "before_xcorr": "0.2", "after_xcorr": "0.6"}],
    )
    out = tmp_path / "status.md"

    write_markdown(out, status)

    text = out.read_text()
    assert "# V1 Pipeline Status" in text
    assert "missing_brain_mask" in text
    assert "conda run -n lys-bbb" in text
    assert "C1_D1" in text
