# Current project state

Last audited: 2026-07-30. This document contains current facts and the immediate
milestone only. Historical plans belong in Git history.

## Executive summary

The repository is technically coherent and should not be replaced or split now. The
current branch is a consolidation candidate for `main`: it has a sensible internal
boundary between `lys_bbb` and `lys_bbb_app`, persistent schema-v13 studies, real MRI
import, frozen-model T1/T2 draft generation, immutable review, approved T1 brain masks,
durable T1 registration/provisional-enhancement state, and approved T2 results.

The T2 reviewed-result workflow and the persistent T1 path from brain-mask generation
through reviewed registration and provisional enhancement are connected to the desktop.
The product remains incomplete because the T1 slice still needs a real-case smoke test
and the enhancement method has not passed signal-preservation validation. Atlas
registration/mapping is explicitly deferred and is not exposed anywhere in the app
because no currently tested atlas method has sufficient validated regional accuracy.

At this checkpoint, Ruff and the complete test suite pass locally. GitHub Actions runs
the same style check and offscreen suite on pushes and pull requests.

```text
First complete vertical workflow

T2 input → validation → inference → draft/corrected mask → human approval
→ approved native-space volume → approved-only CSV → reopen unchanged
```

## Implemented now

### Desktop and study state

- Create, open, and reopen schema-v13 study roots; schema-v2 through v12 roots migrate
  non-destructively when opened.
- Choose an immutable combined T1/T2, T1-only, or T2-only analysis scope at creation;
  irrelevant import roles, worklist columns, review queues, and subject tabs stay hidden.
- Reference read-only Bruker/NIfTI source folders on mounted drives.
- Discover scans and let users correct subject IDs, T1/T2 roles, and orientation actions.
- Convert confirmed inputs to versioned managed NIfTI files with provenance.
- Validate geometry and checksums; batch-flip storage axes as new versions.
- Rename or reversibly archive subjects without losing historical state.
- Preserve blinded review, optional groups, reviewer identity, and audit history.
- Open active MRI inputs in ITK-SNAP.

The Subjects worklist uses operational subject, next-action, enabled-modality, and
overall-state columns instead of exposing every internal workflow stage. Selecting one subject
with an unvalidated conversion enables direct MRI validation from the worklist. The
subject workspace is action-first: one primary next-action card and compact enabled-workflow state
replace the previous repeated summary, metadata, and workflow cards. Stored IDs, paths,
geometry, checksums, device, release, and method provenance remain accessible through
collapsed technical-detail disclosures.

Persistent draft and corrected T1 brain masks and T2 lesion masks populate the
study-level `Reviews` queue, where the user can approve the current mask or manually
edit a managed ITK-SNAP copy. Saving that edit through the app registers it as the new
active human-corrected mask version. The queue is filtered by T1/T2 modality
buttons; each pending item is one subject/workflow button. Mask QC renders every native
slice for previous/next navigation, with display-only orientation changes never
modifying the NIfTI. The subject's `T1 Brain Mask` and `T2 Lesion` tabs mirror the same
service actions. The subject's `T1 Registration + Result` tab runs the frozen post-to-pre
registration off the GUI thread, exposes its QC and exact approval, and calculates an
explicitly provisional enhancement result after approval. Registrations awaiting review
also populate the general T1 Reviews queue. Cohort charts and QC/reproducibility exports
are not implemented. The application contains no sample-data mode or placeholder
scientific actions.

Historical atlas backend and persistence code remains in the repository, but the active
feature profile filters atlas reviews and does not construct, connect, or display an
Atlas Mapping tab. Users cannot initiate atlas registration or mapping.

### T2 lesion workflow

The complete T2 path—checksummed five-model inference, immutable draft/correction,
human approval, official native-space volume, approved-only CSV, invalidation, and
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
TTA now uses CUDA when available, the bounded-memory MPS adapter on Apple Silicon, and
CPU only as a fallback. The explicit MPS/no-TTA variant completed one real case in 83
seconds and reached raw-mask Dice 0.980 against its Colab TTA counterpart; it remains a
distinct draft method, not an equivalent run.

