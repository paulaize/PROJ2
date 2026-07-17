# Desktop application

## Product requirement

The final deliverable is a desktop application for laboratory users with little or no
programming experience. The command line remains an internal development and support
interface, not the normal user experience.

Users should be able to:

1. create or open a project;
2. select T1 and T2 folders;
3. import a CSV or enter mouse metadata in a table;
4. confirm proposed file matching;
5. validate inputs in plain language;
6. start, pause, resume, and retry analysis;
7. review flagged masks and registrations;
8. launch ITK-SNAP with the correct files already loaded;
9. resume dependent stages after approval;
10. inspect and export subject/cohort results and QC.

## Layering

```text
Desktop UI
  project setup, tables, progress, review, results
        ↓
Application services
  validation, project state, user actions, error translation
        ↓
Workflow layer
  dependencies, resume, retry, resource scheduling
        ↓
Scientific backend
  current src/lys_bbb modules plus future T2/atlas modules
        ↓
Project database and versioned derivatives
```

No processing algorithm should live inside a window or widget class. A model update or
method validation must be testable without opening the application.

## User-facing stages

| Technical stage | UI label |
|---|---|
| Conversion/reorientation | Preparing images |
| Brain extraction | Detecting the brain |
| Lesion-model inference | Detecting the lesion |
| Post-to-pre registration | Aligning contrast images |
| T2-to-T1 registration | Aligning image types |
| Enhancement calculation | Measuring contrast enhancement |
| QC montage generation | Creating quality checks |

Errors should explain the consequence and available action. Python tracebacks belong in
a collapsible technical-details panel and support bundle, not the primary message.

## Project state

The application should use SQLite for mice, sessions, file assignments, processing
attempts, model versions, review decisions, checksums, errors, and timestamps. CSV/TSV
remain import/export formats. Generated QC and analysis manifests become internal
derivatives rather than files a novice must edit.

Each processing stage must be resumable. Closing the app or correcting one mask should
not discard completed unrelated work.

## Review experience

The review queue should show case, task, reason for flagging, automatic QC, and actions:

```text
Accept automatic result
Edit in ITK-SNAP
Reject result
Exclude case
Retry with robust strategy
```

When editing, the application copies the immutable prediction, opens ITK-SNAP with the
image and editable mask, validates the saved grid and labels, and writes an auditable
approval record. Registration review uses overlays/checkerboards and a decision; it is
not edited as a mask.

## Delivery sequence

1. Stabilize and validate the scientific T1 backend.
2. Define the canonical project schema and review state machine.
3. Build a minimal desktop shell for project creation, input matching, validation,
   progress, and errors.
4. Add mask/registration review and ITK-SNAP integration.
5. Add subject/cohort results and exports.
6. Integrate the released external T2 lesion model output.
7. Package for one laboratory operating system first, then expand support.

PySide6/Qt is the current preferred native framework, subject to a small packaging
prototype. A hidden workflow engine may be introduced when stage dependencies are
stable. The repository should not adopt a large orchestration framework before the
scientific stages and project state contract are settled.
