# Current project state

Last audited: 2026-07-20. This file records operational facts, not future design.

## Readiness summary

The T1 backend works on synthetic tests and development cases, but the cohort is not
ready for biological interpretation. The final analysis manifest currently includes
zero cases because reviewed T1 brain masks are unavailable.

| Area | Current state |
|---|---|
| Raw inventory | 36 sessions, 285 scans, no inventory failures |
| Intended T1 cases | 35 case IDs |
| Converted T1 pairs | 34 |
| Rigid registration outputs | 34; numeric similarity improved in all cases |
| Explicit registration approvals | 0 |
| MouseBrainExtractor pre-labels | 8 |
| Explicitly approved T1 brain masks | 0 |
| Final analysis cases | 0 |
| Frozen Colab benchmark inputs | 10 T1 images packaged; primary GPU run completed successfully |
| Colab benchmark implementation | Three primary models, two mismatched controls, and a separate RS2 correction experiment |
| Brain-extraction decision | RS2-Net is the visual front-runner; corrected-mask selection and reviewed-reference scoring remain pending |
| Desktop application | Schema-v3 study roots, recent studies, read-only Bruker/NIfTI discovery, editable subject/role/orientation review, versioned NIfTI conversion with provenance, persistent subjects/input state, blinding/groups/audit, plus the synthetic downstream workflow preview |
| T2 desktop workflow | Not implemented; controlled model development is active in sibling `LYS_PROJ1`, but no frozen app release is installed here |
| Tests | Test suite passes; biological validation is separate |

The data contain static pre/post `T1_FLASH_3D_Glymphatic_Sag` scans. They do not
contain the multi-TR or dynamic acquisitions required for quantitative T1 mapping or
DCE permeability modeling.

## Dataset exceptions

- `C23S2_D1` failed T1 conversion because `brkraw` reported no valid ParaVision study.
- `C26S5_D1` has no usable T1 pre/post pair.
- `C23S3` has both `D1` and `D1_bis`; one must be selected before a unique D1-to-D7
  comparison is possible.
- Treatment groups remain blinded.

## Brain masks

Existing MouseBrainExtractor masks cover:

```text
C23S5_D1
C24S3_D1
C24S4_D1
C24S4_D7
C25S1_D1
C26S1_D1
C26S2_D1
C26S3_D7
```

Seven corresponding editable masks are unchanged copies of their pre-label. The
`C23S5_D1` mask was edited and marked with the legacy `_done` filename, but it still
lacks an explicit review approval. Filename state is therefore insufficient.

Current final gate:

```text
8  mask_needs_review
26 missing_brain_mask
1  missing_conversion
0  included
```

Largest-component cleanup and an eight-case testing-only cohort have run successfully.
Those masks and cohort outputs are engineering artifacts, not accepted labels or
biological results.

The first model-comparison cohort is frozen in
`config/brain_extraction_benchmark_10.txt`. Its 10-image local upload archive and exact
Colab notebook generated MBE isotropic, MBE anisotropic, and RS2-Net masks successfully
under one manifest/output contract. The downloaded masks have not yet been reviewed or
scored against accepted references, so no benchmark winner has been selected.

An optional companion notebook is ready for two explicitly mismatched diagnostic
controls: the CAMRI rodent T2/T2* U-Net and human-T1 deepbet. Its outputs use the same
manifest and native-grid mask contract, and the local review launcher can combine both
archives into one five-model ITK-SNAP comparison.

The two controls performed worse than RS2-Net on visual inspection. RS2-Net closely
follows the brain but recurrently includes a bright superior skull cap, most prominently
in high-contrast images where a dark M-shaped brain--skull separation is visible.
Increasing the RS2 probability threshold did not remove this false positive reliably.

`notebooks/brain_extraction_rs2_refinement_colab.ipynb` is now ready to rerun RS2 once
and compare three T1-guided postprocessors on the same ten images: a direct M-seam cut,
marker-controlled watershed, and random walker. It preserves raw RS2, writes every
candidate separately, generates interactive and durable QC, and packages all four masks
for the existing ITK-SNAP review launcher. The algorithms were exercised locally on the
downloaded ten-case results, but the exact notebook still awaits its first Colab run and
formal human selection.

