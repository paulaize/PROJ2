# Desktop application MVP

## Authority and implementation status

This document is the product and application-architecture contract for the LYS BBB
desktop MVP. Scientific details remain authoritative in the workflow-specific documents.
Operational facts about what is implemented today live in `docs/current_state.md`.

The current code includes two deliberately separate experiences:

- a real schema-v4 foundation that creates/reopens study roots, remembers recent
  studies and MRI source roots, persists subjects, versioned scan inputs, and expected workflows, enforces
  one-way blinded review, saves group assignments, and records audit history; and
- a connected design preview (`lys-bbb-desktop --demo`) that renders the planned shell
  and workflow pages from explicitly synthetic, non-persistent view models.

The preview currently covers the study launcher, Overview, Subjects, Subject Workspace,
Review/QC, Results/Export, and Settings. It supports navigation, filtering, subject-to-
review routing, local approve/reject interaction, viewer slice/overlay controls, and
preview export actions. Study, subject, blinding, group, source-folder, scan-input,
conversion-provenance, and audit state are production-connected outside demo mode.
Mask, registration, review, result, and export behavior remains a visual and interaction
prototype until the later phases below.

## Product objective

The MVP lets a non-technical researcher:

1. create, open, and resume a local study;
2. import subject-owned T1 and T2 MRI data without modifying source files;
3. see the processing and review status of every subject;
4. launch registered, versioned quantification workflows under an explicit execution
   policy;
5. review automatically generated masks and registrations;
6. approve or reject scientific artifacts explicitly;
7. inspect subject-level and cohort-level results; and
8. export results, QC, audit history, and reproducibility information.

The two subject-owned MVP workflows are:

- T1-weighted gadolinium enhancement;
- T2 lesion segmentation and native-space volume quantification.

The application is a workflow runner and review system, not a model-development tool.
RatLesNetV2 training, loss comparison, cross-validation, checkpoint selection, and
locked-test evaluation remain in the model-development repository.

### Upstream scientific-backend ownership

On the development workstation, `~/Documents/LYS_PROJ1` owns the T2 lesion model.
`LYS_PROJ2` receives it only after its behavior is frozen into a versioned release with
a structured invocation/import contract, checksums, method status, and provenance.

The desktop must never execute arbitrary source from the sibling working tree. A local
developer may point an installation tool at a completed release produced there, but the
application records and uses its installed immutable copy. This makes a study portable
and prevents uncommitted changes in `LYS_PROJ1` from silently changing measurements.

## Product principles

### Subject-centred organisation

```text
Application
└── Study
    └── Subject
        ├── T1 Enhancement
        ├── T2 Lesion
        └── Combined MRI Results
```

A subject can own one native pre-Gd T1, one post-Gd T1, one native T2, multiple
versioned artifacts, multiple processing attempts, and one currently active result for
each workflow and method version.

Expected workflows are configurable per subject. A missing modality is therefore
distinguished from a workflow explicitly marked not applicable.

### Human review is explicit

Automatic outputs are immutable drafts, never ground truth. Use unambiguous labels:

- Draft brain mask
- Draft lesion mask
- Awaiting review
- Human approved
- Rejected
- Superseded
- Result outdated
- Provisional measurement
- Approved measurement
- Blocked

Do not use `Final`, `Finished`, or `Valid` unless all corresponding review and method
gates have passed.

### Blinded review is explicit

A study can be created in `BLINDED` review mode. While it remains blinded:

- subject group is nullable and should normally remain unassigned;
- group fields, filters, labels, and grouped charts are hidden from reviewers;
- reviewer identity is still required for audit history;
- each review decision records whether it was made while the study was blinded; and
- approved exports may omit group, but grouped summaries are unavailable.

Unblinding is a deliberate audited study action, not a display toggle. It requires
confirmation and may then import or assign groups by stable subject code. The import must
report duplicates, unknown subjects, and missing assignments before committing. Once
groups have been revealed, hiding the column again must not claim that subsequent review
was blinded. Existing decisions retain their original blinding state.

