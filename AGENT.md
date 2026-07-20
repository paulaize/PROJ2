# Agent operating brief

Read this file first, then open only the authoritative document relevant to the task.
Do not reconstruct project status from old branches or ignored outputs alone.

## Purpose

Build a reproducible scientific backend and subject-centred desktop application for
mouse T1 and T2 MRI analysis:

1. import and validate pre/post T1-weighted scans;
2. create and review a brain mask on native pre-Gd T1;
3. rigidly register post-Gd T1 into pre-Gd T1 space;
4. calculate semi-quantitative gadolinium-enhancement outputs;
5. import a released T2 lesion mask or invoke a validated frozen external model release;
6. calculate reviewed native-space T2 lesion volume; and
7. expose both workflows through a non-programmer desktop interface.

## Non-negotiable rules

- Use `conda run -n lys-bbb python ...` unless the user specifies another environment.
- Never modify raw Bruker data.
- Treat native pre-Gd coronal T1 as the quantitative reference space.
- Do not independently segment post-Gd T1 by default. Register it to pre-Gd T1 and use
  the approved pre-space brain mask.
- Automatic brain masks are immutable predictions or pre-labels, never ground truth.
- Final masks and registrations require an explicit human decision.
- Report the current static scans as semi-quantitative T1-weighted gadolinium
  enhancement—not absolute T1, `Ktrans`, `Ki`, DCE, or absolute permeability.
- T2 model development is owned by the sibling `~/Documents/LYS_PROJ1` repository.
  Never recreate its training, tuning, checkpoint-selection, or validation logic here.
  The desktop integrates only a versioned, checksummed release contract from that
  repository.
- Never make the production application import Python from a live `LYS_PROJ1` checkout.
  The local path identifies development ownership, not a portable runtime dependency.
- Artifact approval, method approval, result approval, and job success are independent.
  Never promote one merely because another passed.
- Keep scientific processing outside the GUI. The application calls stable,
  tested backend services.
- Add or update focused tests with behavior changes.
- Keep product scope strictly to the registered T1 enhancement and T2 lesion workflows.
  Do not add another modality or scientific workflow without an explicit user decision.
- Blinded review hides or defers group assignment, never reviewer identity. Record the
  blinding state on review decisions; make unblinding and group import explicit audited
  actions, and never infer groups from subject names or folders.

## Current truth

The repository is technically functional but not biologically ready:

- 34 T1 pre/post cases are converted and have registration outputs.
- 0 cases currently pass the final analysis gate.
- T1 brain-mask quality and explicit review are the immediate blocker.
- The frozen 10-image upload package, pinned Colab notebooks, and ITK-SNAP comparison
  launcher are ready. The primary and control runs make RS2-Net the visual front-runner,
  but it includes a recurring superior skull cap. A separate T1-guided correction
  notebook is ready; corrected-mask selection and reviewed-reference scoring remain.
- A separate optional Colab notebook adds CAMRI rodent T2/T2* and deepbet human-T1
  controls. Their domain mismatch must remain explicit in outputs and documentation.
- Current enhancement normalization and bias correction remain method-development
  choices, not validated primary endpoints.
- No released `LYS_PROJ1` T2 backend is integrated in this repository yet.
- Slices 50–170 are a standardized QC display range only. Quantification uses the full
  approved brain mask.

Exact counts and dataset exceptions live in `docs/current_state.md`.

## Current priority order

1. Preserve progress on T1 brain-mask selection, reviewed references, registration QC,
   and enhancement signal-preservation validation.
2. Preserve the implemented desktop input foundation: schema-v4 studies, read-only MRI
   discovery, human-correctable subject/role/orientation proposals, versioned NIfTI
   conversion, subjects, navigation, and audit history.
3. Implement canonical artifacts, jobs, reviews, methods, results, dependencies, and outdated
   state before connecting scientific actions.
4. Connect T1 import/mask review, then registration and provisional quantification.
5. Integrate released T2 masks and validated frozen-release invocation without model
   development code.
6. Add combined T1/T2 results, QC, and reproducibility exports.
7. Keep atlas mapping outside the MVP.

## Documentation authority

- `README.md`: human entry point and core commands.
- `docs/current_state.md`: live state, blockers, and branch history.
- `docs/pipeline_architecture.md`: processing graph and ownership boundaries.
- `docs/brain_extraction.md`: current mask policy and Colab benchmark contract.
- `docs/enhancement_quantification.md`: formulas, terminology, and unresolved method
  validation.
- `docs/t2_lesion_integration.md`: `LYS_PROJ1` T2 release interface.
- `docs/desktop_application.md`: non-programmer product architecture.
- `docs/development.md`: active CLI entry points and developer workflow.

When code and documentation disagree, verify behavior in code and tests, then update the
single authoritative document rather than adding another planning file.

## Repository and branch policy

The feature branches preceding the 2026-07 cleanup are a linear historical stack, not
alternative implementations. The latest branch contains all of their work. New work
should start from the consolidated tip, use one short-lived branch per bounded change,
and merge or delete it when complete.

Generated outputs under `output/`, `derivatives/`, and `reports/` are ignored and shared
across branches. They can be stale after code changes. Never infer that an output was
produced by the checked-out revision without provenance.

Preserve manual masks and review decisions. Other generated outputs can be regenerated,
but do not delete user-created artifacts merely to tidy the worktree.

## Implementation boundaries

Current supported code includes inventory, conversion, mask workflow/QC, rigid pre/post
registration, analysis-manifest gating, provisional pair/cohort quantification, a
schema-v4 PySide6 study-root foundation with persistent and reversibly archived subjects, expected workflows,
read-only Bruker/NIfTI discovery, reviewed subject/role/orientation assignments,
versioned scan-input conversion/provenance, blinding/groups, audit history and recent studies, plus a
connected synthetic design preview for the planned scientific workflow pages.

Not implemented as production features: canonical artifact/review/job/result state, a
single end-to-end workflow, external T2 model
invocation, T2-to-T1 transform/QC, atlas registration, validated enhancement thresholds,
durable subject/artifact/review/job state, long-format regional results,
production-connected desktop processing/review/results behavior, or installers.

Scientific functions belong in `src/lys_bbb/`; all desktop code belongs in
`src/lys_bbb_app/`. Do not create a second Qt shell or compatibility package. Keep CLIs
and external-model adapters thin. Model-specific T1 inference adapters belong under
`scripts/brain_extraction/<model>/` and must conform to the output contract in
`docs/brain_extraction.md`.
