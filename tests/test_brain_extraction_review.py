import csv
import json
import zipfile
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.brain_extraction_review import (
    ReviewPrediction,
    group_predictions,
    itksnap_command,
    locate_results_root,
    read_predictions,
    upsert_case_review,
    validate_prediction,
    write_overall_decision,
)
from scripts.brain_extraction.review_colab_results import main as review_main


def save_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.eye(4) if affine is None else affine), path)


def write_manifest(root: Path, rows: list[dict[str, str]]) -> None:
    fields = ["case_id", "model_id", "status", "image", "mask", "metadata", "log", "message"]
    with (root / "run_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_results(root: Path) -> None:
    image = np.arange(64, dtype=np.float32).reshape((4, 4, 4))
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1:3, 1:3, 1:3] = 1
    save_nifti(root / "inputs/C1_pre_t1.nii.gz", image)
    save_nifti(root / "predictions/mbe_invivo_iso/C1_brain_mask.nii.gz", mask)
    save_nifti(root / "predictions/rs2net/C1_brain_mask.nii.gz", mask)
    write_manifest(
        root,
        [
            {
                "case_id": "C1",
                "model_id": "mbe_invivo_iso",
                "status": "ok",
                "image": "inputs/C1_pre_t1.nii.gz",
                "mask": "predictions/mbe_invivo_iso/C1_brain_mask.nii.gz",
                "metadata": "",
                "log": "",
                "message": "",
            },
            {
                "case_id": "C1",
                "model_id": "rs2net",
                "status": "ok",
                "image": "inputs/C1_pre_t1.nii.gz",
                "mask": "predictions/rs2net/C1_brain_mask.nii.gz",
                "metadata": "",
                "log": "",
                "message": "",
            },
            {
                "case_id": "C2",
                "model_id": "rs2net",
                "status": "failed",
                "image": "inputs/C2_pre_t1.nii.gz",
                "mask": "",
                "metadata": "",
                "log": "logs/rs2net/C2.log",
                "message": "inference failed",
            },
        ],
    )


def test_read_validate_group_and_itksnap_command(tmp_path: Path) -> None:
    build_results(tmp_path)
    predictions = read_predictions(tmp_path)
    assert [(item.case_id, item.model_id) for item in predictions] == [
        ("C1", "mbe_invivo_iso"),
        ("C1", "rs2net"),
    ]
    assert all(validate_prediction(item) == [] for item in predictions)
    assert list(group_predictions(predictions)) == ["C1"]
    assert itksnap_command(Path("itksnap"), predictions[0]) == [
        "itksnap",
        "-g",
        str(tmp_path / "inputs/C1_pre_t1.nii.gz"),
        "-s",
        str(tmp_path / "predictions/mbe_invivo_iso/C1_brain_mask.nii.gz"),
    ]


def test_validation_reports_grid_and_binary_errors(tmp_path: Path) -> None:
    image = tmp_path / "image.nii.gz"
    mask = tmp_path / "mask.nii.gz"
    save_nifti(image, np.ones((4, 4, 4), dtype=np.float32))
    save_nifti(mask, np.full((3, 4, 4), 2, dtype=np.uint8))
    prediction = ReviewPrediction("C1", "model", image, mask)
    errors = validate_prediction(prediction)
    assert any("shape mismatch" in error for error in errors)
    assert any("not binary" in error for error in errors)


def test_locate_results_root_extracts_nested_zip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    build_results(source)
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        for path in source.rglob("*"):
            if path.is_file():
                stream.write(path, Path("t1_brain_extraction_results") / path.relative_to(source))
    root = locate_results_root(archive)
    assert root.name == "t1_brain_extraction_results"
    assert (root / "run_manifest.csv").is_file()


def test_locate_results_root_rejects_unsafe_zip(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../escape.txt", "no")
    with pytest.raises(ValueError, match="unsafe archive path"):
        locate_results_root(archive)


def test_review_and_overall_decision_are_auditable(tmp_path: Path) -> None:
    review = tmp_path / "model_review.csv"
    upsert_case_review(review, case_id="C2", preferred_model="rs2net")
    upsert_case_review(review, case_id="C1", preferred_model="mbe_invivo_iso")
    with review.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["case_id"] for row in rows] == ["C1", "C2"]
    assert rows[0]["review_status"] == "selected"

    decision = tmp_path / "benchmark_decision.json"
    write_overall_decision(decision, "rs2net", {"rs2net": 1})
    payload = json.loads(decision.read_text())
    assert payload["selected_model"] == "rs2net"
    assert payload["decision_status"] == "provisional_visual_selection"


def test_review_cli_dry_run_prints_one_pair_per_prediction(tmp_path: Path, capsys) -> None:
    build_results(tmp_path)
    assert review_main([str(tmp_path), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert output.count(" -g ") == 2
    assert output.count(" -s ") == 2
    assert "Dry run complete" in output


def test_review_cli_combines_distinct_models_from_two_archives(tmp_path: Path, capsys) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    build_results(primary)

    extra = tmp_path / "extra"
    extra.mkdir()
    image = np.arange(64, dtype=np.float32).reshape((4, 4, 4))
    mask = np.zeros((4, 4, 4), dtype=np.uint8)
    mask[1:3, 1:3, 1:3] = 1
    save_nifti(extra / "inputs/C1_pre_t1.nii.gz", image)
    save_nifti(extra / "predictions/deepbet_human_t1/C1_brain_mask.nii.gz", mask)
    write_manifest(
        extra,
        [
            {
                "case_id": "C1",
                "model_id": "deepbet_human_t1",
                "status": "ok",
                "image": "inputs/C1_pre_t1.nii.gz",
                "mask": "predictions/deepbet_human_t1/C1_brain_mask.nii.gz",
                "metadata": "",
                "log": "",
                "message": "",
            }
        ],
    )

    assert review_main([str(primary), str(extra), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert output.count(" -g ") == 3
    assert output.count(" -s ") == 3
    assert "t1_brain_extraction_combined_review" in output


def test_review_cli_rejects_duplicate_case_model_across_archives(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    build_results(first)
    build_results(second)
    with pytest.raises(ValueError, match="duplicate predictions across result archives"):
        review_main([str(first), str(second), "--dry-run"])