### Approval has separate dimensions

The database and UI must not collapse these independent questions:

| Dimension | Question | Example states |
|---|---|---|
| Artifact state | What version of the file is active? | draft, approved, rejected, superseded |
| Review state | Did a named person make a decision? | awaiting review, approved, rejected |
| Method state | Is the scientific method eligible for official use? | method development, control calibrated, approved, deprecated |
| Result state | Can this measurement be reported as official? | provisional, awaiting review, approved, outdated, blocked |
| Job state | What happened during execution? | queued, running, interrupted, failed, succeeded, cancelled |

A human can approve the quality of an artifact produced by a method still under
development. That approval does not turn the resulting measurement into an approved
scientific endpoint. A result is official only when:

1. every required upstream artifact is the currently approved version;
2. every required review decision is approved;
3. the exact method record is approved for that result type; and
4. the result itself has passed any required result review.

The current T1 enhancement implementation remains provisional until the signal-
preservation work in `docs/enhancement_quantification.md` is complete.

A method-development record may be explicitly enabled for provisional runs so the
scientific team can validate it through the application. It is visually marked on every
run and result. Deprecated or incompatible methods are not executable. Execution
eligibility is therefore not a claim that the method or measurement is approved.

### Scientific logic remains outside Qt

```text
PySide6 page
    ↓
View model and application service
    ↓
Workflow policy and scientific backend adapter
    ↓
Artifact, method, job, and provenance records
    ↓
SQLite transaction
    ↓
UI refresh
```

Widgets render state and submit requests. They never calculate masks, registrations,
volumes, enhancement metrics, approval eligibility, or invalidation.
Services return typed data rather than requiring the UI to parse console output.

## MVP scope

### Included

- local study creation, opening, recent-study history, and version checks;
- subject creation and manifest import;
- subject table, filters, expected-workflow settings, and audit history;
- T1 import, validation, draft brain-mask generation or import, review, rigid
  post-to-pre registration, registration review, and semi-quantitative measurement;
- T2 import, released lesion-mask import, optional invocation of a validated frozen
  model release, lesion-mask review, and native-space lesion volume;
- subject results, cohort tables, descriptive charts, CSV export, QC report, and
  reproducibility bundle;
- background jobs, cancellation, crash recovery, structured errors, and audit events;
- an embedded slice viewer for review plus ITK-SNAP handoff for correction.

### Explicitly excluded

- model training, architecture selection, experiment grids, and locked-test evaluation;
- atlas registration and atlas-region quantification;
- arbitrary workflow construction or user-editable scientific formulas;
- absolute T1, gadolinium concentration, `Ktrans`, `Ki`, or DCE analysis;
- validated permeability claims or automatic biological interpretation;
- inferential statistics without a pre-approved statistical plan;
- additional modalities or scientific workflows without a separate explicit scope
  decision;
- cloud accounts, multi-user authentication, remote clusters, plugin marketplaces, and
  installers for every operating system.

## Study storage contract

### Target study root

Creating a study produces a self-contained state and derivatives directory:

```text
study-root/
├── project.sqlite
├── project.json
├── imports/
├── work/
├── outputs/
├── reports/
├── exports/
└── logs/
```

- `project.sqlite` is the canonical mutable state and uses ordered migrations.
- `project.json` is a small portable identity/version manifest, not a second editable
  source of truth.
- `imports/` contains import manifests and optional managed copies, never silent copies.
- `work/` contains temporary job directories that cannot become active artifacts until
  a completion manifest is validated.
- `outputs/` contains immutable, versioned artifacts and measurements.
- `reports/`, `exports/`, and `logs/` contain their named generated products.

Raw data remain outside the study root by default. The application stores absolute
source paths, file hashes, and import timestamps. A user may explicitly request a
managed copy in a later import flow, but copying must never be implicit.

