# LYS BBB MRI

This repository contains the scientific backend and emerging desktop application for
subject-centred mouse T1 enhancement and T2 lesion quantification workflows. It is not
yet a production pipeline: parts of the T1 backend work, but no current case is eligible
for final biological analysis, and the T2 desktop workflow is not yet implemented.

Scientific validation currently focuses on selecting and reviewing the T1 brain-mask
pre-label generator and validating enhancement signal preservation. Desktop development
now focuses on a study/subject/artifact model that will expose approved T1 and T2
workflows to non-technical users without moving scientific logic into Qt widgets.

## What belongs here

```text
Study
└── Subject
    ├── T1: pre/post import → brain-mask review → registration review → enhancement
    ├── T2: scan + released draft mask → review → native-space lesion volume
    └── Combined MRI results with explicit approval, method, and missingness states
```

Two boundaries are deliberate:

- The sibling `~/Documents/LYS_PROJ1` repository owns T2 lesion-model development. This
  repository integrates its immutable, checksummed releases; it does not run from that
  live checkout or duplicate model-development code.
- The final deliverable is a desktop application for non-programmers. Qt pages call
  typed services, which call the independently tested scientific backend.

## Current state

As of 2026-07-20:

- 36 raw sessions and 285 scans have been inventoried.
- 35 cases are expected to contain T1 pairs; 34 converted successfully.
- Rigid registration outputs exist for all 34 converted cases, but visual approval is
  still required.
- Eight MouseBrainExtractor pre-labels exist. Seven remain unchanged copies; one was
  edited but has not been explicitly approved.
- The final analysis manifest includes 0 cases: 8 need mask review, 26 lack a brain
  mask, and 1 lacks conversion.
- Study metadata and review decisions are not yet complete.
- The PySide6 application now creates and reopens schema-v3 study directories, scans
  external-drive Bruker/NIfTI folders read-only, lets the user correct discovered
  subjects, T1-pre/T1-post/T2 roles and storage-axis operations, converts confirmed
  inputs to versioned NIfTI/provenance artifacts, and persists blinding/group/audit
  state. The synthetic design preview remains available for downstream workflow pages;
  general artifact/job/review/result persistence and T2 model execution are not yet
  implemented.
- The test suite passes, but biological validation is not complete.

See [current state](docs/current_state.md) for the exact cases, branch history, and
known blockers.

## Documentation map

Each topic has one authoritative document:

| Question | Document |
|---|---|
| What works and what is blocked? | [Current state](docs/current_state.md) |
| How do the pipeline stages fit together? | [Pipeline architecture](docs/pipeline_architecture.md) |
| How will T1 brain-extraction models be compared? | [Brain extraction](docs/brain_extraction.md) |
| What do the enhancement values mean? | [Enhancement quantification](docs/enhancement_quantification.md) |
| How will the external T2 lesion model connect? | [T2 lesion integration](docs/t2_lesion_integration.md) |
| What is the non-programmer end product? | [Desktop application](docs/desktop_application.md) |
| How do developers run the current tools? | [Development guide](docs/development.md) |

`AGENT.md` is a compact operating brief for coding agents. It does not duplicate the
method documents.

## Setup

Raw Bruker data remain outside the repository and must never be modified:

```text
/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P
```

Use the `lys-bbb` conda environment. A minimal reproducible definition is provided in
`environment.yml`:

```bash
conda env create -f environment.yml
conda activate lys-bbb
```

Existing environments can run commands without activation:

```bash
conda run -n lys-bbb python ...
```

## Desktop application preview

Open the application launcher:

```bash
conda run -n lys-bbb lys-bbb-desktop
```

Open the connected visual preview immediately:

```bash
conda run -n lys-bbb lys-bbb-desktop --demo
```

The preview has representative T1 and T2 states and connected navigation. Every
preview subject, image, review, and result is visibly labelled synthetic and is never
written to project state. It is intended for discussing layout, terminology, and user
flow while scientific backends and durable study state are developed. Settings includes
a blinded-review preview: groups can be hidden during review and deferred until an
explicit later unblinding/group-assignment step.

Create or open a persistent study directory from the launcher. Reopen one directly with:

```bash
conda run -n lys-bbb lys-bbb-desktop /path/to/study-root
```

