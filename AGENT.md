# Agent operating brief

Read this file first, then open only the authoritative document relevant to the task.
Do not reconstruct project status from old branches or ignored outputs alone.

## Purpose

Build a reproducible backend, and later a desktop application, for mouse MRI analysis:

1. import and validate pre/post T1-weighted scans;
2. create and review a brain mask on native pre-Gd T1;
3. rigidly register post-Gd T1 into pre-Gd T1 space;
4. calculate semi-quantitative gadolinium-enhancement outputs;
5. later import external T2 lesion masks and atlas labels;
6. expose the workflow through a non-programmer desktop interface.

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
- The T2 lesion model is developed in a different repository. Do not add or recreate its
  training code here. Import a released mask plus model provenance later.
- Keep scientific processing outside the future GUI. The application calls stable,
  tested backend services.
- Add or update focused tests with behavior changes.

## Current truth

The repository is technically functional but not biologically ready:

- 34 T1 pre/post cases are converted and have registration outputs.
- 0 cases currently pass the final analysis gate.
- T1 brain-mask quality and explicit review are the immediate blocker.
- Current enhancement normalization and bias correction remain method-development
  choices, not validated primary endpoints.
- Slices 50–170 are a standardized QC display range only. Quantification uses the full
  approved brain mask.

Exact counts and dataset exceptions live in `docs/current_state.md`.

## Current priority order

1. Benchmark open-weight T1 brain-extraction models in Colab on the same cases.
2. Select one pre-label generator using manual QC, surface metrics, failure rate, and
   downstream measurement stability.
3. Review/correct enough masks to unlock final T1 cohort validation.
4. Validate registration and enhancement signal preservation.
5. Stabilize one canonical project data model and review state machine.
6. Add the minimal desktop application.
7. Integrate released T2 lesion outputs from the external repository.
8. Add atlas mapping only after T1/T2 registration is reliable.

## Documentation authority

- `README.md`: human entry point and core commands.
- `docs/current_state.md`: live state, blockers, and branch history.
- `docs/pipeline_architecture.md`: processing graph and ownership boundaries.
- `docs/brain_extraction.md`: current mask policy and Colab benchmark contract.
- `docs/enhancement_quantification.md`: formulas, terminology, and unresolved method
  validation.
- `docs/t2_lesion_integration.md`: external lesion-model interface.
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
registration, analysis-manifest gating, and provisional pair/cohort quantification.

Not implemented as production features: a single end-to-end workflow, external T2 model
invocation, T2-to-T1 transform/QC, atlas registration, validated enhancement thresholds,
long-format regional results, SQLite project state, desktop GUI, or installers.

Prefer reusable functions in `src/lys_bbb/` and thin CLIs in `scripts/`. Model-specific
inference adapters belong under `scripts/brain_extraction/<model>/` and must conform to
the output contract in `docs/brain_extraction.md`.