Mounted local hard drives are supported. A disconnected source drive does not corrupt
the study: records remain visible and affected actions become blocked with a reconnect
or reselect instruction. The SQLite database itself should live on a reliable local or
locally mounted filesystem with working file locks. Concurrent access from multiple
machines or an unreliable network share is outside the MVP.

### Schema-v1 compatibility

The `.lysbbb` single-file project is a legacy prototype and remains supported.
Implemented schema version 4 provides the study/subject/input foundation and a tested
upgrade/import path that:

1. opens schema-v1 files readably;
2. lets the user choose a target study root;
3. creates the directory structure and migrated database transactionally;
4. preserves project identity and T1/T2w source paths;
5. records a migration audit event; and
6. leaves the original file unchanged as a recovery source.

New studies use the study-root contract. The launcher continues accepting a
`.lysbbb` path only as a legacy migration entry point.

Migration builds a sibling staging directory, commits and validates the new database
and manifest, then renames the staging directory into place. A failure removes only the
new incomplete staging area and never edits raw data or the legacy database. New
migrations are append-only; schema version numbers are never reused.

### Subject discovery and MRI import contract

The schema-v1 global T1/T2w folder selectors are retained only as legacy path storage.
New studies select one MRI source root that may contain nested Bruker sessions or direct
NIfTI files. The source is scanned read-only and every proposed match is shown on a
confirmation screen before subjects or scan-input records are created. Selecting the
root itself is retained as an audited reconnectable source reference.

Supported T1 import routes are:

- a raw Bruker study/session source inventoried with the existing read-only backend,
  followed by proposed pre/post matching, user confirmation, and derived NIfTI
  conversion inside the study root; or
- direct assignment of native pre-Gd and post-Gd NIfTI files.

The implemented discovery rules are deliberately conservative:

- a Bruker session contains numeric scan directories with `acqp` and `method` files;
- subject IDs such as `C23S2_D1` are proposed from session names with explicit
  confidence; unrecognised or BD-style names remain editable and require confirmation;
- T1 pre/post is first identified from acquisition comments such as `preGd`/`postGd`,
  then from the order of an otherwise unambiguous T1 FLASH pair with a warning;
- native T2 prefers a T2-named high-resolution RARE acquisition over T2*/FcFLASH
  alternatives; tied RARE scans are low-confidence and require user choice; and
- localizers, TOF, alternative scans, experimental group, lesion side, exclusion, and
  review status are never silently promoted from filenames.

The confirmation table lets the user edit subject IDs and T1-pre/T1-post/T2 roles,
exclude every proposed scan for a discovered subject, ignore individual scans, choose
native or coronal NIfTI storage, and reverse X/Y/Z storage axes. Excluding a discovered
subject before confirmation creates no subject or scan-input record.
T1 defaults to interpolation-free coronal `RSA` storage because axis 2 then indexes the
coronal slices used by the established T1 backend. T2 defaults to its native converted
grid because the `LYS_PROJ1` release contract is defined on native T2. Storage-axis
flips also update the affine; they change array ordering without silently relabelling
world coordinates. Every choice is written to provenance and must be checked in later
image QC.

Confirmed Bruker scans are converted automatically to immutable, versioned NIfTI inputs
below `outputs/subjects/<subject>/inputs/<role>/vNNN/`. Each version contains the NIfTI
and `provenance.json` with source/output hashes, geometry, acquisition identity, and
orientation operations. Reassignment creates a new version and supersedes, rather than
deletes, the old input. A failed conversion remains visible as `FAILED` with its error.

An active subject may later be removed from the Subjects page. Removal is a reversible,
audited archive: the subject and its scan inputs disappear from active worklists, while
source MRI remains untouched and managed NIfTI/provenance files remain in the study.
The Removed subjects action restores the same persistent subject and retained inputs.
Removal is blocked while one of that subject's imports is queued or converting.

