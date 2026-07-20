# Development guide

## Environment and tests

Use the `lys-bbb` environment and keep raw Bruker data read-only.

```bash
conda env create -f environment.yml
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

Reusable scientific code belongs in `src/lys_bbb/`; all Qt application code belongs in
`src/lys_bbb_app/`. `scripts/` contains stage-oriented CLIs and thin external-model
adapters. Generated development outputs belong under ignored `output/`, `derivatives/`,
or `reports/` directories.

## Active entry points

| Task | Command |
|---|---|
| Inventory raw scans | `scripts/inventory/inventory_sessions.py` |
| Convert inventory-selected T1 pairs | `scripts/conversion/convert_inventory_t1_flash.py` |
| Convert selected raw session folders | `scripts/conversion/convert_bruker_t1_flash.py` |
| Package Colab benchmark inputs | `scripts/brain_extraction/prepare_colab_package.py` |
| Run benchmark in Colab | `notebooks/brain_extraction_colab_benchmark.ipynb` |
| Run optional control models in Colab | `notebooks/brain_extraction_colab_extra_baselines.ipynb` |
| Compare T1-guided RS2 corrections in Colab | `notebooks/brain_extraction_rs2_refinement_colab.ipynb` |
| Compare downloaded model masks | `scripts/brain_extraction/review_colab_results.py` |
| Run current MBE adapter | `scripts/brain_extraction/mbe/run_one.py` or `run_batch.py` |
| Registration QC | `scripts/qc/qc_pre_post_registration.py` |
| Edit a selected mask in ITK-SNAP | `scripts/masks/open_manual_mask_editor.py` |
| Build manual review dashboard | `scripts/masks/build_manual_mask_workflow.py` |
| Clean candidate masks | `scripts/masks/postprocess_brain_masks.py` |
| Validate candidate masks | `scripts/masks/build_brain_mask_manifest.py` |
| Build analysis gate | `scripts/qc/build_analysis_manifest.py` |
| Build study metadata | `scripts/qc/build_study_metadata.py` |
| Build readiness report | `scripts/qc/build_project_status.py` |
| Quantify one pair | `scripts/quantification/quantify_flash_pair.py` |
| Quantify a gated cohort | `scripts/quantification/quantify_flash_cohort.py` |
| Launch desktop application | `lys-bbb-desktop [project.lysbbb]` |
| Launch connected design preview | `lys-bbb-desktop --demo` |

Use `python <script> --help` for the complete option set. Documentation should explain
workflow decisions, not copy every CLI flag.

## Conversion

The inventory-driven converter writes only the quantitative files needed downstream:

```text
output/all_mice/<case_id>/pre_coronal.nii.gz
output/all_mice/<case_id>/post_coronal.nii.gz
output/all_mice/<case_id>/source_metadata.json
```

The raw-session converter can additionally write QC and display files. Fiji display
NIfTI is opt-in:

```bash
conda run -n lys-bbb python scripts/conversion/convert_bruker_t1_flash.py \
  /path/to/raw/session \
  -o output/selected \
  --write-fiji-display
```

Never use a Fiji-oriented or moving-slab image for quantification.

## Mask and review workflow

After predictions have been imported to a model-specific folder:

```bash
conda run -n lys-bbb python scripts/qc/build_qc_manifest.py \
  --input-root output/all_mice \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv

conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --out-dir reports/qc \
  --manual-dir derivatives/brain_seg/manual
```

Use `mask_review` and `registration_review` values `pass`, `review`, or `fail`. Rebuilds
preserve these fields. A legacy `_done` filename is not sufficient without review pass.

Candidate predictions should be postprocessed and validated before analysis gating:

```bash
conda run -n lys-bbb python scripts/masks/postprocess_brain_masks.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/model_predictions \
  -o derivatives/brain_seg/model_predictions_cleaned

conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/model_predictions_cleaned \
  --mask-source MODEL_VERSION
```

## Analysis gate and provisional cohort

Merge study metadata and QC into the generated handoff:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --metadata-manifest derivatives/manifests/study_metadata.csv \
  -o derivatives/manifests/analysis_manifest.csv \
  --summary reports/qc/analysis_manifest_summary.csv
```

Always dry-run before a cohort execution:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  --roi-manifest derivatives/manifests/analysis_manifest.csv \
  -o derivatives/quantification/flash_cohort \
  --dry-run
```

Current cohort outputs remain method-development products until masks, registrations,
metadata, normalization, and thresholds are validated.

## Desktop project foundation and next phase

`environment.yml` installs the repository in editable mode and includes PySide6. For an
existing environment created before the desktop milestone, refresh the install with:

```bash
conda install -n lys-bbb pyside6
conda run -n lys-bbb python -m pip install --no-deps -e .
```

Launch the study launcher, open the explicitly synthetic design preview, or pass an
existing schema-v1 project directly:

```bash
conda run -n lys-bbb lys-bbb-desktop
conda run -n lys-bbb lys-bbb-desktop --demo
conda run -n lys-bbb lys-bbb-desktop /path/to/study.lysbbb
```

The preview is implemented in `src/lys_bbb_app/` and is the current place to evaluate
the persistent shell, page layout, navigation, status semantics, review interaction,
and results presentation. Its typed demo records are not persisted. Opening a real
schema-v1 project shows an empty real-study state rather than injecting preview subjects.

The schema-v1 `.lysbbb` file stores only project identity and absolute T1/T2w folder
paths. It does not copy source images or run scientific stages. Persistence and folder
validation live in non-Qt modules.

New MVP studies will use a study root:

```text
study-root/
├── project.sqlite
├── project.json
├── imports/
├── work/
├── outputs/
├── reports/
├── exports/
└── logs/
```

Phase 1 must migrate a legacy `.lysbbb` file without modifying it, add subjects and
expected T1/T2 workflows, create the persistent shell/Overview/Subjects screens,
record audit events, and restore the same state after reopening. It must not connect
scientific processing yet.

Application tests should progressively use `pytest-qt`. Domain and service tests must
remain runnable without showing a window; scientific backend tests remain responsible
for geometry and measurement behavior.

## Sibling backend integration

The local `~/Documents/LYS_PROJ1` checkout owns T2 model development. It is useful for
inspecting the upstream release contract during development, but it is never a
production import path for this application.

Integrate an upstream backend only after `LYS_PROJ1` produces an immutable release with
an ID/version, source revision, checksums, declared inputs/outputs, structured errors,
completion manifest, method status, and validation provenance. Install or copy that
release through an explicit application service and record it in `model_releases` or
`methods`. Do not modify `LYS_PROJ1`, add it to `PYTHONPATH`, invoke whatever branch
happens to be checked out, or infer success from output files alone.

## Branches and generated outputs

Start new work from the consolidated latest tip. Use short-lived branches and do not
revive the old linear feature checkpoints as independent code lines.

Ignored outputs are not reset by branch switching. Before trusting a generated report,
record or inspect the generating code revision, timestamp, inputs, and model version.
Preserve manual masks and review decisions when refreshing reports.
