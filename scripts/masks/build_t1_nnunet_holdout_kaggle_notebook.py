#!/usr/bin/env python3
"""Build the animal-grouped 16/2/2 T1 brain-mask Kaggle notebook."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from build_t1_nnunet_training_notebook import NOTEBOOK as FULL_NOTEBOOK


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "notebooks/t1_brain_mask_standard3d_holdout_16_2_2_t4x2_kaggle.ipynb"
)
REMOVED_CELL_IDS = {
    "benchmark-heading",
    "benchmark",
    "final-heading",
    "final-training",
}


def source(cell: dict) -> str:
    return "".join(cell["source"])


def set_source(cell: dict, value: str) -> None:
    cell["source"] = value.strip().splitlines(keepends=True)
    if cell["source"]:
        cell["source"][-1] = cell["source"][-1].rstrip("\n")


def build_notebook() -> dict:
    notebook = deepcopy(FULL_NOTEBOOK)
    notebook["cells"] = [
        cell for cell in notebook["cells"] if cell["id"] not in REMOVED_CELL_IDS
    ]
    cells = {cell["id"]: cell for cell in notebook["cells"]}

    set_source(
        cells["overview"],
        """
# LYS pre-Gd T1 brain masking — animal-grouped 16/2/2 holdout

This notebook trains one standard 3-D nnU-Net on 16 corrected scans, selects
`checkpoint_best.pth` using 2 validation scans, and evaluates once on 2 sealed
test scans. Splits are grouped by animal: C24S5 is validation and C25S1 is
test. The other 16 scans are training data.

Attach `LYS_T1_brainmask_manual_holdout_16_2_2_20260731.zip` (or its unpacked
Kaggle dataset), enable **GPU T4 ×2** and Internet, and run all cells. Test
images and labels are excluded from nnU-Net planning, preprocessing, training,
and checkpoint selection.
""",
    )
    set_source(
        cells["configuration-heading"],
        """
## 1 — Configuration

The execution flags run exactly one predefined development split. Keep the
resume archive enabled so a later Kaggle session can continue from the latest
completed epoch.
""",
    )
    configuration = source(cells["configuration"])
    replacements = {
        "RUN_SEED = 20260727": "RUN_SEED = 20260731",
        "DATASET_ID = 502": "DATASET_ID = 503",
        'DATASET_NAME = "Dataset502_LYST1BrainMaskV1"': (
            'DATASET_NAME = "Dataset503_LYST1BrainMaskHoldoutV1"'
        ),
        "RUN_BENCHMARK_5E = True": "RUN_BENCHMARK_5E = False",
        "RUN_CV_250 = False": "RUN_HOLDOUT_250 = True",
        "FOLDS_TO_RUN = [0, 1, 2, 3, 4]": "FOLDS_TO_RUN = [0]",
        "EXPECTED_APPROVED_CASES = 34": "EXPECTED_APPROVED_CASES = 20",
        "EXPECTED_ANIMAL_GROUPS = 17": "EXPECTED_ANIMAL_GROUPS = 10",
        '"cv_250": RUN_CV_250': '"holdout_250": RUN_HOLDOUT_250',
        '"LYS_T1_brainmask_standard3d"': (
            '"LYS_T1_brainmask_standard3d_holdout_16_2_2"'
        ),
    }
    for old, new in replacements.items():
        configuration = configuration.replace(old, new)
    configuration = configuration.replace(
        "SURFACE_TOLERANCE_MM = 0.15",
        "EXPECTED_SPLIT_COUNTS = {\"train\": 16, \"validation\": 2, \"test\": 2}\n"
        "SURFACE_TOLERANCE_MM = 0.15",
    )
    set_source(cells["configuration"], configuration)

    restore_resume = source(cells["restore-resume"]).replace(
        "LYS_T1_brainmask_standard3d_resume.tar.gz",
        "LYS_T1_brainmask_holdout_16_2_2_resume.tar.gz",
    )
    set_source(cells["restore-resume"], restore_resume)

    set_source(
        cells["input-heading"],
        """
## 4 — Locate and validate the split-aware package