## Registration and quantification

Rigid post-Gd-to-pre-Gd registration is available for each converted pair. Improved
cross-correlation is a useful automatic check, but not a human pass. The least similar
registered cases deserve early visual review.

Pair and cohort quantification currently implement:

- rigid registration;
- supplied pre-space mask enforcement;
- smooth bias correction;
- independent masked-median normalization;
- difference, ratio, and percent-enhancement maps;
- whole-mask, side-aware, lesion-hook, and D1-to-D7 summary metrics.

The bias-correction and normalization choices may suppress broad biological
enhancement. They remain provisional until the validation experiments in
`docs/enhancement_quantification.md` pass.

## Desktop foundation

The PySide6 input-foundation milestone is implemented on
`feat/pyside-project-foundation`. The launcher creates or opens a schema-v5 study root,
records recent studies, persists subjects and their expected T1/T2 workflows, stores T1
and T2 source-root references, and restores the same state after reopening. Source image
folders may live on mounted hard drives and are referenced in place; project setup does
not copy or modify their contents, and temporarily unavailable paths remain recorded.

Study blinding is durable and one-way. A blinded study stores subjects without requiring
groups and hides group information in the UI. Explicit unblinding records reviewer and
time; group mappings may then be saved while individual subjects remain `Unassigned`.
Study creation/opening, subject discovery/creation/removal/restoration, input-folder
selection, MRI import, conversion success/failure, supersession, unblinding, and group
assignment create append-only audit events visible from the Subjects page. Subject
removal is a reversible archive: source and managed input artifacts are retained.

Selecting an MRI root now scans nested Bruker sessions from their numeric `acqp`/`method`
scan folders and recognisable direct NIfTI inputs. It proposes subject IDs and T1
pre/post/T2 roles, gives preference to high-resolution RARE for native T2 rather than
T2*, and requires a confirmation table where the user can correct identities, roles,
coronal/native storage, and X/Y/Z storage-axis flips. Confirmed inputs are converted off
the GUI thread into versioned NIfTI/provenance directories inside the study. Source data
remain read-only on their original drive. Mask generation, registration, review,
quantification, robust process cancellation, and crash recovery are not connected yet.

The Subjects worklist now supports multi-selection and versioned batch axis flips. A
single selected subject or its workspace can open any active converted T1/T2 input in
ITK-SNAP. Subject names can be changed from the workspace without changing stable IDs or
moving historical files; launch, rename, removal, and restoration actions are audited.
The subject workspace now responds to the available viewport, lays out metadata in
stacked key/value rows, and middle-elides long paths while preserving their full value
in a tooltip. Its workflow cards and tabs contract with smaller windows, with vertical
scrolling used when the complete page cannot fit safely.
The Subjects table now reports T2 import/conversion in a dedicated `T2 data` column.
The separate `T2 lesion` column is reserved for the future released segmentation
workflow and remains `Not started` in persistent studies until that backend is connected.
The desktop package has an enforced dependency direction: shared records and errors are
domain-owned, presenters live in `application`, persistence and external-tool adapters
remain non-Qt infrastructure, services coordinate use cases, and Qt workers/pages stay
under `ui`. The subject workspace is isolated from the general page module, and the Qt
shell no longer imports the scientific backend or legacy database implementation
directly.

The persistent subject Inputs tab now provides the first post-conversion workflow step.
It lists active T1-pre, T1-post, and T2 versions with managed/source paths, dimensions,
spacing, axis codes, import transforms, checksums, validation state, and plain-language
issues. Validation runs off the GUI thread, checks each managed NIfTI against its
conversion provenance, records reviewer/time and an audit event, and survives reopening.
A new flipped or replacement version starts at `Input review required`; successfully
validated T1/T2 inputs become `Ready for analysis`. The UI shows the next brain-mask and
lesion-mask artifact steps honestly as not yet connected.

This milestone contains no scientific processing inside Qt widgets and does not invoke
or reproduce the external T2 lesion model. Production pipeline execution, persisted
review queues, metadata editing, results, and exports remain future desktop milestones.

