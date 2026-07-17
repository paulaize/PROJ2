# LYS BBB MRI

This repository contains the scientific backend for semi-quantitative analysis of
static pre- and post-gadolinium mouse T1-weighted MRI after thrombin/MAC stroke.
It is not yet a production pipeline: conversion and quantification work, but no case
is currently eligible for final biological analysis because T1 brain masks and human
review decisions are incomplete.

The immediate milestone is to benchmark several open-weight mouse/rodent brain
extraction models on the same representative pre-Gd T1 images in Google Colab. The
winning model will become a pre-label generator; human QC remains required.

## What belongs here

```text
Bruker inventory and T1 conversion
        ↓
pre-Gd T1 brain extraction and human review
        ↓
post-Gd → pre-Gd rigid registration and review
        ↓
semi-quantitative enhancement maps and cohort tables
        ↓
later: imported T2 lesion masks, atlas regions, and a desktop application
```

Two boundaries are deliberate:

- The T2w lesion-segmentation model is being developed in another repository. This
  repository will later import its released masks and provenance; it will not contain
  or duplicate that model's training code.
- The final deliverable is a desktop application for non-programmers. The current CLI
  and Python modules are the testable backend that the application will call.

## Current state

As of 2026-07-17:

- 36 raw sessions and 285 scans have been inventoried.
- 35 cases are expected to contain T1 pairs; 34 converted successfully.
- Rigid registration outputs exist for all 34 converted cases, but visual approval is
  still required.
- Eight MouseBrainExtractor pre-labels exist. Seven remain unchanged copies; one was
  edited but has not been explicitly approved.
- The final analysis manifest includes 0 cases: 8 need mask review, 26 lack a brain
  mask, and 1 lacks conversion.
- Study metadata and review decisions are not yet complete.
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

Prepare a model-neutral Colab benchmark package:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --random-count 12
```

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
- Automatic masks, editable masks, reviewed masks, transforms, QC decisions, and final
  tables are separate products.
- Generated files are shared across local branches and can be older than the checked-out
  code. Record the code revision and model version when producing new results.

## Scientific language

The available scans support **semi-quantitative T1-weighted gadolinium enhancement** or
**relative enhancement burden**. They do not support absolute T1, contrast-agent
concentration, `Ktrans`, `Ki`, or quantitative BBB permeability.

The current bias correction and independent pre/post median normalization are
provisional. They must pass signal-preservation experiments before whole-brain or diffuse
enhancement is interpreted biologically.
