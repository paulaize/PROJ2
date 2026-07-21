# LYS BBB MRI

LYS BBB is a subject-centred desktop application and scientific backend for mouse MRI.
It owns two workflows:

```text
T1: pre/post import → brain-mask review → registration review → enhancement
T2: native T2 → frozen-model draft mask → human review → lesion volume
```

The repository is a substantial development checkpoint, not a finished scientific
product. Study creation, MRI import, input validation, orientation correction, audit
history, frozen T2 inference, and persistent draft T2 outputs work. No workflow yet
produces a human-approved result from inside the application.

## Immediate goal

Development is frozen horizontally. The next milestone is one complete T2 vertical
slice:

> Import and validate T2, run the frozen model, review or replace the draft mask,
> approve it, calculate an official native-space lesion volume, export one CSV, and
> recover the same approved state after reopening the study.

Do not add pages, modalities, models, atlas features, or general-purpose framework code
until this user story passes its tests.

## Repository ownership

```text
LYS_PROJ1
  T2 model training, validation, checkpoint selection, and frozen releases

LYS_PROJ2
  Scientific execution backend and desktop application
  Import, review, approval, results, provenance, and exports
```

Within this repository:

```text
src/lys_bbb/       Qt-free scientific backend
src/lys_bbb_app/   desktop domain, services, persistence, and PySide6 UI
```

Production code never imports the live `~/Documents/LYS_PROJ1` checkout. It accepts only
an immutable checksummed release. The current T2 release remains external at
`~/Downloads/LYS_v1_RatLesNetV2_mac_inference`.

## Current checkpoint

- Canonical schema-v6 study roots and stable subject IDs.
- Read-only Bruker/NIfTI discovery and reviewed scan-role assignment.
- Versioned NIfTI conversion, storage-axis flips, validation, and ITK-SNAP viewing.
- Reversible subject archiving, renaming, blinding, groups, and audit history.
- Frozen five-model RatLesNetV2 validation and single/cohort T2 inference.
- Persistent probability maps, draft masks, QC previews, provisional volumes, jobs,
  checksums, and release provenance.
- T1 backend utilities for conversion, registration, mask review, and provisional
  enhancement; none are connected end-to-end in the desktop application.

The T1-guided RS2 refinement notebook is the strongest current T1 brain-mask pre-label
approach by visual inspection. Its outputs remain automatic candidates requiring human
review.

See [current state](docs/current_state.md) for exact blockers and the milestone contract.

## Run locally

```bash
conda env create -f environment.yml
conda run -n lys-bbb python -m pip install --no-deps -e .
conda run -n lys-bbb lys-bbb-desktop
```

Open the explicitly synthetic UI preview with:

```bash
conda run -n lys-bbb lys-bbb-desktop --demo
```

Run the complete test suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

Raw MRI data may live on mounted hard drives. Study creation records source references
and writes derived files under the chosen study root; it does not overwrite source data.

## Documentation map

| Need | Authoritative document |
|---|---|
| Current facts, blockers, and next milestone | [Current state](docs/current_state.md) |
| Stable scientific and package boundaries | [Pipeline architecture](docs/pipeline_architecture.md) |
| Stable desktop product contract | [Desktop application](docs/desktop_application.md) |
| Frozen T2 release and review handoff | [T2 lesion integration](docs/t2_lesion_integration.md) |
| Current T1 mask decision and review rules | [T1 brain extraction](docs/brain_extraction.md) |
| Meaning and limitations of T1 measurements | [Enhancement quantification](docs/enhancement_quantification.md) |
| Commands and developer workflow | [Development guide](docs/development.md) |

`AGENT.md` is the compact operating brief for coding agents. It should point to these
documents rather than duplicate them.

## Scientific and data-safety rules

- Never modify raw Bruker data.
- Automatic masks are drafts, never ground truth.
- Job success, artifact approval, method approval, and result approval are distinct.
- Native pre-Gd T1 is the T1 reference space; native T2 is the lesion-volume space.
- Static pre/post scans support semi-quantitative T1-weighted gadolinium enhancement,
  not absolute T1, `Ktrans`, `Ki`, DCE, or absolute permeability.
- Generated files in `output/`, `derivatives/`, and `reports/` may be older than the
  checked-out code. Preserve manual masks and decisions and record provenance.
