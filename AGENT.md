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

The reviewed T2 vertical slice is complete. Finish the first T1 vertical step without
expanding the application shell:

```text
validated native pre-Gd T1
→ checksummed local RS2 inference
→ selected M-seam refinement and conservative continuity cleanup
→ immutable draft mask
→ accept, reject, or import ITK-SNAP correction
→ approved brain mask
→ reopen with state intact
```

Acceptance criteria are authoritative in `docs/current_state.md`.

Until this slice is complete, do not add more pages, layout polish, modalities, atlas
work, synthetic-preview features, unrelated schema revisions, or generic job
abstractions.

## Non-negotiable rules

- Use `conda run -n lys-bbb python ...` unless instructed otherwise.
- Never modify raw Bruker data or overwrite immutable artifacts.
- Keep scientific processing outside Qt widgets: UI → service → backend/repository.
- Put study-wide review work in the general Reviews queue; subject pages may mirror the
  same service actions but must not create a second decision path.
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

## Current facts

- The reviewed T2 path through immutable approval, official native-space volume, CSV
  export, and reopening is production-connected.
- The selected local RS2/M-seam T1 draft generator is implemented; persistent T1
  artifact/review state is the active milestone.
- T1 registration approval and enhancement method validation remain incomplete.

Exact implementation facts and acceptance criteria live only in
`docs/current_state.md`.

## Ownership and legacy boundary

New production state uses `lys_bbb_app.infrastructure.StudyRepository` and
feature-specific repositories/services.

`lys_bbb.project_state.ProjectDatabase` is the frozen schema-v1 compatibility layer.
Production uses it only to inspect and migrate old `.lysbbb` files; tests may create
schema-v1 fixtures with it. Do not add features to it or use it for schema-v7 studies.

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