The T2 workflow subsequently accepts a released native-grid lesion mask/provenance or a
compatible frozen release package. MRI import does not invoke or reproduce the external
T2 model. CSV/TSV subject manifests remain a later transparent import format.

## Application shell and navigation

### Technology decision

Use Python 3.11, PySide6 Qt Widgets, Qt Model/View, the standard-library `sqlite3`
module behind small explicit repositories and ordered migrations, frozen dataclasses for
service/view contracts, `pathlib`, JSON manifests, `pytest`, `pytest-qt`, and worker
processes for scientific jobs. Introduce SQLAlchemy only if the explicit repository
layer becomes a demonstrated maintenance problem; do not maintain two persistence
abstractions.

The target package boundary is:

```text
src/
├── lys_bbb/          reusable scientific backend; no Qt imports
└── lys_bbb_app/
    ├── domain/       states, entities, transition and approval policies
    ├── application/  presentation and application-facing transformations
    ├── services/     typed use cases and backend adapters
    ├── infrastructure/ SQLite, files, jobs, settings, external tools
    └── ui/           shell, pages, models, dialogs, widgets, resources
```

Dependency direction is enforced in tests. Domain records do not import outer layers;
application presenters depend only on domain contracts; infrastructure does not import
services or UI; and Qt modules call the scientific backend only through services. Qt
thread bridges are UI adapters, not persistence or scientific modules. Shared state
errors belong to the domain so widgets do not import database implementations.

Workflow-specific behavior is registered behind stable service and policy interfaces.
Core artifacts, dependencies, reviews, jobs, methods, and results are keyed records
rather than modality-specific tables. The MVP registers only `t1_enhancement` and
`t2_lesion`; a future workflow can add a service adapter, state policy, and presentation
components without changing the meaning or persistence of existing T1/T2 records.
This is controlled code-level extensibility, not arbitrary workflow construction in the
user interface.

`lys_bbb_app` is the sole desktop implementation package. Keep `lys-bbb-desktop` as the
stable user-facing launcher while the internal application architecture evolves.

The main window uses Qt Widgets and Qt Model/View. It is resizable, with a target size
of 1440 × 900 and a minimum of 1180 × 760.

```text
┌───────────────────────────────────────────────────────────────┐
│ Study: EAE Mouse Study 2026     Jobs: 2     Backend ready     │
├───────────────┬───────────────────────────────────────────────┤
│ Overview      │                                               │
│ Subjects      │                Current page                   │
│ Reviews       │                                               │
│ Results       │                                               │
│ Exports       │                                               │
│ Settings      │                                               │
└───────────────┴───────────────────────────────────────────────┘
```

The left navigation is persistent. T1 and T2 do not create competing navigation
systems; they appear within subject, review, and result screens. The global header shows
the study name, study switcher, active-job count, backend status, and help action.

## Screen contracts

### Study launcher

Recent-study cards show study name, root path, subject count, pending-review count, last
opened time, schema version, availability, and an Open action. Main actions are Create
study, Open study, and Import study bundle.

Recent-study history is a per-user convenience index stored in application settings,
not canonical study state. Deleting that history must not delete a study, and a study
must always remain openable directly from its root.

Create study collects name, stable identifier, root directory, optional description,
and blinded/unblinded review mode. Initial group definitions are available only for an
unblinded study. Reopening restores all subjects, states, review decisions, blinding
state, and provenance. Missing roots and unsupported schema versions produce actionable
errors rather than new empty projects.

### Overview

Header metrics show total subjects, ready subjects, subjects needing review, blocked
subjects, and complete subjects. Cards summarize T1 Enhancement, T2 Lesion, and
Combined MRI Results. An action panel shows at most five highest-priority
clickable tasks.

A subject is `READY` when at least one expected workflow has an available user action
and no unresolved import error blocks that action. A subject is `COMPLETE` only when all
expected workflows have an approved result or are explicitly not applicable. A reviewed
but provisional result does not make a subject complete.

