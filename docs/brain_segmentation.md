# Brain Segmentation Status

Brain segmentation is the critical blocker for final V1 interpretation. The
current cohort quantification code is an engineering/QC iteration and must not
be treated as biological results until the brain masks, registration QC,
side/ROI metadata, thresholds, and inclusion/exclusion decisions are locked.

## Dataset Constraint

The current inventory contains static pre/post gadolinium
`T1_FLASH_3D_Glymphatic_Sag` scans at D1 and D7. It does not contain RARE-VTR
multi-TR T1 mapping or DCE-MRI time-series data. The downstream analysis is
therefore semi-quantitative T1-weighted gadolinium enhancement, not absolute
T1, Ktrans, `ve`, `vp`, or physical permeability.

## Current Mask Decision

The active V1 mask route is:

1. Use native pre-contrast `pre_coronal.nii.gz` images as the mask-editing,
   model-training, and final mask space.
2. Use cloud MouseBrainExtractor outputs as editable pre-labels only.
3. Correct those pre-labels in ITK-SNAP and save binary masks on the exact
   pre-image grid.
4. Use corrected pre masks directly for quantification, or use them to
   fine-tune nnU-Net once enough corrected labels exist.
5. Train or predict brain masks from pre-contrast images first. Do not train
   the first brain-mask model on post-gadolinium images because post-Gd
   intensity changes are the biological leakage signal.
6. Rigidly register the post-Gd image to the pre-Gd image.
7. Apply the final pre-space mask to both the pre image and the registered post
   image only after post-to-pre registration QC passes.
8. If registration fails, fix/review registration or exclude the case. Do not
   silently draw an independent post mask, because that changes the tissue
   support used for the pre/post ratio.

The current default analysis/QC slice range remains:

```text
coronal slices 50-170
```

These slice limits are used for QC display and current V1 interpretation. The
mask file itself must still match the full pre-contrast image grid.

## SHERM Status

The SHERM-inspired implementation has been retired from the active pipeline and
moved to:

```text
deprecated/sherm/
```

It is kept only as historical reference or for a controlled one-off comparison.
It is not the active mask generator, not a fallback in quantification, and not a
source of final masks. Raw SHERM outputs must not be used as nnU-Net labels or
final quantification masks.

The retired SHERM code did not contain the active bias correction used by
quantification. Smooth bias correction, registration, normalization, enhancement
maps, QC outputs, and cohort metrics remain in:

```text
src/lys_bbb/flash_pair.py
src/lys_bbb/flash_cohort.py
```

## Manual Correction Workflow

Open MouseBrainExtractor pre-labels for correction in ITK-SNAP:

```bash
conda run -n lys-bbb python scripts/masks/open_manual_mask_editor.py \
  --input-root output/all_mice \
  --prelabel-dir derivatives/brain_seg/mousebrainextractor \
  --prelabel-glob "*_mousebrainextractor_mask.nii.gz" \
  --prelabel-suffix "_mousebrainextractor_mask.nii.gz" \
  --manual-dir derivatives/brain_seg/manual \
  --skip-existing
```

The launcher copies each selected pre-label into
`derivatives/brain_seg/manual/` and opens it with the matching
`pre_coronal.nii.gz`. The corrected mask is the candidate final mask or an
nnU-Net training label. The raw MouseBrainExtractor output is not final.

Use ITK-SNAP as the only manual editor for now. Other editor launchers were
removed to keep the workflow consistent.

Build the current manual-mask worklist and review dashboard:

```bash
conda run -n lys-bbb python scripts/qc/build_qc_manifest.py \
  --input-root output/all_mice \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv

conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --out-dir reports/qc \
  --manual-dir derivatives/brain_seg/manual
```

Outputs:

```text
reports/qc/manual_mask_worklist.csv
reports/qc/manual_mask_dashboard.html
derivatives/brain_seg/nnunet_manifest.csv
```

The HTML dashboard is a local review page linking each pre image, manual mask,
MouseBrainExtractor pre-label, brain-mask QC montage, and registration QC
montage. The CSV contains editable review columns, but the generated QC
manifest remains the source of truth for discovered files and computed metrics.

After finishing manual correction, rerun both commands above. Masks should be
considered ready only when the file is on the correct grid, visually reviewed,
not an unchanged pre-label, free of obvious disconnected non-brain components,
and saved or copied to the `_pre_manual_mask_done.nii.gz` naming pattern.