For desktop integration, the installed exact-TTA RS2 release remains an immutable
validated source-and-weight contract, while the interactive app now runs the explicit
no-TTA local-draft variant. The no-TTA execution has its own versioned method
specification and hash and remains provisional until mask review and approval. Schema-v12
persists the release separately from T2 releases, records durable T1 jobs, commits only
successful native-grid drafts, preserves raw RS2 and QC provenance, versions managed
ITK-SNAP corrections, and records exact mask approval with reviewer, time, and blinding
state. Replacing the native pre-Gd T1 makes the active brain mask outdated without
deleting its file or historical approval.

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

1. A draft mask appears in the general Reviews queue and can be approved or manually
   edited in ITK-SNAP.
2. The app creates and tracks the editable copy; using the saved edit registers a new
   active immutable artifact version while preserving the automatic prediction.
3. Approval records only reviewer identity, timestamp, exact artifact, and blinding
   state. The app stores no review notes, issue types, or rejection decision.
4. A manually edited mask still requires explicit approval before it can create an
   official result.
5. Official voxel count and volume are calculated only from an approved native-grid mask.
6. Provisional values are never silently promoted to official results.
7. Replacing T2, approving another mask version, or changing the model release makes the
   previous official result `OUTDATED` without deleting it.
8. One approved-results CSV includes subject ID, optional group, value, unit, method,
   mask checksum, release ID, reviewer, approval time, and result state.
9. Closing and reopening preserves artifacts, approvals, dependencies, result, and audit.
10. Focused tests cover allowed and blocked transitions, correction validation,
    invalidation, export gating, reopening, and schema migration.

Use ITK-SNAP for correction. Do not build an embedded segmentation editor.

## Implemented vertical milestone: T1 reviewed brain mask

The application code now covers this user story:

> A researcher validates the native pre-Gd T1, runs the frozen local RS2/M-seam
> method, reviews or corrects the automatic draft, approves the exact current mask,
> and reopens the study with release, job, artifact, correction, and approval intact.

Implemented acceptance criteria:

1. The app validates the exact RS2 source commit, weight checksum, release manifest,
   exact-TTA release declaration, and deterministic M-seam/cleanup configuration hash.
   Each interactive job additionally records the distinct no-TTA generation contract.
2. Generation runs outside the GUI thread and persists queued, running, succeeded,
   failed, or interrupted job state independently from artifact approval.
3. A successful run creates an immutable automatic draft tied to the exact native
   pre-Gd T1, release, job, checksums, device, QC, and regularity warnings.
4. The draft appears in the general T1 Reviews queue and the subject's T1 Brain Mask
   tab mirrors the same service-backed actions.
5. Manual editing uses a managed ITK-SNAP copy; the automatic artifact is never
   overwritten, and the saved edit becomes a new active immutable version.
6. Corrected masks must remain non-empty, binary, and on the exact native pre-Gd T1
   shape, spacing, and affine.
7. Approval records only reviewer identity, timestamp, exact artifact, and blinding
   state. Automatic and corrected masks both require explicit approval.
8. Replacing or invalidating the native pre-Gd T1 makes the active mask outdated while
   preserving previous files and approvals.
9. Closing and reopening preserves the frozen release, job, all artifact versions,
   supersession, and approval.
10. Focused tests cover generation success, correction, invalid edits, checksum change,
    approval, dependency invalidation, migration, presentation, and reopening.

An isolated real-input exact-TTA MPS smoke run completed on 2026-07-22 in approximately
seven minutes but made the 8 GB development Mac difficult to use. The app therefore
defaults to the explicit no-TTA draft method, measured at approximately 83 seconds in
the earlier one-case run. A representative multi-case comparison, full app-managed run,
review, and anatomical approval remain required before relying on it for cohort analysis.

## Implemented desktop milestone: T1 registration and provisional enhancement

The non-UI application path now covers this dependency chain:

```text
validated pre/post T1 + exact approved pre-space mask
→ frozen rigid registration job
→ immutable registered post/transform/QC bundle
→ explicit approval of that exact bundle
→ provisional enhancement from the approved registered post
→ dependency-aware result and reopen
```

