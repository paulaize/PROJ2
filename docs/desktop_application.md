# Desktop application product contract

This document defines the stable product boundary. It intentionally does not list
aspirational classes, database tables, or screens as though they already exist. Current
implementation facts and the immediate milestone live in `current_state.md`.

## Product objective

A non-technical researcher must be able to:

1. create or reopen a study;
2. import subject-owned T1 and T2 MRI data without modifying raw files;
3. understand the state and next action for every subject;
4. run registered, versioned scientific workflows;
5. review, reject, or correct automatic artifacts;
6. approve eligible masks, registrations, and results explicitly;
7. inspect subject and cohort results without hiding missing or provisional data; and
8. export approved measurements with QC and reproducibility provenance.

The application owns two workflows only:

- semi-quantitative T1-weighted gadolinium enhancement;
- T2 lesion segmentation and native-space lesion volume.

It is a workflow runner and review system, not a model-development interface.

## Product principles

### Subject-centred state

```text
Study
└── Subject
    ├── Inputs
    ├── T1 Enhancement
    ├── T2 Lesion
    ├── Results
    └── History
```

Visible subject names may change, but stable subject IDs own inputs, artifacts, jobs,
decisions, and results. Workflows can be marked not applicable per subject.

### Automatic is not approved

Use explicit language:

- Draft mask
- Awaiting review
- Human approved
- Rejected
- Superseded
- Provisional result
- Approved result
- Result outdated

Never infer approval from file presence, a successful job, a filename, or a previous
review of another artifact version.

### Approval has separate dimensions

| Dimension | Question |
|---|---|
| Job | Did execution complete under its contract? |
| Artifact | Did a researcher accept this exact file version? |
| Method | Is this scientific method eligible for official use? |
| Result | Were its method and exact dependencies eligible and approved? |

A successful inference job creates a draft. It does not create ground truth or an
official measurement.

### Blinded review

Blinded studies may omit groups. Group fields and grouped summaries remain hidden until
an explicit audited unblinding action. Reviewer identity is never hidden. Subject-level
workflow execution and review can proceed without a group assignment.

### Scientific code stays outside Qt

```text
PySide6 widget → application service → scientific backend/repository
              ← typed result/state ←
```

Qt widgets collect choices and display state. They do not manipulate image arrays,
calculate measurements, parse arbitrary console text, or write scientific records.

## Study storage and safety

New studies use a directory:

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

- Source MRI remains outside the study by default and is referenced read-only.
- Derived NIfTI, masks, transforms, and results live inside the study root.
- A new version never overwrites an existing artifact.
- Missing mounted drives block affected actions without deleting their records.
- The SQLite study should live on a reliable local or locally mounted filesystem.
- Multi-machine concurrent editing and remote clusters are outside the MVP.

Schema-v7 study roots are canonical. Single-file `.lysbbb` schema-v1 projects are frozen
legacy inputs supported only for non-destructive inspection and migration.

## Current application shell

Persistent navigation remains:

```text
Overview
Subjects
Reviews
Results & exports
Settings
```

The synthetic `--demo` mode is a design fixture. It is clearly labelled, writes no
study state, and is now frozen except for changes required to keep tests or terminology
consistent with production behavior.

### Launcher

Create a study, open a schema-v7 study root, resume a recent study, or migrate a legacy
`.lysbbb` file. Creation must refuse an existing target directory and leave source MRI
untouched.

### Subjects and subject workspace

The worklist is the central operational screen. It separates `T2 data` from `T2 lesion`
state and supports search, selection, subject archiving, group assignment after
unblinding, input validation, versioned axis flips, MRI viewing, and cohort T2 inference.

The subject workspace exposes inputs, workflow state, next action, artifacts, provenance,
and history. Long paths elide visually but remain available in full through a tooltip or
technical details.

### Reviews

The product uses one review concept for T1 masks, T2 masks, registrations, and eligible
results. The first complete implementation may route correction through ITK-SNAP:

1. preserve the immutable automatic draft;
2. make or select an editable copy;
3. open image and copy in ITK-SNAP;
4. validate the saved grid, labels, and checksum;
5. register the correction as a new immutable artifact;
6. record accept/reject decision against the exact version.

Approval records reviewer, time, decision, and study blinding state. Rejection also
requires an issue code and notes. Bulk approval is prohibited.

### Results and exports

Missing values display `Not available`, `Awaiting review`, `Blocked`, or `Not
applicable`; never zero. Every displayed value includes state, unit, method, dependencies,
warnings, and reviewer information where applicable.

Approved-results CSV excludes provisional and outdated values by default. A user may
explicitly include provisional values only when their state and method status are
separate columns. Group columns require audited unblinding.

## Workflow contracts

### T2 lesion

```text
T2 imported → input validated → inference/import → draft mask
→ review or correction → approved mask → official native-space volume
→ approved result or outdated result
```

Native lesion volume does not require T2-to-T1 registration. The official result must
record voxel count, volume in mm³, scan spacing, approved-mask artifact and checksum,
model/import provenance, method version, reviewer, approval time, and warnings.

Changing the source T2, active approved mask, or method/release invalidates the result.
Details of the current release are in `t2_lesion_integration.md`.

### T1 enhancement

```text
pre/post T1 imported → inputs validated → draft pre-T1 brain mask
→ mask review/correction/approval → rigid post-to-pre registration
→ registration review/approval → provisional enhancement method
→ subject result
```

Native pre-Gd T1 is the reference. The approved pre-space mask is used for pre-Gd and
registered post-Gd images. The UI must say `Semi-quantitative T1-weighted gadolinium
enhancement`; never permeability, absolute T1, `Ktrans`, or `Ki`.

## State and provenance requirements

The canonical database must be able to represent:

- study and stable subject identity;
- versioned inputs and artifacts;
- exact artifact dependencies and supersession;
- model/method release identity and checksums;
- background job state and structured failure;
- immutable review decisions;
- provisional, approved, rejected, and outdated results;
- append-only audit history.

Derived results record exact source IDs. Invalidation changes state to `OUTDATED`; it
does not delete history or silently recompute.

## Errors and jobs

Primary errors describe consequence and next action in plain language. Tracebacks belong
only in technical details and logs.

Scientific work must not block the Qt event loop. Current T2 work uses a Qt background
thread and persistent job records. Before the MVP handles cancellation or large cohorts,
execution should move to a worker process with graceful termination and completion-
manifest validation. At startup, an abandoned `RUNNING` job becomes `INTERRUPTED`; file
presence alone never proves success.

## MVP exclusions

- T2 model training, tuning, or checkpoint selection.
- Embedded mask painting or an ITK-SNAP replacement.
- Atlas registration or atlas-region quantification.
- T2-to-T1 quantitative dependency.
- Arbitrary workflow builders, plugins, or scientific parameter editors.
- Inferential statistics without a pre-approved plan.
- Cloud accounts, multi-user authentication, or remote clusters.
- Any additional imaging modality unless product scope is explicitly reopened.

## Development order

1. Smoke-test the completed T2 review-to-export slice on a real unseen case.
2. Finish T1 mask and exact-registration review, then provisional enhancement.
3. Connect combined results and reproducibility exports.
4. Package the application for non-developer users.

The current acceptance criteria are in `current_state.md`. No additional visual screen
is required to complete the next milestone.