### Subjects

The central worklist uses a table model with columns for subject ID, group, T1 data,
brain mask, registration, T1 result, T2 data, T2 lesion, overall state, and updated time.
`T2 data` reports import, validation, and NIfTI conversion readiness. `T2 lesion` is
reserved for lesion-mask generation/import, review, and quantification state; it must
not present scan conversion as lesion-segmentation progress.
Filters include subject search, group, workflow, state, needs review, blocked, complete,
and missing data.

In blinded mode, the group column and group filter are absent rather than populated with
encoded group labels. An explicit `Unblind and assign groups` action starts the confirmed,
audited unblinding flow. Subjects without an assignment display `Unassigned` after
unblinding.

The implemented input foundation supports row multi-selection and an explicit batch
storage-axis flip. A batch flip operates on the chosen active T1/T2 scope, composes the
selected X/Y/Z reversal with the recorded import orientation, and creates new versioned
NIfTI/provenance outputs. It never edits raw data or an existing version in place.
The prior good version remains active until its replacement converts successfully; a
failed replacement is retained for audit without displacing the usable input.
Opening MRI in ITK-SNAP is available for one selected subject and asks which active
converted input to use when that subject has multiple modalities.

Later MVP bulk actions add validation, ready-job execution, selected-result export,
group assignment, and marking a workflow not applicable. Bulk approval is prohibited.

### Subject workspace

The header shows subject code, group, metadata, overall state, and safe subject actions.
It can open an active converted MRI in ITK-SNAP and rename the visible subject code.
Renaming preserves the stable subject database ID, historical provenance, and existing
managed file paths; it records an audit event rather than moving scientific artifacts.
Subject metadata is presented as responsive key/value rows. Long filesystem paths are
middle-elided only when the available width is insufficient, with the complete value
retained in the tooltip. The workspace uses the available window height and falls back
to vertical scrolling rather than allowing content to be clipped outside the viewport.
Tabs are Summary, Inputs, T1 Enhancement, T2 Lesion, Results, and History.
Each workflow card shows purpose, progression, current state, thumbnail, next action,
blocked reason, last update, and details action.

### Reviews

One queue serves brain masks, registrations, T2 lesion masks, and results awaiting
approval. It contains a queue pane, image viewer, and review panel.

Minimum viewer controls are previous/next item, previous/next slice, slice number, zoom,
pan, mask visibility, opacity, outline/fill, image window, and reset. The MVP viewer is a
`QGraphicsView`-based single-slice viewer; it is not an ITK-SNAP replacement.

Corrections use this safe sequence:

1. copy an immutable draft to a new editable artifact;
2. open the image and editable copy in ITK-SNAP;
3. refresh and validate grid, labels, and checksum after save;
4. register the corrected file as a new artifact version; and
5. record a review decision without overwriting the prediction.

Approval records reviewer identity and timestamp. Rejection additionally requires an
issue code and notes. Review history shows artifact version, reviewer, decision, time,
note, and superseding artifact.

Standard issue categories are:

- brain/T2 mask: missing region, false positive, inaccurate boundary, severe artifact,
  wrong subject, wrong orientation, or other;
- registration: misalignment, rotation mismatch, translation mismatch, deformation
  concern, intensity issue, incomplete field of view, or other.

### Results

The subject table shows group, T1 enhancement, T2 lesion volume, approval state, and
method version. Missing values display Not available, Awaiting
review, Blocked, or Not applicable; they are never converted to zero.

Subject detail shows value, unit, state, method, upstream approved artifacts, reviewer,
processing date, and warnings. Cohort summaries may show count, mean, median, standard
deviation, standard error, minimum, maximum, and missing count, plus descriptive dot,
box, histogram, and missingness plots.