The application also has a connected design-preview mode (`lys-bbb-desktop --demo`). It
uses immutable typed view models and explicitly synthetic subjects to render the planned
launcher, persistent shell, Overview, Subjects, Subject Workspace, Review/QC,
Results/Export, and Settings screens. Subject filtering, workspace navigation,
subject-focused review routing, local preview decisions, result filtering, and preview
export actions are connected. The preview also has a blinded-review toggle that hides
group columns/filters, labels the subject workspace, collapses cohort plots, and warns
that grouped exports require audited unblinding. These interactions are intentionally
non-persistent and do not imply that production artifacts, approvals, results, jobs, or
exports exist.

## Adopted desktop MVP

The 2026-07-20 MVP contract expands the desktop target from a T1/T2 folder shell into a
subject-centred application with two workflows: T1 enhancement and T2 lesion volume.
The authoritative product contract is `docs/desktop_application.md`.

New projects now use a study root containing
`project.sqlite`, `project.json`, imports, job workspaces, immutable outputs, reports,
exports, and logs. Existing schema-v1 `.lysbbb` files remain a supported migration input
and are not overwritten during migration. Schema version 2 implements the
study/subject/audit foundation.

Durable study, subject, expected-workflow, group, blinding, input-folder, scan-input
version, conversion result/failure, audit, and recent-study state is implemented.
General artifact, dependency, review, job, method, and result tables remain Phase 2
work. Converted scan inputs are not approvals and do not create scientific results.

### Upstream repository state

The local `~/Documents/LYS_PROJ1` checkout is the upstream scientific-development source.
Its active `dl-ratlesnetv2-finetune` workflow compares Tversky and CE+Dice across five
grouped LYS development folds, evaluates direct versus external-mouse initialization,
then freezes five models, an OOF-selected threshold, an unweighted mean-probability
ensemble, and `postprocessing=none` before one locked-test evaluation.

No frozen T2 application release from that development workflow is currently installed
in `LYS_PROJ2`.

## Metadata

The editable study metadata table contains 35 rows. Group, lesion side, lesion-mask
path, explicit inclusion, and review fields are currently empty. These values cannot be
inferred safely from folder names.

## Branch history

The pre-cleanup branches are a single stack. Each branch is an intermediate checkpoint,
not a maintained product line:

```text
7248265 main
  └─ e560cc8 workflow-status-orchestration
       └─ 6e89e62 candidate mask validation
            └─ b27b16f brain-mask-model-integration
                 └─ 08af420 study-metadata-scaffold
                      └─ 8f58e8e mask-review-workflow
```

Their historical purposes were:

| Branch | Added capability |
|---|---|
| `main` | Initial inventory, conversion, registration, QC, and quantification |
| `workflow-status-orchestration` | Readiness report |
| `brain-mask-model-integration` | Candidate-mask validation and postprocessing |
| `study-metadata-scaffold` | Editable study metadata and analysis-manifest merge |
| `mask-review-workflow` | Explicit manual mask and registration review |

The latest tip contains all earlier changes. Cleanup should be consolidated into one
baseline rather than copied into every historical branch. Old feature branches can be
deleted after the consolidated tip is safely published on `main`.

## Generated-state warning

MRI outputs and reports are ignored by Git and shared by all local branches. Several
current dashboard/manifests were generated on 2026-07-08 or 2026-07-09, before the
2026-07-15 mask-review commit. They must be regenerated before being used as current
workflow evidence. Preserve manual masks and decisions while regenerating derived
reports.

## Scientific validation milestone

The next milestone is complete when the same representative cases have been run through
the selected open-weight models in Colab, outputs satisfy a common grid/provenance
contract, reviewed references exist for quantitative comparison, and a model-selection
report identifies failure modes and the preferred pre-label generator.

## Desktop implementation milestone

The implemented input slice lets a user create a study root, migrate schema-v1/v2
state, select an external-drive MRI root, review automatically discovered subjects and
scan roles, convert confirmed Bruker/NIfTI inputs, close and reopen the application with
the same versioned input state, and inspect the audit history. The next state milestone
is the canonical artifact/review/job/result layer and a real post-conversion image QC
screen.
