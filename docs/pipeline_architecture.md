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

## State semantics

```text
job succeeded
    → automatic draft
        → manually edited as a new version
        → human approved
            → eligible method + exact dependencies
                → approved or provisional result
```

Job success does not imply artifact approval. Artifact approval does not imply method
approval. A result is official only when its method and all required upstream artifacts
are eligible and approved.

Automatic, editable, corrected, approved, superseded, and outdated products
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
- reviewer identity and approval time where applicable;
- output paths and creation time.

## Canonical and transitional state

Schema-v10 `StudyRepository` state is canonical for new desktop studies. It owns studies,
subjects, input versions, validation, T2 model releases/jobs/artifacts/results, T1
brain-mask releases/jobs/artifacts/approvals, T1 registration methods/jobs/artifacts/
approvals, provisional enhancement methods/jobs/results, blinding/groups, and audit
events. The T1 tables are feature-specific because their approval and dependency
contracts differ from the T2 ensemble and measured result. Presenters merge reviewable
feature state into the same application presentation layer.

`lys_bbb.project_state.ProjectDatabase` is the frozen compatibility layer for the
single-file schema-v1 prototype. Production uses it only for inspection and migration;
it is not a second production service or database and must not receive new features.

CSV manifests in the repository-development workflow remain scientific-validation
handoffs. Desktop T1 processing uses canonical study state through services. The
registration and enhancement run/review controls are not yet exposed in the UI, while
the enhancement measurement itself remains scientifically provisional.

The T1 brain-mask slice uses `lys_bbb.t1_brain_mask_review` for native-grid binary-mask
validation, `T1BrainMaskReviewService` for managed correction/approval, and a feature
repository for frozen releases, durable runs, immutable mask versions, and approvals.
Automatic mask volume is QC metadata only; it is not a T1 analysis result.

`lys_bbb.t1_registration` owns the Qt-free frozen rigid-registration contract and emits
the registered post image, transform, QC, checksums, and method identity. The app stores
that immutable bundle and requires approval of the exact checksummed files.
`lys_bbb.t1_enhancement` accepts the approved registered post directly and cannot
recompute registration. It calls the typed `FlashPairRequest` backend directly; the
argument parser is retained only as a compatibility adapter for CLI and cohort callers.
Its outputs remain explicitly `PROVISIONAL` and are invalidated when the source input,
mask, registration, or active method changes.

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