The manifest fixes the animal-grouped split. Test rows must be approved but
must have `include_for_nnunet=no`; the notebook still verifies their files and
hashes before keeping them in a separate sealed-test folder.
""",
    )
    validate_input = source(cells["validate-input"])
    validate_input = validate_input.replace(
        '    "animal_id",',
        '    "animal_id",\n    "split",',
    )
    validate_input = validate_input.replace(
        '            "LYS_T1_brainmask_manual_v1.zip"',
        '            "LYS_T1_brainmask_manual_holdout_16_2_2_20260731.zip"',
    )
    start = validate_input.index("include = (")
    end = validate_input.index("geometry_records = []")
    split_validation = """
include = (
    all_rows.include_for_nnunet.astype(str).str.strip().str.lower()
    .isin(TRUE_VALUES)
)
approved = (
    all_rows.mask_review.astype(str).str.strip().str.lower()
    .isin(PASS_VALUES)
)
rows = all_rows.loc[approved].copy().reset_index(drop=True)
rows["split"] = rows["split"].astype(str).str.strip().str.lower()
assert len(rows) == EXPECTED_APPROVED_CASES, (
    len(rows), EXPECTED_APPROVED_CASES
)
assert rows.animal_id.astype(str).str.strip().ne("").all()
assert rows.animal_id.nunique() == EXPECTED_ANIMAL_GROUPS, (
    rows.animal_id.nunique(), EXPECTED_ANIMAL_GROUPS
)
assert rows.reviewer.astype(str).str.strip().ne("").all()
reviewed_times = pd.to_datetime(rows.reviewed_at, utc=True, errors="coerce")
assert reviewed_times.notna().all(), "Missing/invalid reviewed_at"
assert (
    rows.modality.astype(str).str.strip().str.lower() == "t1w"
).all()
assert (
    rows.acquisition_role.astype(str).str.strip().str.lower()
    == "pre_gd"
).all()
assert rows["split"].value_counts().to_dict() == EXPECTED_SPLIT_COUNTS
expected_include = all_rows["split"].astype(str).str.lower() != "test"
assert (include == expected_include).all(), (
    "Only train/validation rows may have include_for_nnunet=yes"
)
animal_split_counts = rows.groupby("animal_id")["split"].nunique()
assert (animal_split_counts == 1).all(), "Animal leakage across splits"
assert set(rows.loc[rows["split"] == "validation", "animal_id"]) == {"C24S5"}
assert set(rows.loc[rows["split"] == "test", "animal_id"]) == {"C25S1"}

"""
    validate_input = (
        validate_input[:start] + split_validation + validate_input[end:]
    )
    validate_input = validate_input.replace(
        '        "animal_id": record["animal_id"],',
        '        "animal_id": record["animal_id"],\n'
        '        "split": record["split"],',
    )
    validate_input = validate_input.replace(
        '"approved_cases": len(rows),',
        '"approved_cases": len(rows),\n'
        '    "split_counts": rows["split"].value_counts().to_dict(),',
    )
    set_source(cells["validate-input"], validate_input)

    set_source(
        cells["materialize-heading"],
        """
## 5 — Materialize only train/validation data and one fixed split

The 18 development scans become nnU-Net `imagesTr`/`labelsTr`. The 2 test
scans remain outside the raw and preprocessed nnU-Net datasets.
""",
    )
    set_source(
        cells["materialize"],
        """
RAW_DATASET = NNUNET_RAW / DATASET_NAME
images_tr = RAW_DATASET / "imagesTr"
labels_tr = RAW_DATASET / "labelsTr"
images_tr.mkdir(parents=True, exist_ok=True)
labels_tr.mkdir(parents=True, exist_ok=True)
SEALED_TEST = WORK / "LYS_T1_sealed_test"
test_images = SEALED_TEST / "images"
test_labels = SEALED_TEST / "labels"
test_images.mkdir(parents=True, exist_ok=True)
test_labels.mkdir(parents=True, exist_ok=True)

