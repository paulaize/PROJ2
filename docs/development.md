# Development guide

## Environment

```bash
conda env create -f environment.yml
conda run -n lys-irm python -m pip install --no-deps -e .
conda run -n lys-irm python -c "import ants; assert ants.__version__ == '0.6.3'"
```

ANTsPyx 0.6.3 and SciPy 1.15.2 are the canonical scientific runtime versions on macOS
and Windows. The exact SciPy pin matches the conda-forge packages available to the
native Windows environment and keeps local development on the same numerical stack.
Do not add standalone ANTs command-line dependencies or platform-specific registration
methods. Changing the ANTsPyx version requires a deliberate
method-version/provenance review.

Keep raw Bruker data read-only. Generated development data belongs under ignored
`output/`, `derivatives/`, or `reports/` directories.

## Tests and CI

Run the same command used by CI:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen \
  conda run -n lys-irm python -m pytest tests -q
```

Also run:

```bash
conda run -n lys-irm ruff check src scripts tests
```

Tests prove software behavior; they do not replace anatomical review or a frozen
raw-data-to-result validation set.

CI runs the full suite on Linux and a dedicated Python 3.11 Windows job that installs
the real ANTsPyx wheel and exercises the backend, architecture, and desktop smoke tests.
Treat a failing Windows job as a release blocker even when development is performed on
macOS.

## Primary application commands

```bash
# Launcher
conda run -n lys-irm lys-irm-desktop

# Open a canonical study root
conda run -n lys-irm lys-irm-desktop /path/to/study-root
```

The desktop normally owns T2 execution. A backend smoke test accepts inputs arranged as
`<input>/<case-id>/scan.nii.gz` and requires new work/output directories:

```bash
conda run -n lys-irm python -m lys_bbb.t2_inference_cli \
  --release ~/Downloads/LYS_v1_RatLesNetV2_mac_inference \
  --input /absolute/path/to/inference_input \
  --work /absolute/path/to/new_work \
  --output /absolute/path/to/new_output \
  --device auto
```

`auto` selects MPS, then CUDA, then CPU. The adapter does not train, tune, postprocess,
approve, or calculate an accuracy metric.

## Current source boundaries

The product and Python distribution are named **LYS IRM** (`lys-irm`). The established
`lys_bbb` and `lys_bbb_app` Python import namespaces remain stable implementation
contracts so existing studies, frozen workers, and research adapters do not require a
risky API migration.

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

Current production state uses `StudyRepository` and feature-specific repositories.

The T2 review slice is divided into `lys_bbb.t2_review` for native-grid binary-mask
validation and measurement, `T2ReviewService` for managed correction/approval
coordination, a feature repository for immutable approvals/results, and
`t2_export_service` for the
approved-only CSV. Keep new image logic in the backend and new use cases out of widgets.

## Active scientific commands

### T1 refinement and review

```bash
conda run -n lys-irm python scripts/brain_extraction/prepare_colab_package.py --help
conda run -n lys-irm python scripts/brain_extraction/build_rs2_refinement_notebook.py
conda run -n lys-irm python scripts/brain_extraction/review_colab_results.py --help
conda run -n lys-irm lys-irm-t1-mask-setup --help
conda run -n lys-irm lys-irm-t1-mask --help
conda run -n lys-irm python scripts/masks/open_manual_mask_editor.py --help
```

The notebook builder embeds the tested `brain_mask_refinement.py` source. Rebuild and
run notebook-structure tests after changing that algorithm.

The local setup command downloads and validates the exact RS2 source and model used by
the frozen Colab run. The mask command accepts one native pre-Gd T1, refuses to overwrite
an output directory, and preserves raw RS2, refined draft, diagnostics, QC, checksums,
and provenance separately. These are automatic drafts, never approvals.

The desktop uses the default local release at:

```text
~/Library/Application Support/LYS IRM/models/rs2net-m-seam-v1
```

After importing and validating the native pre-Gd T1, open the subject's `T1 Brain Mask`
tab and choose `Generate draft`. Generation runs off the GUI thread using the explicit
no-TTA low-impact draft method. A successful draft appears in the study-level `Reviews`
queue, where it can be approved or corrected through a managed ITK-SNAP copy. The
application records the exact release, no-TTA method-spec hash, source input, mask
checksums, run state, immutable versions, reviewer, approval time, and blinding state.

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