While blinded, results omit the group column and show only whole-cohort descriptive
views. Grouped plots and comparisons become available only after audited unblinding and
successful group assignment.

### Exports

Approved-results CSV excludes provisional results by default. If the user opts in,
provisional records include an explicit state and method-status column. Pre-export
confirmation reports how many selected subjects are approved, provisional, pending QC,
blocked, or missing.

A blinded study may export approved subject-level measurements without group columns.
Any export requesting groups or grouped summaries must require unblinding and validated
group assignments. Export provenance records whether the study was blinded, unblinded,
or partially unassigned when the export was created.

QC reports are HTML or PDF and include study status, review decisions, warnings,
representative images, exclusions, and method versions. Reproducibility bundles contain:

```text
study_manifest.json
subjects.csv
artifacts.csv
results.csv
reviews.csv
jobs.csv
methods.json
model_releases.json
software.json
checksums.sha256
reports/
```

### Settings

Standard settings cover external editor path, default export directory, automatic
project backup, reviewer display name, appearance, CPU workers, MPS use, temporary work
directory, and maximum concurrent jobs.

Review settings show the study's blinding state. Preview mode may simulate hiding and
revealing groups, but a persistent study changes from blinded to unblinded only through
the audited study action described above.

Model Releases shows release ID, version, validation status, checksums, install date,
source, and compatible input type, with Install, Validate, Remove, and View provenance
actions. Expert mode can show logs, database diagnostics, environment reports, method
manifests, and controlled invalidation tools; it does not expose arbitrary scientific
parameters.

### First visually complete build

The first end-to-end visual build contains six coherent experiences:

1. Study launcher with recent, create, open, and legacy migration actions.
2. Overview with readiness metrics, T1/T2 cards, and prioritized next actions.
3. Subjects with the central filterable status table.
4. Subject workspace with workflow progress cards, next actions, and history.
5. Review and QC with queue, slice viewer, overlay controls, issue panel, and decisions.
6. Results and export with subject/cohort tables, provenance, safeguards, and export
   actions.

Settings remains accessible from the shell but does not block visual completion of
these six primary experiences.

## Workflow contracts

### T1 Enhancement

Required inputs are native pre-Gd T1, native post-Gd T1, subject identity, and available
acquisition metadata. Native pre-Gd T1 is the reference space. Post-Gd is rigidly
registered to pre-Gd, and the approved pre-space brain mask is applied to both.

```text
NOT_AVAILABLE → IMPORTED → INPUTS_VALIDATED
    → MASK_READY_TO_GENERATE → MASK_GENERATING → MASK_REVIEW_REQUIRED
    → MASK_APPROVED → REGISTRATION_READY → REGISTRATION_RUNNING
    → REGISTRATION_REVIEW_REQUIRED → REGISTRATION_APPROVED
    → QUANTIFICATION_READY → QUANTIFICATION_RUNNING
    → RESULT_REVIEW_REQUIRED → RESULT_APPROVED → COMPLETE
```

Failure branches include validation failed, mask rejected, registration rejected,
result rejected, outdated, blocked, interrupted, and failed. Rejection never deletes
the associated artifact.

The input screen reports paths, hashes, dimensions, spacing, orientation, affine
compatibility, metadata, warnings, and technical detail. Brain-mask and registration
screens expose generator/method version, artifacts, metrics, thumbnails, history, and
review actions.

The result is labelled `Semi-quantitative T1-weighted gadolinium enhancement`. It must
show reference space, approved brain mask, registered post-Gd image, normalization,
analysis volume, excluded voxels, warnings, method version, and result state. It must
never be labelled permeability, absolute T1, `Ktrans`, or `Ki`.

### T2 Lesion

Supported paths are import of a released T2-space mask plus provenance, or invocation
of an installed frozen RatLesNetV2 release package. Training and release selection are
outside the application.

