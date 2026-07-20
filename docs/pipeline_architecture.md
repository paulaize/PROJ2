# Pipeline architecture

## Stable scientific design

The desktop product is subject-centred and owns two independent workflows. Combined
MRI results join approved subject-level records; they do not erase each workflow's native
space, method status, or review history.

```text
Subject
├── T1 Enhancement
│   post-Gd T1 ── rigid ──> native pre-Gd T1
│   approved pre-Gd brain mask ────────┤
│                                      └─> semi-quantitative enhancement
│
├── T2 Lesion
│   native T2 + approved native-grid lesion mask ─> lesion volume in mm³
│
└── Combined MRI Results
    approved/provisional records + explicit missingness and method versions
```

Native pre-Gd T1 remains the quantitative reference for T1 enhancement. Native T2 is
the reference for MVP lesion volume. T2-to-T1 registration is not required for that
measurement and is deferred for later lesion-associated T1 analyses.

Brain extraction, lesion segmentation, registration, enhancement measurement, and human
review are separate tasks. Success in one stage never implies acceptance in another.

## Upstream backend ownership and handoff

The sibling repository `~/Documents/LYS_PROJ1` is the scientific development source for
the T2 lesion backend. This repository, `LYS_PROJ2`, owns desktop integration,
study/subject state, job execution, human review, dependency invalidation, results, and
exports.

The workstation path is a developer reference only. Production code must not add
`LYS_PROJ1` to `sys.path`, import its live source tree, depend on its current Git branch,
or read uncommitted training outputs. The handoff is:

```text
LYS_PROJ1 development and scientific validation
    → frozen backend/model release + contract + checksums + provenance
    → explicit installation/import into a LYS_PROJ2 study/application
    → draft artifacts → LYS_PROJ2 human review → versioned results
```

`LYS_PROJ1` remains authoritative for algorithm behavior, model/threshold selection,
scientific validation, and release contents. `LYS_PROJ2` validates compatibility and
checksums, invokes the declared interface, and records outputs without modifying the
upstream release. Updating the backend requires a new release/version and can mark
dependent desktop results outdated.

## Processing stages

| Stage | Current status | Required output |
|---|---|---|
| Study/project state | Input + first T2 artifact slice implemented | Schema-v6 study root, subjects, expected workflows, blinding/groups, MRI roots, versioned inputs, model releases, jobs, draft T2 artifacts, and audit |
| Input inventory and validation | Implemented | Case/scan inventory |
| Bruker T1 conversion | Implemented | Native pre/post coronal NIfTI |
| T1 brain extraction | Model selection in progress | Immutable prediction plus reviewed mask |
| Post-to-pre T1 registration | Implemented, review incomplete | Transform, registered image, QC decision |
| Enhancement quantification | Implemented, method provisional | Maps, metrics, provenance |
| T2 lesion model development | Active in `LYS_PROJ1` | Frozen release package or released mask and provenance |
| T2 lesion inference | Implemented for frozen LYS v1 bundle | Native-grid probability map and draft mask with release/job provenance and QC preview |
| Native T2 lesion volume | Provisional draft value implemented | Human-approved-mask voxel count and official volume in mm³ remain gated on review |
| T2-to-T1 linkage | Post-MVP | Transform, transferred mask, registration QC |
| Atlas mapping | Explicitly excluded from MVP | Subject-space labels and QC |
| Desktop application | Persistent shell + T2 inference implemented | Study create/open/migrate, subjects, inputs, release selection, single/cohort T2 run, draft inspection, blinding/groups, and audit; approval/results/exports remain planned |

## Review, method, and result states

Automatic output and human decisions must be distinct. The artifact review path is:

```text
draft_auto
      ↓
awaiting_review ──> human_approved
      ├────────> manually_corrected
      ├────────> rejected
      └────────> superseded
```

Each accepted mask should eventually record source prediction, model and version,
reviewer, decision time, notes, and a checksum. The current `_done` filename convention
is transitional and must not become the desktop application's source of truth.

Artifact approval, method approval, result approval, and job success are independent.
A successful job creates a draft artifact or provisional result; it never creates human
approval. A human-approved artifact produced under a method-development policy can feed
a reviewed provisional measurement, but not an official approved measurement. Changing
an approved dependency marks downstream artifacts/results outdated without deleting
their history.

## Provenance contract

Every processing stage should record:

- case and session identity;
- input paths and checksums where practical;
- image shape, spacing, orientation, and affine;
- software/model name and immutable version or digest;
- parameters and transform paths;
- automatic QC values;
- human review state;
- method status and immutable method ID;
- dependency artifact IDs and supersession links;
- code revision and timestamp;
- output paths and failure details.

Automatic predictions must not be overwritten. Editable and accepted copies are separate
files so model performance and reviewer changes remain auditable.

## Backend layers

```text
Desktop interface in src/lys_bbb_app
        ↓
Application services, view models, workflow policies, and canonical project state
        ↓
Worker-process job orchestration, cancellation, and recovery
        ↓
Reusable scientific modules in src/lys_bbb
        ↓
Versioned artifacts, transforms, QC, results, audit history, and exports
```

The CLI remains useful for development, testing, reproducibility, and support. Ordinary
end users should eventually interact only with the desktop application.

## Canonical project state

The current developer workflow spreads state across a QC manifest, manual-mask worklist,
study metadata, analysis manifest, and nnU-Net manifest. These remain valid transitional
products, but desktop users edit only canonical SQLite state through application
services.

The target study root uses:

- SQLite for studies, subjects, artifacts, dependencies, processing attempts, methods,
  model releases, reviews, results, errors, audit events, and timestamps;
- CSV/TSV imports and exports for transparency;
- generated analysis and worker-handoff manifests derived from the database;
- migrations so older projects remain openable.

Schema version 1 establishes only project identity, migration history, and T1/T2w
folder assignments in a `.lysbbb` file. Schema version 2 introduced the study root,
subjects, expected workflows, blinding/groups, and audit history. Implemented schema
version 3 adds one combined MRI source reference plus subject-owned, versioned T1-pre,
T1-post, and T2 input records with source identity, orientation operations, conversion
state, geometry, hashes, and immutable NIfTI outputs. Schema-v2 roots migrate in place;
the original schema-v1 prototype remains unchanged during explicit migration. Saved raw
paths may point to mounted hard drives and may be temporarily unavailable when a study
is opened.

Until the foundation schema expands to own scientific metadata and review records,
`study_metadata.csv` remains the editable metadata table, the manual worklist stores
mask/registration review, and `analysis_manifest.csv` is the QC-gated quantification
handoff.

## Output organization

Target desktop study:

```text
study-root/
  project.sqlite       canonical mutable state
  project.json         portable identity and schema manifest
  imports/             import manifests and optional explicit managed copies
  work/                uncommitted job workspaces
  outputs/             immutable versioned artifacts and results
  reports/             QC and study reports
  exports/             user-requested exports and reproducibility bundles
  logs/                structured application and worker logs
```

Current repository-development outputs remain:

```text
output/                 converted working images
derivatives/
  brain_extraction/     predictions, edited/reviewed masks, benchmarks
  registration/         transforms and registered images
  manifests/            generated internal handoffs
  quantification/       maps and tables
reports/
  inventory/            raw-data inventory
  qc/                   compact review/status products
```

Large derivatives remain ignored. Long-term reproducibility therefore depends on the raw
data, canonical project state, model versions, code revision, and explicit commands—not
on the Git branch name alone.
