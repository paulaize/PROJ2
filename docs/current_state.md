# Current project state

Last audited: 2026-07-21. This document contains current facts and the immediate
milestone only. Historical plans belong in Git history.

## Executive summary

The repository is technically coherent and should not be replaced or split now. The
current branch is a consolidation candidate for `main`: it has a sensible internal
boundary between `lys_bbb` and `lys_bbb_app`, persistent schema-v7 studies, real MRI
import, frozen-model T2 inference, immutable review, and approved T2 results.

The T2 reviewed-result workflow now crosses the first visible finish line. The product
remains incomplete because the equivalent persistent T1 path has not yet been built.

At this checkpoint, Ruff and the complete test suite pass locally. GitHub Actions runs
the same style check and offscreen suite on pushes and pull requests.

```text
First complete vertical workflow

T2 input → validation → inference → draft/corrected mask → human decision
→ approved native-space volume → approved-only CSV → reopen unchanged
```

## Implemented now

### Desktop and study state

- Create, open, and reopen schema-v7 study roots; schema-v2 through v6 roots migrate
  non-destructively when opened.
- Reference read-only Bruker/NIfTI source folders on mounted drives.
- Discover scans and let users correct subject IDs, T1/T2 roles, and orientation actions.
- Convert confirmed inputs to versioned managed NIfTI files with provenance.
- Validate geometry and checksums; batch-flip storage axes as new versions.
- Rename or reversibly archive subjects without losing historical state.
- Preserve blinded review, optional groups, reviewer identity, and audit history.
- Open active MRI inputs in ITK-SNAP.

The persistent T2 review controls live in each subject's `T2 Lesion` tab. The global
`Reviews` page, cohort chart, QC/reproducibility export buttons, and most settings remain
explicitly labelled design fixtures; they do not save scientific state. `--demo` is
entirely synthetic.

### T2 lesion workflow

The complete T2 path—checksummed five-model inference, immutable draft/correction,
human decision, official native-space volume, approved-only CSV, invalidation, and
reopening—is implemented. Its exact acceptance criteria are recorded below; release and
scientific details live in `t2_lesion_integration.md`.

The supplied unseen T2 smoke case reproduced the prior result exactly at the binary-mask
level: 7,339 voxels and identical affine. CPU/MPS probability differences were at most
1.73 × 10⁻⁶.

### T1 scientific backend

- 36 raw sessions and 285 scans inventoried.
- 35 intended T1 cases; 34 converted pairs.
- 34 rigid registration outputs; zero explicit registration approvals.
- Zero explicitly approved T1 brain masks and zero cases in the final analysis gate.
- Enhancement calculation exists, but its independent pre/post normalization may
  suppress diffuse signal and remains provisional.

The T1-guided RS2 refinement experiment has now run on the frozen ten-case cohort and
is the best current pre-label approach by visual inspection. Review selected M-seam over
raw RS2, marker-watershed, and random-walker. A local macOS command now invokes the exact
reviewed RS2 commit and weight, applies M-seam, removes conservatively gated small slice
islands, repairs only short outlier runs with agreeing flanks, and writes native-grid
drafts plus QC and provenance. The added continuity cleanup still needs ten-case visual
review, and no automatic output is ground truth or an approved mask. Exact eight-way
TTA is CPU/CUDA on the tested M1 because it exceeded MPS memory. The explicit MPS/no-TTA
variant completed one real case in 83 seconds and reached raw-mask Dice 0.980 against its
Colab TTA counterpart; it is recorded as a distinct draft method, not an equivalent run.

## Known dataset exceptions

- `C23S2_D1`: T1 conversion failure; no valid ParaVision study reported by `brkraw`.
- `C26S5_D1`: no usable T1 pre/post pair.
- `C23S3`: both `D1` and `D1_bis`; one must be selected for a unique longitudinal pair.
- Treatment groups remain blinded.

## Completed vertical milestone: T2 reviewed result

The current implementation covers this user story:

> A researcher imports and validates T2, runs the frozen model, reviews or corrects the
> draft mask, approves it, receives an official native-space lesion volume, exports one
> CSV, and reopens the study with the complete state intact.

Implemented acceptance criteria:

1. A draft mask can be accepted, rejected, or replaced by an ITK-SNAP-corrected mask.
2. A correction is a new immutable artifact version; the automatic prediction remains.
3. Reviewer identity, timestamp, decision, notes, issue code, and blinding state persist.
4. Rejection requires a reason; approval does not require a note.
5. Official voxel count and volume are calculated only from an approved native-grid mask.
6. Provisional values are never silently promoted to official results.
7. Replacing T2, approving another mask version, or changing the model release makes the
   previous official result `OUTDATED` without deleting it.
8. One approved-results CSV includes subject ID, optional group, value, unit, method,
   mask checksum, release ID, reviewer, approval time, and result state.
9. Closing and reopening preserves artifacts, decisions, dependencies, result, and audit.
10. Focused tests cover allowed and blocked transitions, correction validation,
    invalidation, export gating, reopening, and migration of an existing schema-v6 draft.

Use ITK-SNAP for correction. Do not build an embedded segmentation editor.

## Still explicitly frozen

- Additional application pages or synthetic-preview features.
- More responsive-layout polishing.
- Atlas or T2-to-T1 integration.
- New modalities or models.
- General-purpose plugin/job/workflow frameworks.
- New schema revisions without a concrete vertical-workflow requirement.
- Cohort charts beyond the single approved-results CSV.

## What follows

After a real-case desktop smoke test of the completed T2 slice, finish the T1 vertical
slice. The local draft generator now exists; application persistence and review do not:

```text
T1 import → refined RS2 pre-label/import → mask review/approval
→ exact reviewed post-to-pre registration → registration approval
→ explicitly provisional enhancement method → subject result/export
```

Before T1 cohort interpretation:

- require explicit mask and registration approval in the analysis gate;
- quantify the exact reviewed registration rather than recomputing it;
- validate signal preservation for diffuse and focal enhancement;
- treat 3-D mask regularity metrics as QC warnings, not automatic anatomical truth.

## Repository direction

Do not create another repository. Keep:

```text
LYS_PROJ1  model development and frozen T2 releases
LYS_PROJ2  execution backend, desktop review, approval, results, and exports
```

After this consolidation passes local tests and CI, open one PR from
`feat/pyside-project-foundation` to `main`, preserve the useful commits, merge it, and
delete the long-lived feature branch. A backend/desktop repository split should be
considered only after the backend has a small stable public API, versioned wheel,
contract tests, and an independent release schedule.

## Generated-state warning

`output/`, `derivatives/`, and generated `reports/` are ignored and shared across local
branches. File presence is not proof of provenance or approval. Preserve manual masks
and decisions before regenerating reports, and record the code/model revision for every
scientific result.