```text
NOT_AVAILABLE → T2_IMPORTED → T2_VALIDATED
    → MASK_READY → MASK_GENERATING or MASK_IMPORTED
    → MASK_REVIEW_REQUIRED → MASK_APPROVED
    → QUANTIFICATION_READY → QUANTIFICATION_RUNNING
    → RESULT_REVIEW_REQUIRED → RESULT_APPROVED → COMPLETE
```

Failure branches include validation failed, model release missing, provenance invalid,
mask rejected, outdated, blocked, interrupted, and failed.

Native-space lesion volume requires no T2-to-T1 registration. Required result fields are
lesion voxel count, lesion volume in mm³, approved mask artifact, scan spacing, release
or import provenance, reviewer, review date, warnings, and method version. The release
contract and ownership boundary are authoritative in `docs/t2_lesion_integration.md`.

## Canonical data model

The MVP SQLite database contains these principal entities:

| Entity | Purpose |
|---|---|
| Study | Identity, root, description, schema version, blinding state, timestamps |
| Subject | Stable code, group, metadata, expected workflows |
| Artifact | Immutable file identity, type, state, version, hash, creator |
| Artifact dependency | Directed provenance and invalidation edges |
| Review decision | Reviewer, decision, issue, notes, blinding state, timestamp |
| Processing job/event | Execution state, stage progress, errors, logs |
| Result | Typed value/unit/state linked to method and artifacts |
| Method record | Name, immutable version, status, config, code/environment |
| Model release | Validated external release identity and checksums |
| Audit event | Append-only record of important user and system actions |

Required fields include:

- Study: UUID, stable study identifier, name, root path, description, schema version,
  `BLINDED`/`UNBLINDED` review state, optional unblinding time/user, created time, and
  updated time.
- Subject: UUID, study ID, unique subject code, optional group, JSON metadata, and
  timestamps. Expected workflows are child records keyed by registered workflow ID,
  not fixed modality booleans.
- Artifact: UUID, study/subject IDs, type, path, state, integer version, file hash,
  creator, method ID, timestamps, and optional superseding artifact.
- Review: UUID, artifact ID, reviewer, decision, optional issue code, notes, study
  blinding state at decision time, and time.
- Job: UUID, study/optional subject IDs, job type, state, stage, progress values, start/
  finish times, structured error, and log path.
- Result: UUID, study/subject IDs, type, typed value/unit or structured value payload,
  state, method ID, source artifact IDs, creation time, and optional approval time.
- Method: UUID, name, immutable version, status, JSON configuration, code revision, and
  environment manifest.

Suggested tables are `studies`, `subjects`, `subject_metadata`, `subject_workflows`,
`artifacts`, `artifact_dependencies`, `reviews`, `jobs`, `job_events`, `results`,
`methods`, `model_releases`, `audit_events`, and `schema_migrations`.

Important uniqueness and indexes include subject code within study; workflow key within
subject; artifact by subject, type, version, and state; review by artifact; job by state;
result by subject, type, and method; dependency by source artifact; and audit event by
timestamp.

## Artifact dependency and invalidation

Every derived artifact and result records exact source artifact IDs and method ID. If an
approved dependency changes, dependent results become `OUTDATED`; they are never
deleted or silently updated.

```text
T1 enhancement result
├── approved brain mask artifact
├── approved registration artifact
├── native pre-Gd image artifact
├── registered post-Gd artifact
└── method record
```

The UI explains the cause and next action, for example: `This result is outdated because
the approved brain mask changed. Run quantification again.` A newly approved artifact
supersedes the old active artifact but preserves both files and histories.

## Application services

Stable typed services own business actions:

- `ProjectService`: create, validate, open, migrate, back up, and list recent studies;
- `SubjectService`: create subjects, import manifests, assign groups, and build summaries;
- `T1AnalysisService`: import/validate T1, start mask/registration/quantification jobs;
- `T2LesionService`: import T2/masks, validate releases, start inference/volume jobs;
- `ReviewService`: approve/reject artifact versions and record reviewer decisions;
- `ResultService`: enforce approval gates, invalidate dependencies, and build cohorts;
- `ExportService`: produce approved tables, QC reports, and reproducibility bundles;
- `JobService`: submit, cancel, recover, and observe background work.