Implemented acceptance criteria:

1. Registration has a typed Qt-free request/config/output contract with a deterministic
   method-spec checksum.
2. The app records registration methods and durable queued/running/succeeded/failed/
   interrupted jobs independently from artifact approval.
3. Every registration artifact records the exact pre/post scan versions, approved mask,
   registered image, transform, QC, checksums, metric, and QC correlation values.
4. Approval verifies the registered image, transform, and QC checksums before recording
   reviewer identity and time.
5. Enhancement has a separate typed contract that accepts an already registered post
   image and disables registration recomputation.
6. Enhancement runs only from the exact active approved registration and its exact
   approved mask, then persists map, summary, QC, metadata, checksums, and dependency IDs.
7. Every enhancement result is labelled `PROVISIONAL`; there is no method or result
   promotion to an official T1 endpoint.
8. Replacing or invalidating a source pre/post input or brain mask, or creating a new
   registration, marks active downstream artifacts/results outdated without deleting
   historical files or approvals.
9. Stored input/dependency checksums are reverified immediately before processing, and
   returned output checksums and durable job paths are verified before database commit.
10. Focused tests cover approval-to-result execution, no-registration enhancement,
    invalidation, migration, presentation, reopening, and the connected desktop sequence.
11. The selected production method is
    `antspyx_0_6_3_unmasked_regular_25pct_mattes_rigid_v1`: fixed native pre-Gd T1,
    moving native post-Gd T1, geometry-centre initialization, six-degree-of-freedom
    rigid, 50-bin Mattes MI with regular 25% sampling, seed 42, one ITK thread, and one
    linear interpolation into the unchanged pre-T1 grid. The corrected pre-T1 mask is
    QC-only. Every output remains `DRAFT_REVIEW_REQUIRED`.

This path is ready for a real-case desktop smoke test, not scientific cohort
interpretation. The existing legacy cohort/CLI code remains an exploratory compatibility
path and is not an approval route.

## Selected native pre-T1 to partial-T2 development registration

The Qt-free backend and durable application artifact workflow use only
`native_pre_t1_to_partial_t2_antspyx_0_6_3_rigid_unmasked_sensitivity_v1`.
Original native partial T2 is fixed and original native pre-Gd T1 is moving. The method
uses geometry-centre rigid initialization, 32-bin Mattes MI, regular 50% sampling,
seed 42, a physical 2×1 pyramid, and no metric masks. Scalar T1 is linearly interpolated
once into the unchanged T2 grid; the corrected T1 mask is propagated once with
`GenericLabel` for QC only. A lesion mask is optional and display-only. QC renders every
original T2 slice. Explicit equal database/manifest identities are mandatory.

Transforms, command records/logs, hashes, geometry, runtime, method specification, and
all-slice QC are durable artifacts. Outputs remain `DRAFT_REVIEW_REQUIRED` and require
human QC; the method is an operational development selection, not an independently
landmark-validated method. The operation and its original-slice QC are available in the
subject's `T1 Registration + Result` tab. This registration does not enable atlas mapping.

## Still explicitly frozen

- Additional application pages or placeholder UI features.
- More responsive-layout polishing.
- All atlas registration, mapping, regions, and atlas-facing UI.
- Affine, deformable, masked, N4, or other registration candidates.
- New modalities or models.
- General-purpose plugin/job/workflow frameworks.
- New schema revisions without a concrete vertical-workflow requirement.
- Cohort charts beyond the single approved-results CSV.

## What follows

The independent T1 enhancement smoke test remains:

```text
approved pre-Gd brain mask → run exact post-to-pre registration
→ inspect QC and approve the exact registration
→ run explicitly provisional enhancement → inspect subject result
```

Close and reopen the study and confirm that the mask, registration approval, provisional
result, exact dependencies, and history are unchanged.

Before T1 cohort interpretation:

- run a real approved mask/registration/result through the new persistent path;
- validate signal preservation for diffuse and focal enhancement;
- choose and freeze a justified normalization strategy before result approval/export;
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
and approvals before regenerating reports, and record the code/model revision for every
scientific result.
