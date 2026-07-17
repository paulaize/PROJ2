# Pipeline architecture

## Stable scientific design

Native pre-Gd T1 is the quantitative reference space. Other images and labels are
mapped into that space only when needed.

```text
post-Gd T1 ── rigid ────────────────> pre-Gd T1
                                              │
pre-Gd brain mask ────────────────────────────┤
                                              ├─> enhancement maps and metrics
external T2 lesion mask ─ T2→T1 transform ───┤
                                              │
atlas labels ─ optional transform chain ──────┘
```

Brain extraction, lesion segmentation, enhancement measurement, and atlas mapping are
separate tasks. A success in one stage does not imply QC acceptance in another.

## Processing stages

| Stage | Current status | Required output |
|---|---|---|
| Input inventory and validation | Implemented | Case/scan inventory |
| Bruker T1 conversion | Implemented | Native pre/post coronal NIfTI |
| T1 brain extraction | Model selection in progress | Immutable prediction plus reviewed mask |
| Post-to-pre T1 registration | Implemented, review incomplete | Transform, registered image, QC decision |
| Enhancement quantification | Implemented, method provisional | Maps, metrics, provenance |
| T2 lesion segmentation | External repository | Released T2-space lesion mask and provenance |
| T2-to-T1 linkage | Planned here | Transform, transferred mask, registration QC |
| Atlas mapping | Deferred | Subject-space labels and QC |
| Desktop application | Planned | Non-programmer project workflow |

## Human review states

Automatic output and human decisions must be distinct. The target state machine is:

```text
auto_generated
      ↓
needs_review ──> accepted_auto
      ├────────> manually_corrected
      ├────────> rejected
      └────────> excluded
```

Each accepted mask should eventually record source prediction, model and version,
reviewer, decision time, notes, and a checksum. The current `_done` filename convention
is transitional and must not become the desktop application's source of truth.

## Provenance contract

Every processing stage should record:

- case and session identity;
- input paths and checksums where practical;
- image shape, spacing, orientation, and affine;
- software/model name and immutable version or digest;
- parameters and transform paths;
- automatic QC values;
- human review state;
- code revision and timestamp;
- output paths and failure details.

Automatic predictions must not be overwritten. Editable and accepted copies are separate
files so model performance and reviewer changes remain auditable.

## Backend layers

```text
Desktop interface (future)
        ↓
Application services and canonical project state (future)
        ↓
Workflow orchestration and resume logic (future)
        ↓
Reusable scientific modules in src/lys_bbb
        ↓
Versioned derivatives, transforms, QC, and exports
```

The CLI remains useful for development, testing, reproducibility, and support. Ordinary
end users should eventually interact only with the desktop application.

## Canonical project state

The current workflow spreads state across a QC manifest, manual-mask worklist, study
metadata, analysis manifest, and nnU-Net manifest. These remain valid internal products,
but future users should edit only one source of truth.

The desktop product should use:

- SQLite for processing attempts, model versions, errors, and review decisions;
- CSV/TSV imports and exports for transparency;
- generated analysis/training manifests derived from the database;
- migrations so older projects remain openable.

Until that layer exists, `study_metadata.csv` is the editable scientific metadata table,
the manual worklist stores mask/registration review, and `analysis_manifest.csv` is the
QC-gated quantification handoff.

## Output organization

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