Build the quantification handoff manifest after refreshing QC:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  -o derivatives/manifests/analysis_manifest.csv \
  --summary reports/qc/analysis_manifest_summary.csv
```

This manifest is the bridge from mask QC to cohort quantification. It preserves
editable fields for `group`, `ipsilateral_side`, `lesion_mask_path`,
`review_status`, and `review_notes`, but it forces `include=no` whenever the
automated mask or registration gates are not ready. The cohort command can read
it through `--roi-manifest`.

## Mask Target

The mask target should be consistent across manual masks, corrected pre-labels,
nnU-Net labels, predictions, and final QC-approved masks.

Current target:

- brain/parenchyma on the native pre-contrast coronal T1 FLASH image
- no skull, skin, eyes, muscle, glands, bright surface rim, or background
- no obvious missing cortex, basal/inferior brain, anterior brain, or posterior
  brain within the selected V1 slice range
- binary label image on the same shape and affine as `pre_coronal.nii.gz`

Open target-definition points to keep explicit during correction:

- whether olfactory bulb is included
- whether cerebellum and lower brainstem are included in the selected slice
  range
- how edge partial-volume voxels are handled
- whether ventricles/CSF are included as part of the brain mask

These choices should be made consistently before training nnU-Net or freezing
the final cohort masks.

## Validation Plan

Start with representative D1/D7 cases and visible failure modes. A practical
first correction set is 8-12 pre-contrast masks; 10-15 corrected masks is a
stronger basis for nnU-Net testing; correcting all pre masks may be the most
defensible final route if feasible.

Before accepting masks for final quantification:

- visually inspect every mask in ITK-SNAP or QC PNGs
- confirm image/mask shape and affine match
- verify plausible brain volume and stable mask extent across comparable cases
- inspect post-to-pre registration overlays before reusing the pre mask for
  post-Gd quantification
- record failures, exclusions, and any manual corrections in a manifest

Useful sensitivity check:

```text
compare primary enhancement metrics with the final mask and a 1-voxel-eroded mask
```

If the results change materially after a small erosion, the quantification is
too boundary-sensitive and mask quality remains a major uncertainty.

## nnU-Net Path

The nnU-Net path is optional but likely useful once corrected pre masks exist.
Use it as a mask-production accelerator, not as unchecked truth:

1. Correct 8-12 representative MouseBrainExtractor pre-labels.
2. Train a first nnU-Net v2 brain/background model on pre-contrast T1 images
   only.
3. Split by animal, not by scan, so D1 and D7 from the same animal do not leak
   across train/validation.
4. Predict masks for remaining pre scans.
5. Correct failures in ITK-SNAP.
6. Retrain with the expanded corrected label set.
7. Visually QC every final prediction before quantification.

The operational plan is documented in:

```text
docs/nnunet_active_learning.md
```

The current implementation can already create the nnU-Net manifest and raw
dataset folder once enough corrected masks are marked done:

```bash
conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py

conda run -n lys-bbb python scripts/masks/prepare_nnunet_brain_extraction.py \
  --manifest derivatives/brain_seg/nnunet_manifest.csv \
  --nnunet-raw derivatives/brain_seg/nnUNet_raw \
  --dry-run
```

Remove `--dry-run` only when the manifest contains the intended training cases.
By default, only masks marked `_done` and passing basic grid/QC checks become
`split=train`; remaining converted pre images become unlabeled `split=test`
prediction images.

## Model-Mask Integration

Once a brain-mask model produces predictions, do not pass those masks directly
to quantification. First validate them as candidate brain masks:

```bash
conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/nnunet_preds \
  --mask-source nnunet \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv
```

The default prediction filename pattern is:

```text
derivatives/brain_seg/nnunet_preds/{case_id}.nii.gz
```

The candidate manifest checks that each predicted mask matches the native
pre-contrast image grid, reports brain volume, connected components, largest
component percentage, registration QC linkage, and writes mask QC montages.
Then use the generated manifest as the input to the analysis-manifest gate:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/brain_mask_manifest.csv \
  -o derivatives/manifests/analysis_manifest.csv
```

For development only, current non-final manual masks can exercise the same
downstream path with:

