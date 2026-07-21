# Development guide

## Environment

```bash
conda env create -f environment.yml
conda run -n lys-bbb python -m pip install --no-deps -e .
```

Keep raw Bruker data read-only. Generated development data belongs under ignored
`output/`, `derivatives/`, or `reports/` directories.

## Tests and CI

Run the same command used by CI:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen \
  conda run -n lys-bbb python -m pytest tests -q
```

Also run:

```bash
conda run -n lys-bbb ruff check src tests
```

Tests prove software behavior; they do not replace anatomical review or a frozen
raw-data-to-result validation set.

## Primary application commands

```bash
# Launcher
conda run -n lys-bbb lys-bbb-desktop

# Explicitly synthetic design fixture
conda run -n lys-bbb lys-bbb-desktop --demo

# Open a canonical study root
conda run -n lys-bbb lys-bbb-desktop /path/to/study-root
```

The desktop normally owns T2 execution. A backend smoke test accepts inputs arranged as
`<input>/<case-id>/scan.nii.gz` and requires new work/output directories:

```bash
conda run -n lys-bbb python -m lys_bbb.t2_inference_cli \
  --release ~/Downloads/LYS_v1_RatLesNetV2_mac_inference \
  --input /absolute/path/to/inference_input \
  --work /absolute/path/to/new_work \
  --output /absolute/path/to/new_output \
  --device auto
```

`auto` selects MPS, then CUDA, then CPU. The adapter does not train, tune, postprocess,
approve, or calculate an accuracy metric.

## Current source boundaries

| Layer | Location | Responsibility |
|---|---|---|
| Scientific backend | `src/lys_bbb/` | Image discovery, conversion, validation, inference, QC, and measurement; no Qt |
| Domain/application | `src/lys_bbb_app/domain`, `application`, `services` | Typed state and use-case coordination |
| Persistence/adapters | `src/lys_bbb_app/infrastructure` | SQLite, filesystem, recent studies, ITK-SNAP |
| UI | `src/lys_bbb_app/ui` | User choices and presentation only |
| CLIs | `scripts/` and project entry points | Thin development/reproducibility adapters |

Use the dependency direction UI → service → backend/repository. Do not import scientific
modules from widgets or Qt from domain/backend code. `tests/test_app_architecture.py`
enforces this boundary.

Current production state uses `StudyRepository` and feature-specific repositories. The
old `lys_bbb.project_state` and `ProjectService` are frozen schema-v1 migration support;
do not extend them.

The T2 review slice is divided into `lys_bbb.t2_review` for native-grid binary-mask
validation and measurement, `T2ReviewService` for correction/review coordination, a
feature repository for immutable decisions/results, and `t2_export_service` for the
approved-only CSV. Keep new image logic in the backend and new use cases out of widgets.

## Active scientific commands

### T1 refinement and review

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py --help
conda run -n lys-bbb python scripts/brain_extraction/build_rs2_refinement_notebook.py
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py --help
conda run -n lys-bbb python scripts/masks/open_manual_mask_editor.py --help
```

The notebook builder embeds the tested `brain_mask_refinement.py` source. Rebuild and
run notebook-structure tests after changing that algorithm.

### Transitional T1 backend

These commands remain useful for scientific validation but are not the next desktop
milestone:

| Task | Entry point |
|---|---|
| Inventory raw scans | `scripts/inventory/inventory_sessions.py` |
| Convert selected T1 scans | `scripts/conversion/convert_inventory_t1_flash.py` |
| Registration QC | `scripts/qc/qc_pre_post_registration.py` |
| Manual mask worklist | `scripts/masks/build_manual_mask_workflow.py` |
| Candidate-mask validation | `scripts/masks/build_brain_mask_manifest.py` |
| Analysis gate | `scripts/qc/build_analysis_manifest.py` |
| One-pair quantification | `scripts/quantification/quantify_flash_pair.py` |
| Dry-run cohort quantification | `scripts/quantification/quantify_flash_cohort.py` |

Do not interpret cohort outputs biologically until masks, exact registrations, metadata,
normalization, and thresholds pass their documented gates.

## Legacy project compatibility

`.lysbbb` is the frozen single-file schema-v1 prototype. It may be inspected or migrated
through the launcher, but new studies never use it. Migration creates a new study root
and leaves the original file unchanged.

Do not use `ProjectService` in new production code. Its tests exist to guarantee recovery
of old user projects.

## Generated outputs

- Raw data and manual masks are never cleanup targets.
- Automatic, editable, reviewed, approved, superseded, and outdated artifacts are
  separate products.
- Generated paths can be stale after a branch switch.
- New scientific outputs record code/model revisions and checksums.
- `frontend_inspo/` is local design reference material and is ignored by Git.

## Branch workflow

After this consolidation passes tests and CI:

1. open one PR from `feat/pyside-project-foundation` to `main`;
2. preserve the useful commits rather than rebuilding the application elsewhere;
3. merge and delete the long-lived feature branch; and
4. use a narrow branch for the next vertical workflow.

Do not tag, merge, or delete remote branches as part of an unrelated code change.
