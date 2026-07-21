# T2 lesion integration

## Ownership

`~/Documents/LYS_PROJ1` owns RatLesNetV2 model development, training, model/threshold
selection, validation, and frozen releases. `LYS_PROJ2` owns release validation,
inference execution, study artifacts, human review, approved native-space volume, and
exports.

The application never trains, tunes, chooses, or silently updates a T2 model and never
imports Python from the live sibling checkout.

## Current frozen release

Development workstation location:

```text
~/Downloads/LYS_v1_RatLesNetV2_mac_inference/
├── bundle_manifest.json
├── frozen_spec.json
├── selected_threshold.json
├── models/fold_0.model ... fold_4.model
└── RatLesNetv2/
    ├── LICENSE
    ├── UPSTREAM_GIT_COMMIT.txt
    └── lib/
```

Before every run, the application checks:

- RatLesNetV2 architecture and upstream revision;
- exactly folds 0–4 and every model SHA-256;
- OOF-validation threshold selection and `locked_test_used=false`;
- threshold 0.40;
- unweighted mean lesion probability;
- `postprocessing=none`;
- frozen specification and runtime-file hashes.

The release remains external and read-only. Weights, training code, calibration, and
cross-validation are not copied into this repository or into a study.

## Inference contract

An eligible subject has an active, validated native T2 NIfTI with spacing
0.07 × 0.07 × 0.5 mm. The adapter:

1. adds only the required singleton modality dimension;
2. performs no spatial resampling or reorientation;
3. applies the frozen RatLesNetV2 normalization;
4. loads all five checksummed models;
5. averages their lesion-probability maps;
6. applies threshold 0.40;
7. performs no connected-component or other postprocessing; and
8. validates output shape and affine against the native input.

Job outputs:

```text
outputs/t2_lesion/jobs/<job-id>/
├── cases/<subject-id>/
│   ├── ensemble_probability.nii.gz
│   ├── ensemble_mask.nii.gz
│   └── qc_preview.png
├── inference_manifest.csv
└── inference_summary.json
```

SQLite records release, job, source input, hashes, device, provisional voxel count and
volume, and artifact version. File presence alone never proves success.

The supplied unseen smoke case matched the previous MPS mask voxel-for-voxel: 7,339
voxels and identical affine. Maximum CPU/MPS probability difference was 1.73 × 10⁻⁶.

## Connected review-to-result workflow

```text
validated T2 → inference → immutable draft mask → review/correction
→ approved mask → official native-space volume → approved-only CSV
```

An automatic mask starts as `DRAFT_REVIEW_REQUIRED`; an imported correction starts as
`CORRECTED_REVIEW_REQUIRED`. Their displayed volumes remain provisional. Only approval
creates an active official result. Both states appear in the study-level Reviews queue;
the subject workspace exposes the same service actions for detailed context.

### Review actions

- `Approve`: accept this exact native-grid mask version.
- `Reject`: require issue code and notes; keep the draft.
- `Open for correction`: create an editable copy and open T2 plus copy in ITK-SNAP.
- `Import corrected mask`: validate shape, affine, binary labels, checksum, and source;
  store it as a new immutable version.

Every decision records reviewer, time, notes, issue code where required, and study
blinding state.

### Official volume

Only an approved mask may produce the official result:

```text
lesion_voxel_count = count(mask == 1)
lesion_volume_mm3  = lesion_voxel_count × voxel_volume_mm3
```

The result records approved mask ID/checksum, native T2 ID, spacing, model release,
method version, reviewer, approval time, and warnings. A new source T2, approved mask, or
release/method makes the old result `OUTDATED` without deleting it.

### First export

The first production export is a simple approved-results CSV. It includes no unapproved
value by default and requires audited unblinding before adding group columns.

## Deferred

- T2-to-T1 registration and lesion-associated enhancement.
- Atlas mapping and regional quantification.
- Embedded mask editing.
- Model release marketplaces or arbitrary parameter editing.

The implemented acceptance criteria are listed in `current_state.md` and exercised by
`tests/test_t2_review.py`.