```bash
conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --mask-dir derivatives/brain_seg/manual \
  --mask-source manual_test \
  --mask-pattern "{case_id}_pre_manual_mask_done.nii.gz" \
  --mask-pattern "{case_id}_pre_manual_mask.nii.gz" \
  --manifest-name brain_mask_manifest_manual_test.csv \
  --summary-name brain_mask_manifest_manual_test_summary.json

conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/brain_mask_manifest_manual_test.csv \
  -o derivatives/manifests/analysis_manifest_manual_test.csv \
  --summary reports/qc/analysis_manifest_manual_test_summary.csv \
  --allow-review-masks-for-testing
```

Testing manifests use the `testing_review_mask` gate and
`testing_nonfinal_masks` analysis mode. They are useful for pipeline
development, but they are not final biological analysis inputs.

## Future Lesion ROI Integration

Brain masking, lesion segmentation, and BBB enhancement quantification should
remain separate but connected steps.

Current V1 handles brain masking and static pre/post T1w enhancement. A later
stage can add the available high-resolution T2w lesion-volume images, but T2w
should be used to define the stroke lesion independently of gadolinium
enhancement. This avoids circular analysis from defining the lesion by the same
post-Gd signal that is later quantified as BBB leakage.

The detailed implementation plan for linking a T2w lesion model to T1 FLASH
enhancement quantification is tracked in:

```text
docs/t2_lesion_t1_integration.md
```

A strong T2w lesion segmentation model does not remove the T1 brain-mask
requirement. The T1 brain mask remains necessary for pre/post normalization,
skull/background exclusion, clipping transferred lesion masks to valid brain
tissue, defining hemispheres and midline, computing whole-brain and
outside-lesion regions, and deciding whether a session passes QC.

Future staged workflow:

1. Produce reliable brain masks from corrected pre-Gd T1 FLASH masks and,
   optionally, nnU-Net active learning.
2. Register post-Gd T1 to pre-Gd T1 and quantify whole-brain plus
   ipsilateral/contralateral enhancement.
3. Convert high-resolution T2w scans.
4. Register each T2w image to the matching pre-Gd T1 space.
5. Segment the stroke lesion on T2w.
6. Transform the T2w lesion mask into pre-Gd T1 space.
7. Mirror the lesion ROI to the contralateral hemisphere.
8. Quantify T1 pre/post enhancement in lesion ROI, mirrored contralateral ROI,
   ipsilateral hemisphere, contralateral hemisphere, and whole brain.

Conceptual rule:

```text
T2w = lesion definition
T1 pre/post = BBB leakage measurement
mirrored contralateral ROI = internal control
```

Future lesion-specific metrics should include lesion mean CE %, lesion median
CE %, lesion 95th percentile CE %, enhancing volume inside lesion, percent
lesion enhancing, lesion integrated leakage burden, lesion/mirrored
contralateral enhancement ratio, z-leakage metrics, peri-lesional leakage,
outside-lesion leakage, and D7-D1 change for all lesion-based metrics.

The first lesion-integration implementation should add T2w conversion/pairing,
T2-to-T1 registration QC, nearest-neighbor lesion-mask transfer into T1 pre
space, edema-corrected D1 T2 lesion volume when hemisphere masks are reliable,
exclusion masks for normally enhancing or artifact-prone structures, D1-to-D7
persistent/resolved/new leakage compartments, and a long-format ROI metrics
table. The current cohort code already accepts a T1-space lesion mask and an
ipsilateral side, but it should be extended before final reporting so
inside-lesion, outside-lesion, peri-lesion, hemisphere, and mirrored-ROI metrics
are all represented explicitly.

## Quantification Dependency

Active quantification now requires a supplied pre-space brain mask:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
  --pre output/all_mice/C25S1_D1/pre_coronal.nii.gz \
  --post output/all_mice/C25S1_D1/post_coronal.nii.gz \
  --mask derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz \
  -o derivatives/flash_v1_minimal/C25S1/D1/C25S1_D1
```

For cohort runs, provide masks through `--brain-mask-dir`,
`--brain-mask-pattern`, or a manifest `brain_mask` column. Sessions without a
mask should fail clearly rather than falling back to deprecated automatic
segmentation.

## References

- MouseBrainExtractor: `https://github.com/MouseSuite/MouseBrainExtractor`
- nnU-Net: `https://github.com/MIC-DKFZ/nnUNet`
- ITK-SNAP: `http://www.itksnap.org/`
- Retired SHERM reference implementation:
  `https://github.com/liu-yikang/SHERM-rodentSkullStrip`
