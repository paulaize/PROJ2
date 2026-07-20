# External T2 lesion integration

## Ownership boundary

The T2w brain-lesion segmentation model is developed and evaluated in the sibling
`~/Documents/LYS_PROJ1` repository. Its active development branch at the 2026-07-20
audit is `dl-ratlesnetv2-finetune`, with the executable protocol in
`docs/ratlesnetv2_lys_v1_kaggle_workflow.md` in that repository. `LYS_PROJ2` must not
contain a duplicate training pipeline, private development weights, experiment
selection, or an independent reimplementation.

The desktop MVP supports two controlled paths:

1. import a released native-T2 lesion mask and its provenance; or
2. validate and invoke an installed frozen RatLesNetV2 release package to create a draft
   mask that still requires human review.

The application never trains, tunes, chooses, or silently updates the release. T2
integration must not block T1 brain-extraction validation.

## Handoff from LYS_PROJ1

The controlled `LYS_PROJ1` workflow is designed to freeze:

- the selected loss and initialization route;
- five grouped-fold RatLesNetV2 checkpoints;
- an OOF-validation-selected probability threshold;
- an unweighted mean-probability ensemble;
- `postprocessing=none` unless a later version validates another rule; and
- dataset/split, code revision, environment, model hashes, locked-test, and evaluation
  provenance in a reproducibility artifact bundle.

That scientific artifact bundle is the source for an application release. The first
approved inference bundle is now connected through a narrow local adapter and structured
completion records. The app validates and uses that immutable release; it never imports
the sibling working tree or runs directly from an active training branch.

## Connected LYS v1 inference release

The current installed release directory on the development workstation is:

```text
/Users/paul-andreaslaize/Downloads/LYS_v1_RatLesNetV2_mac_inference
```

It contains:

```text
LYS_v1_RatLesNetV2_mac_inference/
├── bundle_manifest.json
├── frozen_spec.json
├── selected_threshold.json
├── models/
│   ├── fold_0.model
│   └── ... fold_4.model
└── RatLesNetv2/
    ├── LICENSE
    ├── UPSTREAM_GIT_COMMIT.txt
    └── lib/
```

The validator checks both specifications, the OOF-only threshold record, all five weight
hashes, folds 0–4, unweighted mean-probability ensembling, `postprocessing=none`, and the
bundled upstream revision/runtime files. It records the runtime-file hashes and refuses
execution if the registered bundle changes later. The release remains read-only and
external to the study. `LYS_PROJ2` contains only the small inference orchestration layer; weights,
training, model selection, calibration, and cross-validation are not copied here.

For each eligible study subject, the adapter adds the required singleton modality
dimension to the managed 3-D T2 NIfTI. It performs no spatial resampling or reorientation,
loads all five models, normalizes as RatLesNetV2 expects, averages their lesion
probabilities, applies threshold 0.40, performs no postprocessing, and validates that the
saved probability and mask geometry match the native input.

Outputs live in a new job-specific directory under
`outputs/t2_lesion/jobs/<job-id>/`. Each subject receives
`ensemble_probability.nii.gz`, `ensemble_mask.nii.gz`, and `qc_preview.png`; the job also
writes `inference_manifest.csv` and `inference_summary.json`. SQLite records the release,
job, source input, hashes, device, provisional voxel count/volume, and immutable artifact
version. File existence alone never promotes a failed or interrupted run.

The supplied unseen scan was reproduced through this adapter. A sandbox CPU execution
matched the prior MPS binary mask voxel-for-voxel (7,339 voxels), preserved the affine,
and differed in continuous probability by at most 1.73 × 10⁻⁶.

The T2 lesion mask and T1 brain mask solve different problems:

```text
T1 brain mask       valid tissue support for T1 analysis
T2 lesion mask      stroke pathology defined independently of gadolinium
pre/post T1         enhancement measurement
```

## Frozen model-release contract

A future general-purpose runnable release package has this logical content:

```text
release/
├── release.json
├── preprocessing.json
├── inference_contract.json
├── threshold.json
├── provenance.json
├── checksums.sha256
└── model files
```

