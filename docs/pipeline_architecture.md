# Pipeline architecture

## Scientific graph

```text
Subject
├── T1 Enhancement
│   approved pre-Gd brain mask ───────────────┐
│   post-Gd T1 ── approved rigid transform ──> native pre-Gd T1
│                                             └─> semi-quantitative enhancement
│
├── T2 Lesion
│   native T2 ── frozen release ──> draft mask ── human approval
│                                  └─────────────> native lesion volume
│
└── Combined MRI Results
    approved/provisional values + method version + explicit missingness
```

Native pre-Gd T1 is the T1 reference. Native T2 is the lesion-volume reference. T2-to-T1
registration is not a dependency of the MVP lesion volume.

## Repository ownership

```text
LYS_PROJ1
  T2 training, validation, threshold/model selection, locked testing, frozen releases

LYS_PROJ2
  MRI import, scientific execution, study state, review, approval, results, exports
```

`LYS_PROJ2` never imports a live `LYS_PROJ1` checkout. A new upstream model or method
enters through a versioned release and can invalidate dependent desktop results.

Do not split `lys_bbb` and `lys_bbb_app` into separate repositories while their API is
still changing. Reconsider only after the backend has a small stable public interface,
a versioned wheel, contract tests, and an independent release schedule.

## Package dependency direction

```text
src/lys_bbb_app/ui
        ↓
src/lys_bbb_app/services + application presenters
        ↓
src/lys_bbb_app/domain + infrastructure repositories
        ↓                         ↓
SQLite/filesystem adapters       src/lys_bbb scientific backend
```

Rules:

- Qt is restricted to `lys_bbb_app/ui`.
- Domain records are immutable and Qt-free.
- Widgets do not import scientific modules directly.
- Services coordinate use cases and repositories commit canonical state.
- Scientific functions operate on explicit paths/arrays/contracts and do not know Qt.
- External tools such as ITK-SNAP are infrastructure adapters.

Architecture tests enforce these boundaries. Large files should be split only while a
vertical slice reveals a real responsibility boundary.

## Current implementation map

| Capability | Owner | State |
|---|---|---|
| Inventory and Bruker/NIfTI conversion | `lys_bbb` | Implemented |
| Input geometry/checksum validation | `lys_bbb` + study service | Implemented |
| Canonical study/subjects/inputs/audit | schema-v6 repositories | Implemented |
| T2 release validation and inference | `lys_bbb.t2_*` | Implemented |
| T2 release/job/draft persistence | feature repository | Implemented |
| T2 immutable review and approved result | next vertical slice | Missing |
| T1 brain-mask generation/review in app | later vertical slice | Missing |
| T1 registration/quantification backend | `lys_bbb` | Implemented but provisional/review-incomplete |
| Production exports | later slice | Missing |

## State semantics

```text
job succeeded
    → automatic draft
        → rejected
        → corrected as a new version
        → human approved
            → eligible method + exact dependencies
                → approved or provisional result
```

Job success does not imply artifact approval. Artifact approval does not imply method
approval. A result is official only when its method and all required upstream artifacts
are eligible and approved.

Automatic, editable, corrected, approved, rejected, superseded, and outdated products
remain separate records. Replacing a dependency marks downstream state `OUTDATED`; it
does not overwrite or delete it.

## Provenance minimum

Each scientific artifact/result should record:

- study, subject, session, and input identity;
- source and output checksums;
- shape, spacing, orientation, and affine;
- model/method immutable version;
- configuration and code revision;
- exact dependency IDs and supersession link;
- job state, stage, hardware, and structured error;
- reviewer decision and time where applicable;
- output paths and creation time.

## Canonical and transitional state

Schema-v6 `StudyRepository` state is canonical for new desktop studies. It currently
owns studies, subjects, input versions, validation, T2 model releases, T2 jobs, T2 draft
artifacts, blinding/groups, and audit events. Reviews, method records, dependencies, and
approved results are the next additions required by the T2 slice.

The old `lys_bbb.project_state` and `ProjectService` implement a single-file schema-v1
prototype. They are frozen compatibility code used only to inspect and migrate `.lysbbb`
files. They are not a second production database and must not receive new features.

CSV manifests in the repository-development workflow remain transitional handoffs for
T1 work. Desktop users should eventually edit only canonical study state through
services.

## Storage

```text
study-root/
  project.sqlite    canonical mutable state
  project.json      portable identity/schema manifest
  imports/          import manifests
  work/             uncommitted job workspaces
  outputs/          immutable versioned artifacts/results
  reports/          generated QC reports
  exports/          explicit user exports
  logs/             structured logs
```

Repository-development outputs remain under ignored `output/`, `derivatives/`, and
`reports/`. Their presence does not prove that they match the checked-out revision.
