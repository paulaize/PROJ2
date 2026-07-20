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

Launch the study launcher, open the explicitly synthetic design preview, pass a
schema-v4 study root directly, or inspect a legacy schema-v1 project:

```bash
conda run -n lys-bbb lys-bbb-desktop
conda run -n lys-bbb lys-bbb-desktop --demo
conda run -n lys-bbb lys-bbb-desktop /path/to/study-root
conda run -n lys-bbb lys-bbb-desktop /path/to/study.lysbbb
```

The preview is implemented in `src/lys_bbb_app/` and remains the place to evaluate
the persistent shell, page layout, navigation, status semantics, review interaction,
and results presentation. Its typed demo records are not persisted.

Outside demo mode, the application now creates/reopens a schema-v4 study root, scans a
selected MRI root read-only, proposes Bruker/NIfTI subject and role assignments, converts
confirmed inputs to versioned NIfTI artifacts, and persists geometry, hashes,
orientation operations, subjects, expected workflows, recent studies, audit events, and
blinding. Schema-v2 roots migrate automatically; the schema-v1 `.lysbbb` file remains a
non-destructive explicit migration input. Persistence, discovery, and conversion live in
non-Qt repositories and services.

Keep the MRI import feature split across these boundaries:

| Layer | Module | Responsibility |
|---|---|---|
| Scientific backend | `lys_bbb.scan_discovery`, `lys_bbb.scan_conversion`, `lys_bbb.image_orientation` | Read-only discovery, conversion, and image geometry; no Qt or study database access |
| Domain contracts | `lys_bbb_app.domain.scan_import` | Immutable requests, states, records, and reports; no Qt or I/O |
| Application service | `lys_bbb_app.services.study_service` | Validate and coordinate the import use case |
| Persistence | `lys_bbb_app.infrastructure.scan_input_repository` | Store versioned scan inputs and provenance behind a small database-context protocol |
| Background bridge | `lys_bbb_app.infrastructure.scan_import_worker` | Carry service work and structured outcomes across the Qt thread boundary |
| User interface | `lys_bbb_app.ui.scan_import_dialog`, `lys_bbb_app.ui.main_window` | Collect explicit user choices and refresh views; no scientific processing |

Shared SQLite mechanics belong in `infrastructure.database_support`; schema creation and
migrations belong in `infrastructure.study_schema`. Repositories must not import each
other bidirectionally. New workflows should follow the same dependency direction:
UI → service → backend/repository, with domain contracts shared between layers.

New MVP studies use a study root:

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

The current slice migrates a legacy `.lysbbb` file without modifying it and connects MRI
discovery/conversion. Bruker sources are identified from numeric scan folders containing
`acqp` and `method`; T1 FLASH and high-resolution T2 RARE are proposals only until the
user confirms the import table. Conversion runs through application/scientific services
off the GUI thread. The next state milestone adds the general artifact/job/review/result
model, process-level cancellation/recovery, and post-conversion image QC.

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