Before installation or use, the application validates:

- release ID and immutable version;
- expected model-file count and checksums;
- input type and application compatibility;
- preprocessing and inference contracts;
- threshold and postprocessing setting;
- human-review requirement;
- model-development code revision and evaluation provenance; and
- absence of undeclared mutable runtime parameters.

Release validation creates a `model_releases` record. It does not imply that any lesion
prediction is approved. The connected v1 bundle uses the equivalent concrete files
listed above; no metadata field is invented when the release does not declare it.

## Released-mask contract

For each case/session, the released `LYS_PROJ1` contract should provide or make
derivable:

- canonical mouse and session ID;
- native T2w input image identity;
- binary lesion mask on exactly the T2w image grid;
- image/mask shape, affine, spacing, orientation, and permitted labels;
- model name, release version, code revision, and weight checksum;
- preprocessing and postprocessing description;
- automatic QC and prediction status;
- optional external review decision and reviewed-mask checksum, which the importing
  study records as provenance but does not silently treat as its own approval.

The final file naming can change, but these semantics must not.

## MVP responsibilities of this repository

For native-space lesion volume, the desktop application owns:

1. selecting and validating the matching T2w scan;
2. validating an imported mask and provenance or validating/invoking a frozen release;
3. recording the generated or imported mask as an immutable draft artifact;
4. validating native-grid shape, affine, spacing, orientation, and binary labels;
5. requiring explicit human approval or rejection;
6. preserving corrected masks as new artifact versions;
7. calculating lesion voxel count and volume in mm³ from the approved native-grid mask;
8. recording reviewer, warnings, method/release ID, checksums, and dependency links; and
9. marking the result outdated if the T2 scan, mask, or method changes.

T2-to-T1 registration is not required for the MVP native lesion-volume result.

Items 1–4, draft provenance, provisional native-space voxel/volume calculation, T2 input
invalidation, and ITK-SNAP inspection are implemented for generated masks. Items 5–9 are
only partially complete: the current value is explicitly provisional until immutable
review/correction, approval, dependency records, and approved-result export are added.

## Post-MVP T2-to-T1 linkage

Later lesion-associated T1 analysis may register native T2 to native pre-Gd T1,
visually approve the multimodal registration, transfer the lesion mask with nearest-
neighbour interpolation, and calculate lesion/perilesional enhancement metrics. That is
a separate reviewed workflow and must not block native-space lesion volume.

```text
T2 lesion mask ── native T2
       │
       └─ nearest-neighbour through approved T2→T1 transform
                            ↓
                     native pre-Gd T1
                            ↓
             lesion-associated enhancement metrics
```

Native T2 lesion volume remains the primary T2 MVP measurement. Do not repeatedly
resample lesion or T1 intensity images.

## Post-MVP linked metrics

Once the transform is validated, useful outputs include:

- native T2 lesion volume and morphology;
- mean, median, and 95th-percentile enhancement inside lesion;
- enhancing lesion volume and percent of lesion enhancing;
- integrated positive enhancement inside and outside lesion;
- lesion-to-mirrored-contralateral ratio;
- physical-distance perilesional rings;
- ipsilateral and contralateral outside-lesion brain;
- D1-to-D7 scalar changes.

Voxelwise persistent/resolved/new compartments require an additional validated D1-to-D7
registration. They must not be inferred from scalar deltas alone.

## Atlas relationship

Atlas mapping is optional and later. An MRI-compatible atlas may register through T2,
then have its labels composed into pre-Gd T1 space. Enhancement remains measured in
native pre-Gd T1. Start with larger regions supported by the MRI resolution; do not imply
fine anatomical precision from small atlas labels.

## MVP integration acceptance

The external link is ready only when a reviewed representative set demonstrates correct
subject matching, release/checksum validation, native-grid mask validation, immutable
draft creation, human review, corrected-mask versioning, native-space volume, dependency
invalidation, provenance export, and structured failure behavior. A successful model
process or a lesion prediction file alone is not sufficient.

T2-to-T1 alignment, nearest-neighbour transfer, and lesion-associated enhancement have
their own later validation gate.