Images stay in their source folders, including mounted hard drives; project setup neither
copies nor modifies them. New studies contain `project.sqlite`, `project.json`, imports,
workspaces, outputs, reports, exports, and logs. Existing `.lysbbb` projects remain
readable and can be migrated without modifying the original file. The application can
persist real subject identities and setup state, but it does not yet import subject MRI
files or execute scientific pipeline stages.

The target screens and implementation phases are defined in
[Desktop application MVP](docs/desktop_application.md).

## Core commands

Inventory the raw sessions:

```bash
conda run -n lys-bbb python scripts/inventory/inventory_sessions.py \
  /Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P \
  -o reports/inventory
```

Convert inventory-selected pre/post T1 scans:

```bash
conda run -n lys-bbb python scripts/conversion/convert_inventory_t1_flash.py \
  --inventory reports/inventory/scan_inventory.csv \
  --out-root output/all_mice
```

The first ten-image Colab benchmark package has been prepared locally at
`derivatives/brain_extraction/colab/t1_brain_extraction_benchmark_10.zip`. Rebuild the
same frozen cohort with:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --case-file config/brain_extraction_benchmark_10.txt \
  --package-name t1_brain_extraction_benchmark_10 \
  --overwrite
```

Upload [`notebooks/brain_extraction_colab_benchmark.ipynb`](notebooks/brain_extraction_colab_benchmark.ipynb)
to Google Colab, choose a T4 GPU, run all cells, and upload the prepared archive when
prompted. After Colab downloads `t1_brain_extraction_results.zip`, compare every mask
with its T1 in ITK-SNAP:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip
```

The primary notebook has now run successfully on the 10 frozen images. To add two
optional diagnostic controls without disturbing it, run
[`notebooks/brain_extraction_colab_extra_baselines.ipynb`](notebooks/brain_extraction_colab_extra_baselines.ipynb)
in a fresh T4 runtime with the same upload archive. It produces
`t1_brain_extraction_extra_results.zip`. Compare the primary and extra masks together:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip \
  ~/Downloads/t1_brain_extraction_extra_results.zip
```

The extras are a rodent T2/T2* cross-contrast control and a human-T1 cross-species
control. They are not presented as mouse-T1-validated replacements for MBE or RS2-Net.

Visual inspection found RS2-Net to be the strongest current pre-label, with a recurring
superior skull-cap false positive separated from cortex by a dark M-shaped T1 boundary.
To test three image-guided corrections without changing the successful primary run, use
[`notebooks/brain_extraction_rs2_refinement_colab.ipynb`](notebooks/brain_extraction_rs2_refinement_colab.ipynb)
in a fresh T4 runtime and upload the same frozen archive. It produces untouched RS2,
direct M-seam, marker-watershed, and random-walker masks plus interactive and saved QC.
After downloading the result, compare all four candidates in ITK-SNAP:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_rs2_refinement_results.zip
```

These corrections are experimental automatic pre-labels. The notebook never adds mask
voxels, falls back to raw RS2 when its dark-gap gate is not satisfied, and does not
approve or select a corrected mask automatically.

Build the compact technical readiness report:

```bash
conda run -n lys-bbb python scripts/qc/build_project_status.py
```

Run tests:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The development guide contains the mask-review and provisional quantification
commands. Do not run cohort quantification as a biological analysis until the analysis
manifest contains reviewed cases.

## Output policy

- `output/`, `derivatives/`, and generated content under `reports/` are ignored.
- Raw images and immutable automatic predictions must not be overwritten.
- Quantitative work uses native `*_coronal.nii.gz` images.
- Fiji-oriented NIfTI files and slab volumes are optional display products only.
- Automatic masks, editable masks, reviewed masks, transforms, QC decisions, and
  approved/provisional result tables are separate products.
- Generated files are shared across local branches and can be older than the checked-out
  code. Record the code revision and model version when producing new results.

## Scientific language

The available scans support **semi-quantitative T1-weighted gadolinium enhancement** or
**relative enhancement burden**. They do not support absolute T1, contrast-agent
concentration, `Ktrans`, `Ki`, or quantitative BBB permeability.

The current bias correction and independent pre/post median normalization are
provisional. They must pass signal-preservation experiments before whole-brain or diffuse
enhancement is interpreted biologically.
