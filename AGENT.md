# Agent operating brief

Read this file first. Then open only the authoritative document needed for the task.

## Product

Build a reproducible PySide6 application for subject-owned mouse MRI workflows:

```text
T1 Enhancement
T2 Lesion Segmentation and Native-space Volume
```

`src/lys_bbb/` is the Qt-free scientific backend. `src/lys_bbb_app/` is the desktop
application. Do not create another repository or a second application shell.

## Current milestone

Finish the T2 vertical slice before expanding anything else:

```text
validated native T2
→ frozen-model inference
→ immutable draft mask
→ accept, reject, or import ITK-SNAP correction
→ approved mask
→ official native-space volume
→ approved-results CSV
→ reopen with state intact
```

Acceptance criteria are authoritative in `docs/current_state.md`.

Until this slice is complete, do not add more pages, layout polish, modalities, models,
atlas work, synthetic-preview features, schema revisions, or generic job abstractions.

## Non-negotiable rules

- Use `conda run -n lys-bbb python ...` unless instructed otherwise.
- Never modify raw Bruker data or overwrite immutable artifacts.
- Keep scientific processing outside Qt widgets: UI → service → backend/repository.
- Automatic masks are drafts, never ground truth.
- Human approval requires reviewer identity and time. Rejection requires a reason.
- Job success, artifact approval, method approval, and result approval are independent.
- New or corrected masks are new versions; previous files and decisions remain.
- Changing an approved dependency makes results outdated; it never silently replaces
  or deletes them.
- Native pre-Gd T1 is the T1 reference. Register post-Gd to pre-Gd and use the approved
  pre-space mask for both.
- Use only semi-quantitative T1-weighted gadolinium-enhancement terminology. Never claim
  absolute T1, `Ktrans`, `Ki`, DCE, or absolute permeability.
- T2 model development stays in `~/Documents/LYS_PROJ1`. This repository validates and
  invokes frozen checksummed releases and never imports its live checkout.
- Keep product scope to the T1 and T2 workflows unless explicitly changed.
- Blinding hides groups, not reviewer identity. Unblinding and group assignment are
  explicit audited actions.
- Add focused tests for every state transition and behavior change.

## Current truth

- Schema-v7 studies, MRI import/conversion/validation, subjects, audit, blinding/groups,
  ITK-SNAP launch, T2 inference, correction, review, official volume, and approved-only
  CSV export are production-connected.
- T2 inference creates persistent probability maps, draft masks, QC previews, jobs,
  provenance, and provisional volumes; only an immutable human approval creates an
  official result.
- Zero T1 cases currently pass the final scientific analysis gate.
- The T1-guided RS2 refinement notebook is the strongest current T1 brain-mask pre-label
  approach by visual inspection. It remains unapproved; three-dimensional regularity is
  a QC warning and review aid, never an automatic approval rule.
- T1 registration exists in backend development outputs but lacks explicit approvals.
- Enhancement normalization remains method-development work.

Exact operational facts live in `docs/current_state.md`.

## Ownership and legacy boundary

New production state uses `lys_bbb_app.infrastructure.StudyRepository` and
feature-specific repositories/services.

`lys_bbb.project_state` and `lys_bbb.project_service.ProjectService` are frozen legacy
schema-v1 compatibility code. They exist only to inspect and migrate old `.lysbbb`
files. Do not add new features to them and do not use them for schema-v7 studies.

## Documentation authority

- `README.md`: short human entry point.
- `docs/current_state.md`: current facts, blockers, and immediate milestone.
- `docs/pipeline_architecture.md`: ownership, package, state, and storage boundaries.
- `docs/desktop_application.md`: stable product contract, not an implementation wishlist.
- `docs/t2_lesion_integration.md`: frozen release and T2 review contract.
- `docs/brain_extraction.md`: current T1 mask decision and QC policy.
- `docs/enhancement_quantification.md`: T1 measurement meaning and validation.
- `docs/development.md`: active commands and developer workflow.

When code, tests, and documentation disagree, verify behavior in code and tests and
update the single authoritative document. Git history is the archive; do not retain
obsolete plans inside current-state documents.

## Repository hygiene

- Preserve manual masks, review decisions, and raw data.
- Generated outputs under `output/`, `derivatives/`, and `reports/` are ignored and can
  be stale across branches.
- Split large modules only while implementing the next vertical slice and only along a
  real responsibility boundary.
- Keep CLIs thin and typed domain records Qt-free.
- Run the full suite before committing. Use CI as the visible merge gate.
