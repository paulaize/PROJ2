# T2 lesion integration

## Ownership

Upstream training owns model development, calibration, and validation. `LYS_PROJ2`
owns the immutable inference resources, release validation, model selection, inference
execution, study artifacts, human review, approved native-space volume, and exports.

The application never trains, tunes, or silently updates a T2 model. Windows builds
copy only checksummed resources from `resources/models`; inference never depends on
Downloads, Kaggle, or a live training checkout.

The approved native lesion artifact can be consumed by atlas mapping, but it remains on
the original T2 grid and is never a whole-brain registration mask. Changing it always
invalidates regional overlap; it also invalidates pre-T1→T2 and the composite only when
that exact lesion checksum was explicitly used for cost-function exclusion.

## Packaged model choices

Settings expose three deliberate choices:

- **Standard model — LYS v3 nnU-Net fold 1**: visible and internal default;
- **Small model — legacy RatLesNetV2**: retained inference-only five-fold release;
- **Larger model — LYS v3 folds 0+1**: non-default standard nnU-Net
  mean-logit fold ensemble,
  available because both best checkpoints are deliberately packaged.

The nnU-Net resource family is self-contained:

```text
resources/models/lys_v3_standard3d_nnunet/
├── dataset.json
├── plans.json
├── fold_0/checkpoint_best.pth
├── fold_1/checkpoint_best.pth
├── model_metadata.json
├── variants/folds_0_1/model_metadata.json
├── NNUNET_LICENSE.txt
└── SHA256SUMS
```

Fold 0 exists only to support the explicit larger-model option. No latest/final
checkpoints, logs, plots, debug files, validation predictions, training data, or masks
are packaged. The legacy small model is likewise copied as a minimal inference-only
resource under `resources/models/lys_v1_small_ratlesnetv2`.

Before every run, the application validates all packaged SHA-256 entries and checks the
selected contract. For LYS v3 this includes:

- nnU-Net v2.8.1;
- `Dataset701_LYSDevelopmentV1`;
- `nnUNetTrainer_250epochs`, `nnUNetPlans`, and `3d_fullres`;
- standard `PlainConvUNet`;
- fold 1 alone for the default or folds 0+1 for the optional ensemble;
- `checkpoint_best.pth`;
- lesion probability threshold 0.20;
- `postprocessing=none`;
- draft-mask and human-review requirements.

Threshold 0.20 is preliminary. It was calibrated from pooled partial OOF probabilities
for 81 unique held-out MRIs (41 fold 0 and 40 fold 1), not from fold-1-only
predictions. The complete metrics and fold-1 interruption/checkpoint provenance are in
`model_metadata.json`.

## Inference contract

An eligible subject has an active, validated native T2 NIfTI with spacing
0.07 × 0.07 × 0.5 mm. The LYS v3 adapter uses nnU-Net v2.8.1's inspected
`nnUNetPredictor` API, exports native-shape class probabilities, saves lesion channel
1, applies threshold 0.20 directly, performs no connected-component or other
postprocessing, and validates output shape and affine against the native input.

Job outputs:

```text
outputs/t2_lesion/jobs/<job-id>/
├── cases/<subject-id>/
│   ├── lesion_probability.nii.gz
│   ├── draft_lesion_mask.nii.gz
│   └── qc_preview.png
├── inference_manifest.csv
└── inference_summary.json
```

SQLite records release, job, source input, hashes, device, provisional voxel count and
volume, and artifact version. File presence alone never proves success.

The legacy small-model adapter retains its frozen normalization, probability
ensembling, threshold 0.40, and native-grid output contract.

## Connected review-to-result workflow

```text
validated T2 → inference → immutable draft mask → review/correction
→ approved mask → official native-space volume → approved-only CSV
```

An automatic mask starts as `DRAFT_REVIEW_REQUIRED`; a saved manual edit starts as
`CORRECTED_REVIEW_REQUIRED`. Their displayed volumes remain provisional. Only approval
creates an active official result. Both states appear in the study-level Reviews queue;
the subject workspace exposes the same service actions for detailed context.

The T2 QC renderer writes a montage plus one PNG for every native slice. The Reviews
viewer navigates those individual slices. Its coronal presentation is reflected
vertically (about the display x-axis); no voxel data, affine, or stored mask is changed.

### Review actions

- `Approve current mask`: accept this exact native-grid mask version.
- `Manually edit in ITK-SNAP`: create a managed editable copy and open the native T2
  plus that copy in ITK-SNAP.
- `Use saved mask`: validate shape, affine, binary labels, checksum, and source, then
  store the edit as the subject's new active immutable mask version.

Approval records reviewer identity, time, exact artifact, and study blinding state. The
application stores no reviewer note, issue type, or rejection decision. A manual edit is
the current human-corrected mask, but it still requires explicit approval before its
volume becomes official.

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

- Lesion-associated T1 enhancement is deferred implementation work but remains a final
  cross-workflow objective: calculate enhancement in native pre-T1 space, connect it
  through an independently approved pre-T1→T2 transform, and compare signal-intensity
  change inside the untouched native T2 lesion with a predeclared outside-lesion brain
  reference.
- Broad atlas-specific lesion and enhancement summaries remain planned additions.
  Detailed Allen labels, Waxholm comparison, and cohort atlas exports remain deferred.
- Embedded mask editing.
- Model release marketplaces or arbitrary parameter editing.

These additions do not supersede the independent endpoints. Native T2 lesion
segmentation/volume and general pre/post-T1 enhancement remain useful required results
even when atlas mapping, cross-modal registration, or combined analysis is unavailable
or fails review.

The implemented acceptance criteria are listed in `current_state.md` and exercised by
`tests/test_t2_review.py`.