mapping_records = []
development = rows.loc[rows["split"] != "test"].sort_values("case_id")
for index, record in enumerate(development.to_dict("records")):
    case_id = str(record["case_id"])
    nnunet_case_id = f"T1BM_{index:03d}"
    source_image, source_mask = verified_paths[case_id]
    output_image = images_tr / f"{nnunet_case_id}_0000.nii.gz"
    output_mask = labels_tr / f"{nnunet_case_id}.nii.gz"
    if not output_image.is_file():
        shutil.copy2(source_image, output_image)
    mask_image = nib.load(str(source_mask))
    binary = (np.asarray(mask_image.dataobj) > 0).astype(np.uint8)
    if not output_mask.is_file():
        header = mask_image.header.copy()
        header.set_data_dtype(np.uint8)
        clean_mask = nib.Nifti1Image(binary, mask_image.affine, header=header)
        qform, qcode = mask_image.get_qform(coded=True)
        sform, scode = mask_image.get_sform(coded=True)
        clean_mask.set_qform(qform, int(qcode))
        clean_mask.set_sform(sform, int(scode))
        nib.save(clean_mask, str(output_mask))
    mapping_records.append({
        "case_id": case_id,
        "nnunet_case_id": nnunet_case_id,
        "animal_id": str(record["animal_id"]),
        "split": str(record["split"]),
        "reviewer": str(record["reviewer"]),
        "reviewed_at": str(record["reviewed_at"]),
        "source_image_sha256": str(record["image_sha256"]).lower(),
        "source_mask_sha256": str(record["mask_sha256"]).lower(),
    })

test_mapping_records = []
test_rows = rows.loc[rows["split"] == "test"].sort_values("case_id")
for index, record in enumerate(test_rows.to_dict("records")):
    case_id = str(record["case_id"])
    test_id = f"T1TEST_{index:03d}"
    source_image, source_mask = verified_paths[case_id]
    destination_image = test_images / f"{test_id}_0000.nii.gz"
    destination_mask = test_labels / f"{test_id}.nii.gz"
    if not destination_image.is_file():
        shutil.copy2(source_image, destination_image)
    if not destination_mask.is_file():
        shutil.copy2(source_mask, destination_mask)
    test_mapping_records.append({
        "case_id": case_id,
        "nnunet_case_id": test_id,
        "animal_id": str(record["animal_id"]),
        "split": "test",
        "source_image_sha256": str(record["image_sha256"]).lower(),
        "source_mask_sha256": str(record["mask_sha256"]).lower(),
    })

dataset_json = {
    "channel_names": {"0": "pre-Gd T1w"},
    "labels": {"background": 0, "brain": 1},
    "numTraining": len(mapping_records),
    "file_ending": ".nii.gz",
}
(RAW_DATASET / "dataset.json").write_text(
    json.dumps(dataset_json, indent=2, sort_keys=True) + "\\n"
)
mapping = pd.DataFrame(mapping_records)
test_mapping = pd.DataFrame(test_mapping_records)
mapping.to_csv(RAW_DATASET / "case_mapping.csv", index=False)
test_mapping.to_csv(PROVENANCE / "test_case_mapping.csv", index=False)

training_ids = sorted(
    mapping.loc[mapping["split"] == "train", "nnunet_case_id"]
)
validation_ids = sorted(
    mapping.loc[mapping["split"] == "validation", "nnunet_case_id"]
)
assert len(training_ids) == 16 and len(validation_ids) == 2
assert set(training_ids).isdisjoint(validation_ids)
splits = [{"train": training_ids, "val": validation_ids}]
(RAW_DATASET / "splits_final.json").write_text(
    json.dumps(splits, indent=2, sort_keys=True) + "\\n"
)
split_assignments = pd.concat([mapping, test_mapping], ignore_index=True)
assert split_assignments["split"].value_counts().to_dict() == (
    EXPECTED_SPLIT_COUNTS
)
assert (
    split_assignments.groupby("animal_id")["split"].nunique() == 1
).all()
split_assignments.to_csv(
    PROVENANCE / "split_assignments.csv", index=False
)
for name in ("case_mapping.csv", "dataset.json", "splits_final.json"):
    shutil.copy2(RAW_DATASET / name, PROVENANCE / name)
display(
    split_assignments.groupby("split").agg(
        cases=("case_id", "count"),
        animals=("animal_id", "nunique"),
    )
)
""",
    )

    plan = source(cells["plan-preprocess"]).replace(
        '"protocol": "lys_t1_brainmask_standard3d_v1"',
        '"protocol": "lys_t1_brainmask_standard3d_holdout_16_2_2_v1"',
    )
    plan = plan.replace(
        '"approved_case_count": len(rows),',
        '"approved_case_count": len(rows),\n'
        '    "development_case_count": len(mapping),\n'
        '    "sealed_test_case_count": len(test_mapping),',
    )
    set_source(cells["plan-preprocess"], plan)

    set_source(
        cells["cv-heading"],
        """