Job-starting service methods return a job ID. Service results are dataclasses or other
typed contracts. Errors use a stable code, severity, user message, suggested action,
technical detail, and affected path.

## Background jobs

Scientific work runs in worker processes, never on the Qt event loop.

```text
UI submits request → job record committed → worker process launched
    → structured stage events → completion manifest validated
    → artifacts committed transactionally → UI notified and refreshed
```

Stage names matter more than approximate percentages. Cancellation requests graceful
termination, lets the backend clean its work directory, and never promotes partial
outputs. At startup, jobs left `RUNNING` become `INTERRUPTED`; files alone never prove
success. Recovery checks a structured completion manifest before offering a retry or
safe import.

## Errors and audit history

Primary errors state the consequence and a useful action in plain language. Raw
tracebacks appear only in expandable technical detail and support bundles. For example:

```text
The lesion mask cannot be imported because its dimensions do not match the T2 scan.
Confirm that the mask belongs to this subject or select the correct T2 scan.
```

Important actions append audit events: study creation/migration, subject import, source
replacement, job start/completion/interruption, artifact creation/approval/rejection,
result invalidation, study unblinding, group import/assignment, model-release
installation, backup, and export.

## Visual and accessibility rules

Use a light neutral background, white cards, dark navy navigation, teal/green for ready
or approved, amber for review, red for failure/rejection, blue for processing, grey for
unavailable, and purple/amber for outdated. Colour is always paired with text and an
icon. Use an 8 px spacing system, visible keyboard focus, selectable technical paths,
and labels that do not rely on colour alone.

## Testing contract

- Domain tests cover transitions, blocked actions, approvals, supersession, dependency
  invalidation, and missing-input semantics.
- Service tests use synthetic files and mocked adapters for imports, geometry errors,
  non-binary masks, duplicates, missing provenance, backend failure, interruption, and
  invalid release packages.
- UI tests use `pytest-qt` for navigation, filters, disabled-action explanations, review
  decisions, outdated warnings, job refresh, and export confirmation.
- Scientific tests remain in `src/lys_bbb` and cover measurements, geometry,
  registration, mask rules, volume, and provenance. UI tests do not duplicate them.

## Implementation phases

1. **Application shell and MRI input foundation** — study-root creation/opening, recent
   studies, schema-v1/v2 migration, read-only source discovery, editable subject/role/
   orientation proposals, versioned NIfTI conversion, blinded-review state, deferred
   group assignment, main navigation, subject table, and audit log.
2. **Artifact and workflow state model** — artifacts, dependencies, workflow policies,
   status badges, subject workspace, approval gates, and outdated handling.
3. **T1 validation and mask review** — converted subject-owned T1 validation, draft
   mask generation/import, slice viewer, overlay, decisions, and ITK-SNAP correction flow.
4. **Registration and T1 quantification** — background rigid registration, QC/review,
   provisional measurement, method status, and subject result display.
5. **T2 lesion integration** — converted T2 validation, release validation, mask import/inference,
   review, provenance, and native-space lesion volume.
6. **Results and exports** — cohort table, descriptive summaries, approved CSV, QC
   report, and reproducibility bundle.

The implemented input slice succeeds when a user creates a study, discovers or edits
subjects and scan roles from a selected MRI root, converts the confirmed inputs, closes
the application, reopens it, and sees the same versioned input and setup statuses. The
next production slice is post-conversion image validation plus canonical artifact/job/
review/result state.
The full MVP succeeds only when a
non-technical user can complete both workflows, understand every blocked or
provisional state, approve eligible artifacts/results, export provenance-rich outputs,
and reopen the study without losing state.
