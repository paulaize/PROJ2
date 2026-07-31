#!/usr/bin/env python3
"""Build the T4x2 Kaggle notebook for the currently corrected T1 labels."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from build_t1_nnunet_training_notebook import NOTEBOOK as FULL_PROTOCOL_NOTEBOOK


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "notebooks/t1_brain_mask_standard3d_fold_all_t4x2_kaggle.ipynb"

REMOVED_CELL_IDS = {
    "benchmark-heading",
    "benchmark",
    "cv-heading",
    "cross-validation",
    "oof-heading",
    "oof-evaluation",
}


def source(cell: dict) -> str:
    return "".join(cell["source"])


def set_source(cell: dict, value: str) -> None:
    cell["source"] = value.strip().splitlines(keepends=True)
    if cell["source"]:
        cell["source"][-1] = cell["source"][-1].rstrip("\n")


def build_notebook() -> dict:
    notebook = deepcopy(FULL_PROTOCOL_NOTEBOOK)
    notebook["cells"] = [
        cell
        for cell in notebook["cells"]
        if cell["id"] not in REMOVED_CELL_IDS
    ]
    cells = {cell["id"]: cell for cell in notebook["cells"]}

    set_source(
        cells["overview"],
        """
# LYS pre-Gd T1 brain masking — direct `fold_all` standard 3-D nnU-Net

This Kaggle notebook trains one official standard `PlainConvUNet` on all 20
currently corrected pre-Gd T1 brain masks (10 animal groups). It runs only
`fold_all` for 250 epochs and is configured for Kaggle T4×2 distributed
training.

This direct-training route creates a deployment model but no held-out or
out-of-fold performance estimate. It cannot justify a tuned probability
threshold; the packaged model records the default threshold `0.5`.

Attach one approved training package containing `training_manifest.csv` plus
its relative image and mask paths. Enable **GPU T4 ×2** and Internet. Download
the resume archive before every Kaggle session ends.
""",
    )
    set_source(
        cells["configuration-heading"],
        """
## 1 — Configuration

The execution flags are fixed to train only `fold_all` with two GPUs. Keep
`BUILD_RESUME_ARCHIVE=True` so interrupted Kaggle sessions can continue from
the latest completed epoch.
""",
    )

    configuration = source(cells["configuration"])
    configuration = configuration.replace(
        "RUN_BENCHMARK_5E = True", "RUN_BENCHMARK_5E = False"
    ).replace(
        "RUN_FINAL_ALL_250 = False", "RUN_FINAL_ALL_250 = True"
    ).replace(
        "DEPLOY_DISABLE_TTA = True",
        "DEPLOY_DISABLE_TTA = True\nPROBABILITY_THRESHOLD = 0.5",
    ).replace(
        "EXPECTED_APPROVED_CASES = 34",
        "EXPECTED_APPROVED_CASES = 20",
    ).replace(
        "EXPECTED_ANIMAL_GROUPS = 17",
        "EXPECTED_ANIMAL_GROUPS = 10",
    )
    set_source(cells["configuration"], configuration)

    set_source(
        cells["benchmark-package-heading"],
        """
## 9 — Define compact inference-checkpoint packaging

This helper strips training-only optimizer, scheduler, scaler, and logger
state from the completed `fold_all` checkpoint.
""",
    )
    benchmark_package = source(cells["benchmark-package"])
    set_source(
        cells["benchmark-package"],
        benchmark_package[: benchmark_package.index("if RUN_BENCHMARK_5E:")],
    )

    set_source(
        cells["final-heading"],
        """
## 10 — Train `fold_all` for 250 epochs on all approved labels

There is no validation split in `fold_all`. Its release checkpoint is
`checkpoint_final.pth`. If training is interrupted, build and download the
resume archive below; the next session continues from `checkpoint_latest.pth`.
""",
    )
    final_training = source(cells["final-training"])
    assertion_start = final_training.index(
        '    assert (OOF_ROOT / "oof_summary.json").is_file()'
    )
    assertion_end = final_training.index(
        "    final_record = train_all(", assertion_start
    )
    final_training = (
        final_training[:assertion_start] + final_training[assertion_end:]
    )
    set_source(cells["final-training"], final_training)

    set_source(
        cells["final-package-heading"],
        """
## 11 — Package the single inference-only `fold_all` model

The package records the absence of OOF validation and uses probability
threshold `0.5`. Predictions remain drafts requiring native-grid review.
""",
    )
    final_package = source(cells["final-package"])
    final_package = final_package.replace(
        '        "oof_summary_sha256": sha256(\n'
        '            OOF_ROOT / "oof_summary.json"\n'
        "        ),",
        '        "probability_threshold": PROBABILITY_THRESHOLD,\n'
        '        "threshold_selection": "default_not_tuned",\n'
        '        "oof_validation": False,',
    )
    final_package = final_package.replace(
        '        PROVENANCE / "split_assignments.csv",\n'
        '        OOF_ROOT / "oof_summary.json",\n'
        '        OOF_ROOT / "oof_case_metrics.csv",',
        '        PROVENANCE / "split_assignments.csv",',
    )
    set_source(cells["final-package"], final_package)

    set_source(
        cells["review-heading"],
        """
## 12 — Build review and resume artifacts

Run this after completion and at the end of every interrupted session. The
resume tar retains training checkpoints but excludes source MRI, masks, and
preprocessed arrays.
""",
    )
    set_source(
        cells["interpretation"],
        """
## Interpretation boundary

- `fold_all` uses every approved label and has no held-out validation cases.
- Training-set results are not a generalisation estimate.
- No probability threshold was tuned; the release records default `0.5`.
- Every prediction remains a draft requiring native-grid human review.
- Static pre/post T1-weighted scans do not estimate gadolinium concentration,
  absolute T1, Ktrans, Ki, DCE, or a direct permeability value.
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