## 10 — Train the single 16/2 development split

Only fold 0 exists: 16 training scans and 2 validation scans. The best
checkpoint is selected from validation performance; test data remain sealed.
""",
    )
    set_source(
        cells["cross-validation"],
        """
holdout_record = None
if RUN_HOLDOUT_250:
    holdout_record = train_and_validate(
        CV_TRAINER,
        0,
        RUNS / "holdout_250/fold_0/complete.json",
    )
    display(holdout_record)
else:
    print("Holdout training disabled.")
""",
    )

    set_source(
        cells["oof-heading"],
        """
## 11 — Validation and sealed-test evaluation

The selected validation checkpoint predicts the test images only after
training is complete. Metrics are reported per case and pooled; the two test
scans belong to one animal and therefore represent one independent test unit.
""",
    )
    oof = source(cells["oof-evaluation"])
    metric_start = oof.index("def case_metrics")
    metric_end = oof.index("if RUN_CV_250")
    metric_helpers = oof[metric_start:metric_end]
    evaluation = """
EVALUATION_ROOT = EXPERIMENT_ROOT / "holdout_evaluation"

def predict_cases(
    input_folder: Path,
    output_folder: Path,
    expected: set[str],
    disable_tta: bool,
) -> Path:
    observed = {
        path.name.removesuffix(".nii.gz")
        for path in output_folder.glob("*.nii.gz")
    }
    if observed != expected:
        command = [
            "nnUNetv2_predict_from_modelfolder",
            "-i", str(input_folder),
            "-o", str(output_folder),
            "-m", str(model_root(CV_TRAINER)),
            "-f", "0",
            "-chk", "checkpoint_best.pth",
            "-device", "cuda",
            "-npp", "2",
            "-nps", "2",
        ]
        if disable_tta:
            command.append("--disable_tta")
        subprocess.run(command, check=True)
    observed = {
        path.name.removesuffix(".nii.gz")
        for path in output_folder.glob("*.nii.gz")
    }
    assert observed == expected, (observed, expected)
    return output_folder

""" + metric_helpers + """
if RUN_HOLDOUT_250 and (
    RUNS / "holdout_250/fold_0/complete.json"
).is_file():
    metric_records = []
    mapping_by_id = mapping.set_index("nnunet_case_id")
    validation_folder = model_folder(CV_TRAINER, 0) / "validation"
    for nnunet_case_id in expected_validation_ids(0):
        identity_row = mapping_by_id.loc[nnunet_case_id]
        metric_records.append({
            "case_id": identity_row.case_id,
            "animal_id": identity_row.animal_id,
            "nnunet_case_id": nnunet_case_id,
            "split": "validation",
            "inference_policy": "default_tta",
            **case_metrics(
                labels_tr / f"{nnunet_case_id}.nii.gz",
                validation_folder / f"{nnunet_case_id}.nii.gz",
            ),
        })

    expected_test = set(test_mapping.nnunet_case_id)
    for policy, disable_tta in (
        ("default_tta", False),
        ("no_tta", True),
    ):
        prediction_folder = predict_cases(
            test_images,
            EVALUATION_ROOT / f"test_{policy}",
            expected_test,
            disable_tta,
        )
        for record in test_mapping.to_dict("records"):
            nnunet_case_id = record["nnunet_case_id"]
            metric_records.append({
                **record,
                "inference_policy": policy,
                **case_metrics(
                    test_labels / f"{nnunet_case_id}.nii.gz",
                    prediction_folder / f"{nnunet_case_id}.nii.gz",
                ),
            })

    holdout_metrics = pd.DataFrame(metric_records)
    holdout_metrics.to_csv(
        EVALUATION_ROOT / "holdout_case_metrics.csv", index=False
    )
    summaries = {
        f"{split}_{policy}": summarize_metrics(part)
        for (split, policy), part in holdout_metrics.groupby(
            ["split", "inference_policy"]
        )
    }
    (EVALUATION_ROOT / "holdout_summary.json").write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\\n"
    )
    display(summaries)
else:
    print("Evaluation waits for completed holdout training.")
"""
    set_source(cells["oof-evaluation"], evaluation)

    set_source(
        cells["benchmark-package-heading"],
        """
## 9 — Define inference-only checkpoint packaging

