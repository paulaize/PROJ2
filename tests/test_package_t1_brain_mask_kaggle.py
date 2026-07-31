"""Tests for corrected T1 brain-mask Kaggle packaging."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np

from scripts.masks.package_t1_brain_mask_kaggle import (
    ROOT,
    build_package,
    corrected_masks,
)


def save_pair(image_path: Path, mask_path: Path) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    image = np.ones((3, 4, 5), dtype=np.float32)
    mask = np.zeros((3, 4, 5), dtype=np.uint8)
    mask[1:, 1:3, 2:4] = 1
    nib.save(nib.Nifti1Image(image, np.eye(4)), image_path)
    nib.save(nib.Nifti1Image(mask, np.eye(4)), mask_path)


def test_corrected_masks_uses_named_boundary_inclusively(tmp_path):
    mask_dir = tmp_path / "masks"
    image_dir = tmp_path / "images"
    cases = ["C23S1_D1", "C23S2_D7", "C23S3_D1_bis"]
    for index, case_id in enumerate(cases):
        mask = mask_dir / f"{case_id}_pre_manual_mask.nii.gz"
        save_pair(image_dir / f"{case_id}_pre_t1.nii.gz", mask)
        timestamp_ns = (100 + index) * 1_000_000_000
        mask.touch()
        mask.chmod(0o644)
        os.utime(mask, ns=(timestamp_ns, timestamp_ns))

    selected = corrected_masks(
        mask_dir, "C23S2_D7_pre_manual_mask.nii.gz"
    )

    assert [path.name for path in selected] == [
        "C23S2_D7_pre_manual_mask.nii.gz",
        "C23S3_D1_bis_pre_manual_mask.nii.gz",
    ]


def test_build_package_writes_valid_manifest_and_zip(tmp_path):
    mask_dir = tmp_path / "masks"
    image_dir = tmp_path / "images"
    output_dir = tmp_path / "LYS_T1_test"
    first = "C23S2_D7_pre_manual_mask.nii.gz"
    save_pair(
        image_dir / "C23S2_D7_pre_t1.nii.gz",
        mask_dir / first,
    )

    package, archive = build_package(
        mask_dir=mask_dir,
        image_dir=image_dir,
        output_dir=output_dir,
        first_mask_name=first,
        reviewer="Test Reviewer",
        overwrite=False,
    )

    rows = list(csv.DictReader((package / "training_manifest.csv").open()))
    assert archive.is_file()
    assert rows[0]["case_id"] == "C23S2_D7"
    assert rows[0]["animal_id"] == "C23S2"
    assert rows[0]["split"] == "train"
    assert rows[0]["mask_review"] == "approved"
    assert rows[0]["reviewer"] == "Test Reviewer"
    assert len(rows[0]["image_sha256"]) == 64


def test_fold_all_notebook_targets_current_package_and_compiles():
    notebook_path = (
        ROOT / "notebooks/t1_brain_mask_standard3d_fold_all_t4x2_kaggle.ipynb"
    )
    notebook = json.loads(notebook_path.read_text())
    source = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"]
    )
    assert "RUN_CV_250 = False" in source
    assert "RUN_FINAL_ALL_250 = True" in source
    assert "NUM_GPUS = 2" in source
    assert "EXPECTED_APPROVED_CASES = 20" in source
    assert "EXPECTED_ANIMAL_GROUPS = 10" in source
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile(
                "".join(cell["source"]),
                f"t1-fold-all-notebook-cell-{index}",
                "exec",
            )


def test_holdout_notebook_has_sealed_animal_grouped_16_2_2_contract():
    notebook_path = (
        ROOT
        / "notebooks"
        / "t1_brain_mask_standard3d_holdout_16_2_2_t4x2_kaggle.ipynb"
    )
    notebook = json.loads(notebook_path.read_text())
    source = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"]
    )
    assert 'EXPECTED_SPLIT_COUNTS = {"train": 16, "validation": 2, "test": 2}' in source
    assert 'rows["split"] == "validation", "animal_id"]) == {"C24S5"}' in source
    assert 'rows["split"] == "test", "animal_id"]) == {"C25S1"}' in source
    assert 'development = rows.loc[rows["split"] != "test"]' in source
    assert 'splits = [{"train": training_ids, "val": validation_ids}]' in source
    assert '"checkpoint": "checkpoint_best.pth"' in source
    assert '"sealed_test_cases": 2' in source
    assert source.count(
        "LYS_T1_brainmask_holdout_16_2_2_resume.tar.gz"
    ) == 2
    assert "BASE_NUMPY_VERSION" in source
    assert "normalize-kaggle-nifti" in [
        cell["id"] for cell in notebook["cells"]
    ]
    assert 'source.with_suffix("")' in source
    assert "normalized_rows.at[index, hash_column] = sha256(destination)" in source
    cell_ids = [cell["id"] for cell in notebook["cells"]]
    assert cell_ids.index("install") < cell_ids.index("configuration")
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile(
                "".join(cell["source"]),
                f"t1-holdout-notebook-cell-{index}",
                "exec",
            )