This helper removes optimizer, scheduler, scaler, and logger state from the
selected checkpoint without changing network weights.
""",
    )
    package_helper = source(cells["benchmark-package"])
    set_source(
        cells["benchmark-package"],
        package_helper[: package_helper.index("if RUN_BENCHMARK_5E:")],
    )

    set_source(
        cells["final-package-heading"],
        """
## 12 — Package the evaluated validation-selected model

The release contains one fold-0 `checkpoint_best.pth` plus the fixed split and
validation/test metrics. Predictions remain drafts requiring native-grid
review.
""",
    )
    set_source(
        cells["final-package"],
        """
if RUN_HOLDOUT_250 and (
    EVALUATION_ROOT / "holdout_summary.json"
).is_file():
    release_parent = WORK / "holdout_inference_release"
    release_name = (
        "nnUNetTrainer_250epochs__nnUNetPlans__3d_fullres"
    )
    release_root = release_parent / release_name
    if release_parent.exists():
        shutil.rmtree(release_parent)
    release_root.mkdir(parents=True)
    source_root = model_root(CV_TRAINER)
    shutil.copy2(source_root / "plans.json", release_root / "plans.json")
    shutil.copy2(
        source_root / "dataset.json", release_root / "dataset.json"
    )
    release_checkpoint_record = portable_checkpoint(
        source_root / "fold_0/checkpoint_best.pth",
        release_root / "fold_0/checkpoint_best.pth",
        "nnUNetTrainer_250epochs",
    )
    release_manifest = {
        **release_checkpoint_record,
        "fold": 0,
        "checkpoint": "checkpoint_best.pth",
        "model_count": 1,
        "training_cases": 16,
        "validation_cases": 2,
        "sealed_test_cases": 2,
        "test_independent_animals": 1,
        "disable_tta": DEPLOY_DISABLE_TTA,
        "postprocessing": "none",
        "predictions_are_drafts": True,
        "parameter_count": plan_summary["parameter_count"],
        "training_manifest_sha256": sha256(TRAINING_MANIFEST),
        "holdout_summary_sha256": sha256(
            EVALUATION_ROOT / "holdout_summary.json"
        ),
    }
    (release_root / "release_manifest.json").write_text(
        json.dumps(release_manifest, indent=2, sort_keys=True) + "\\n"
    )
    for path in (
        PROVENANCE / "protocol_identity.json",
        PROVENANCE / "plan_summary.json",
        PROVENANCE / "split_assignments.csv",
        EVALUATION_ROOT / "holdout_summary.json",
        EVALUATION_ROOT / "holdout_case_metrics.csv",
    ):
        destination = release_root / "provenance" / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    release_zip = (
        WORK / "LYS_T1_brainmask_standard3d_holdout_inference.zip"
    )
    with zipfile.ZipFile(
        release_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in sorted(release_parent.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(release_parent))
    print(
        "Holdout inference release:",
        release_zip,
        f"{release_zip.stat().st_size / 1024**2:.1f} MiB",
    )
    display(FileLink(str(release_zip)))
""",
    )

    review = source(cells["review-resume"]).replace(
        "LYS_T1_brainmask_standard3d_review.zip",
        "LYS_T1_brainmask_holdout_16_2_2_review.zip",
    ).replace(
        "LYS_T1_brainmask_standard3d_resume.tar.gz",
        "LYS_T1_brainmask_holdout_16_2_2_resume.tar.gz",
    )
    set_source(
        cells["review-heading"],
        """
## 13 — Build review and resume artifacts

The review ZIP excludes MRI arrays. The resume archive retains training
checkpoints but excludes uploaded source images and masks.
""",
    )
    set_source(cells["review-resume"], review)
    set_source(
        cells["interpretation"],
        """
## Interpretation boundary

- Splits are animal-grouped: 16 scans train, 2 validate, and 2 test.
- The validation scans select `checkpoint_best.pth`.
- Test data are excluded from planning, preprocessing, training, and model
  selection and are evaluated only after training completes.
- Both test scans belong to one animal, so test uncertainty remains high.
- Every prediction is a draft requiring native-grid human review.
- Static pre/post T1 scans do not estimate gadolinium concentration, absolute
  T1, Ktrans, Ki, DCE, or a direct permeability value.
""",
    )
    notebook["metadata"]["kaggle"]["accelerator"] = "gpu"
    return notebook


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(build_notebook(), indent=1, ensure_ascii=False) + "\n"
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
