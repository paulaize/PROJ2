# LYS BBB MRI Pipeline

This repo is being organized into a staged V1 pipeline for mouse BBB leakage MRI analysis.

Current V1 is for the data actually available in this cohort: static pre/post `T1_FLASH_3D_Glymphatic_Sag` scans at D1 and D7 after thrombin/MAC stroke induction. The goal is a trustworthy semi-quantitative whole-brain gadolinium enhancement score per mouse/session, then simple ipsilateral/contralateral comparison once masking and side handling are reliable.

The final project objective is a reproducible pipeline that can take a folder
containing T1 gadolinium-leakage MRI data, plus an optional CSV/manifest that
identifies animals, time points, and pre/post scans, then produce a full
experiment-level BBB leakage report across all mice. The report should compare
D1 versus D7 for each animal where available, include whole-brain and later
side-aware leakage metrics, preserve QC outputs, and make the processing
parameters auditable.

These outputs are not absolute T1, Ktrans, absolute permeability, DCE-MRI modeling, or strict RARE-VTR protocol quantification.

## Environment

Use the conda environment `lys-bbb` for all project commands:

```bash
conda activate lys-bbb
```

Or run commands without activating:

```bash
conda run -n lys-bbb python ...
```

Raw dataset root:

```bash
/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P
```

Do not modify raw Bruker folders.

## Current Implementation State

The current implementation can process one converted pre/post T1 FLASH pair and
can run an initial D1/D7 cohort quantification table from converted case
folders. These outputs are still provisional because final corrected brain
masks, lesion/ROI masks, side assignments, and QC inclusion decisions are not
locked. Quantification should use only brain tissue on the reliable coronal
slice range:

```text
slices 50-170
```

Brain masks in this project are not final analysis masks yet. Cloud
MouseBrainExtractor masks should be treated as editable pre-labels until they
are visually QC'd and manually corrected. A bad mask is the first reason to
reject or distrust a session summary.

The detailed brain-segmentation status, tuning plan, lesion-linkage plan, and
comparison with other possible routes are documented in:

```text
docs/brain_segmentation.md
docs/nnunet_active_learning.md
docs/t2_lesion_t1_integration.md
```

Those documents are the current method decision records for V1 masking and
lesion-to-enhancement linkage. Their main conclusion is that reliable brain
segmentation is still the next blocker before final cohort interpretation,
atlas mapping, leakage-volume thresholds, ipsilateral/contralateral primary
endpoints, or polished plots.

Current decision: cloud MouseBrainExtractor outputs are rough pre-labels, not
final V1 segmentation. The preferred next path is to manually correct those
pre-labels in native pre-contrast T1 FLASH space, then use the corrected masks
directly for quantification or to fine-tune an nnU-Net brain-mask model if
enough corrected labels exist. The older SHERM-inspired mask code is deprecated
under `deprecated/sherm/` and is not an active fallback.

Post-gadolinium images should not be segmented independently by default. The
current plan is to create or predict a final mask on the pre-contrast image,
rigidly register the post-Gd image to the pre-Gd image, and then use the same
pre-space mask for both pre and registered-post quantification after
registration QC passes.

V1 should stay lightweight by default. Heavy NIfTI intermediates and Fiji display files should be generated only when explicitly requested.

## 1. Inventory Raw Bruker Sessions

Build a machine-readable inventory:

```bash
conda run -n lys-bbb python scripts/inventory/inventory_sessions.py \
  /Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P \
  -o reports/inventory
```

Outputs:

```text
reports/inventory/scan_inventory.csv
reports/inventory/scan_inventory_summary.json
```

The inventory detects pre/post T1 FLASH scans by metadata. A future full
pipeline should also accept an optional CSV/manifest when folder names or scan
metadata are not enough to identify animal ID, time point, and pre/post role
unambiguously.

## 2. Convert Bruker Sagittal T1 FLASH To Coronal NIfTI

Run one session:

```bash
conda run -n lys-bbb python scripts/conversion/convert_bruker_t1_flash.py \
  "/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P/20241003_094309_FP_THR_03_D1_C25S1_1_1" \
  -o output \
  --qc-slab-mm 0.4 \
  --no-fiji-display
```

Run several sessions by listing folders:

```bash
conda run -n lys-bbb python scripts/conversion/convert_bruker_t1_flash.py \
  "/path/to/session_1" \
  "/path/to/session_2" \
  -o output \
  --qc-slab-mm 0.4 \
  --no-fiji-display
```

Important outputs for normal quantitative conversion:

```text
*_sag.nii.gz                         original sagittal converted NIfTI
*_coronal.nii.gz                     native coronal quantitative NIfTI
*_coronalQC.png                      coronal QC montage
*_pre_post_diffQC.png                pre/post/difference QC montage
```

Use `_coronal.nii.gz` for quantification. Use PNGs for visual QC.

The current conversion script can also write `_coronal_fijiDisplay.nii.gz` files. These are Fiji viewing copies only. The desired V1 workflow is to avoid them during normal quantitative runs by using `--no-fiji-display`, and to omit that flag only when you explicitly want Fiji-viewable files.

Optional slab NIfTI outputs are supported with `--write-slab-mm`, but they are visualization-only and can be large. Do not write them unless you need them for a specific Fiji review.

## 3. Example Fiji Views For Two Animals At D1 And D7

This command intentionally writes a Fiji display set for `C25S1` and `C25S2` at D1 and D7. Do not add `--no-fiji-display` for this viewing-specific run:

```bash
conda run -n lys-bbb python scripts/conversion/convert_bruker_t1_flash.py \
  "/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P/20241003_094309_FP_THR_03_D1_C25S1_1_1" \
  "/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P/20241009_075901_FP_THR_03_D7_C25S1_1_1" \
  "/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P/20241003_104111_FP_THR_03_D1_C25S2_1_1" \
  "/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P/20241009_085531_FP_THR_03_D7_C25S2_1_1" \
  -o output/fiji_d1_d7_two_animals \
  --qc-slab-mm 0.4
```

For Fiji viewing, open:

```text
*_sag.nii.gz                         sagittal view
*_coronal_fijiDisplay.nii.gz         coronal view with vertical flip and square XY pixels
```

For quantification, keep using:

```text
*_coronal.nii.gz
```

## 4. Quantify One Pre/Post FLASH Pair

After conversion, run quantification on native coronal files:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
  --pre output/fiji_d1_d7_two_animals/20241003_094309_FP_THR_03_D1_C25S1_1_1/20241003_094309_FP_THR_03_D1_C25S1_1_1_scan-3_T1FLASH3D_coronal.nii.gz \
  --post output/fiji_d1_d7_two_animals/20241003_094309_FP_THR_03_D1_C25S1_1_1/20241003_094309_FP_THR_03_D1_C25S1_1_1_scan-6_T1FLASH3D_coronal.nii.gz \
  --mask derivatives/brain_seg/manual/20241003_094309_FP_THR_03_D1_C25S1_1_1_pre_manual_mask.nii.gz \
  --session-id 20241003_094309_FP_THR_03_D1_C25S1_1_1 \
  -o derivatives/flash_v1_minimal/20241003_094309_FP_THR_03_D1_C25S1_1_1
```

Default lightweight outputs:

```text
*_mask.nii.gz
*_percent_enhancement.nii.gz
*_post_to_pre.tfm
*_mask_qc.png
*_enhancement_qc.png
*_summary.csv
*_metadata.json
```

Current defaults:

```text
brain mask: required corrected or predicted pre-space binary mask
--mask-slice-start 50
--mask-slice-stop 170
```

The mask slice options control QC display range. They do not generate an
automatic mask.

The main quantitative map currently written by default is:

```text
*_percent_enhancement.nii.gz
```

The current per-session summary table is:

```text
*_summary.csv
```

Final V1 should use the cohort-level CSV/report as the primary table once masks
and QC decisions are finalized, rather than relying on disconnected per-session
tables.

## 5. Quantify Converted D1/D7 Cohort

This is an initial batch-analysis iteration for engineering, QC, and method
development. It is not the locked final quantification workflow. The script is
intended to be re-run and possibly refactored once the final converted image set,
corrected brain masks, lesion/ROI masks, and ipsilateral side assignments are
available. Until those inputs are final and QC-approved, treat `cohort_quantification.csv`
as a provisional technical output, not a final biological results table.

The first batch quantification script expects converted folders like:

```text
output/all_mice/C25S1_D1/pre_coronal.nii.gz
output/all_mice/C25S1_D1/post_coronal.nii.gz
output/all_mice/C25S1_D7/pre_coronal.nii.gz
output/all_mice/C25S1_D7/post_coronal.nii.gz
```

Run a discovery-only check before processing:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  -o derivatives/flash_v1_cohort \
  --dry-run
```

Build the gated analysis manifest from the QC manifest:

```bash
conda run -n lys-bbb python scripts/qc/build_qc_manifest.py \
  --input-root output/all_mice \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv

conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  -o derivatives/manifests/analysis_manifest.csv \
  --summary reports/qc/analysis_manifest_summary.csv
```

The analysis manifest is the intended handoff from QC to quantification. It
contains one row per case, the selected brain-mask path, optional lesion/side
fields, `include`, and a `qc_gate`. Cases with missing or unreviewed masks are
written with `include=no`, so the cohort run cannot silently process bad masks.

Build or refresh the editable study metadata table when group labels,
ipsilateral side, lesion masks, or manual inclusion/review decisions need to be
tracked outside the generated QC manifest:

```bash
conda run -n lys-bbb python scripts/qc/build_study_metadata.py \
  --analysis-manifest derivatives/manifests/analysis_manifest.csv
```

This writes `derivatives/manifests/study_metadata.csv` plus validation reports
under `reports/qc/`. Fill `group`, `ipsilateral_side`, `lesion_mask_path`,
`review_status`, and `review_notes` there as those decisions become available.
Accepted side values are `left`, `right`, `low-x`, and `high-x`. Then rebuild
the analysis manifest with those editable values merged back in:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --metadata-manifest derivatives/manifests/study_metadata.csv \
  -o derivatives/manifests/analysis_manifest.csv \
  --summary reports/qc/analysis_manifest_summary.csv
```

The metadata table can request inclusion or exclusion, but it cannot override a
failed automated QC gate. A case with a missing/invalid mask or failed
registration still stays `include=no`.

Build the current V1 readiness report:

```bash
conda run -n lys-bbb python scripts/qc/build_project_status.py
```

This writes `reports/qc/project_status.md` and
`reports/qc/project_status.json`. The report summarizes analysis-manifest
gates, manual-mask status, nnU-Net readiness, registration QC, current blockers,
and the next commands to run. It is a technical status artifact, not a
biological result.

Run a manifest-gated cohort dry run:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  -o derivatives/flash_v1_cohort \
  --roi-manifest derivatives/manifests/analysis_manifest.csv \
  --dry-run
```

Run the cohort with corrected brain masks when available:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  -o derivatives/flash_v1_cohort \
  --brain-mask-dir derivatives/brain_seg/manual \
  --brain-mask-pattern "{case_id}_pre_manual_mask_done.nii.gz" \
  --brain-mask-pattern "{case_id}_pre_manual_mask.nii.gz"
```

Preferred final-style run after masks and QC decisions are locked:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  -o derivatives/flash_v1_cohort \
  --roi-manifest derivatives/manifests/analysis_manifest.csv
```

The preferred way to run ipsilateral/contralateral correction is to fill
`ipsilateral_side` in `derivatives/manifests/study_metadata.csv`, rebuild
`analysis_manifest.csv`, and run the manifest-gated cohort command above. For
single-side debugging across all included sessions, the cohort command also
accepts:

```bash
--ipsilateral-side left
```

or:

```bash
--ipsilateral-side right
```

For orientation debugging, `low-x` and `high-x` are also accepted instead of
anatomical left/right.

Main outputs:

```text
cohort_sessions.csv          discovered case manifest
cohort_quantification.csv    one row per session plus D7-D1 rows when unique pairs exist
cohort_metadata.json         processing settings and failure/delta warnings
```

Per-session outputs are written under:

```text
derivatives/flash_v1_cohort/<animal>/<timepoint>/<case_id>/
```

The combined CSV reports semi-quantitative pre/post T1w gadolinium enhancement
metrics only. It includes raw CE statistics, contralateral-corrected CE
statistics when a side/reference is available, enhancing volume, percent ROI or
lesion enhancing, integrated leakage burden, ipsi/contra post-pre ratio, and
D7-D1 changes. It does not report `Ktrans`, `ve`, `vp`, absolute permeability,
or physical permeability units.

Relevant future objectives for this batch workflow:

1. Replace raw MouseBrainExtractor pre-labels with final corrected brain masks or validated nnU-Net predictions.
2. Add final lesion/ROI masks from high-resolution T2w lesion images registered to the T1 FLASH pre-space.
3. Confirm stroke side per animal/session through a manifest before using ipsilateral/contralateral endpoints as primary metrics.
4. Validate leakage-volume thresholding against contralateral or sham distributions before treating enhancing volume as a final endpoint.
5. Freeze the primary endpoint set after mask and ROI QC, likely mean/median corrected CE, 95th percentile CE, enhancing volume, percent lesion enhancing, integrated leakage burden, and D7-D1 changes.
6. Add final statistics tables for D1 vs D7 within mouse, group comparisons at each time point, and group comparison of D7-D1 change once unblinding/group labels are available.

## 6. Inspect QC Before Trusting Numbers

Always inspect:

```text
*_mask_qc.png
*_enhancement_qc.png
```

The mask should tightly follow the murine brain on slices 50-170. It should not include skull, skin, glands, bright rim, or background noise, and it should not miss major brain tissue. If the mask is bad, do not trust the summary.

For the current dataset, mask QC is not a cosmetic review step. It decides
whether any downstream number is usable. Do not use summaries from failed masks
for biological interpretation, threshold selection, atlas work, group plots, or
V1 reporting.

Before reusing one pre-contrast mask for the registered post image, inspect
post-to-pre registration QC:

```bash
conda run -n lys-bbb python scripts/qc/qc_pre_post_registration.py \
  --input-root output/test_mice \
  -o derivatives/registration_qc/test_mice \
  --mask-slice-start 50 \
  --mask-slice-stop 170 \
  --n-slices 7
```

This writes one before/after registration montage per case plus
`registration_qc_summary.csv`. The conversion script only reorients images to
coronal NIfTI; rigid post-to-pre registration happens later in the
quantification/registration QC code.

Current brain-mask plan:

1. Use pre-contrast `pre_coronal.nii.gz` images as the mask-editing and model-training space.
2. Treat cloud MouseBrainExtractor outputs under `derivatives/brain_seg/mousebrainextractor/` as editable pre-labels, not as final masks.
3. Manually correct those pre-labels and save corrected masks under `derivatives/brain_seg/manual/`.
4. Use corrected pre masks as the labels for nnU-Net fine-tuning if enough corrected cases are available.
5. For quantification, apply the final pre-space mask to the pre image and to the post image only after the post image has been registered into pre space.
6. If post-to-pre registration fails, fix registration or exclude/review the case; do not silently create an independent post mask because that would change the pre/post denominator and can bias enhancement.

To open cloud MouseBrainExtractor pre-labels as editable manual masks:

```bash
conda run -n lys-bbb python scripts/masks/open_manual_mask_editor.py \
  --input-root output/all_mice \
  --prelabel-dir derivatives/brain_seg/mousebrainextractor \
  --prelabel-glob "*_mousebrainextractor_mask.nii.gz" \
  --prelabel-suffix "_mousebrainextractor_mask.nii.gz" \
  --manual-dir derivatives/brain_seg/manual \
  --skip-existing
```

This copies each selected pre-label to `derivatives/brain_seg/manual/` and opens
it with the matching pre-contrast image for correction. The saved manual mask is
the candidate final mask or nnU-Net label; the raw MouseBrainExtractor output is
not.

Build or refresh the manual-mask dashboard and nnU-Net manifest:

```bash
conda run -n lys-bbb python scripts/qc/build_qc_manifest.py \
  --input-root output/all_mice \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv

conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --out-dir reports/qc \
  --manual-dir derivatives/brain_seg/manual
```

This writes:

```text
reports/qc/manual_mask_worklist.csv
reports/qc/manual_mask_dashboard.html
reports/qc/brain_masks/comparison/*_manual_vs_mbe_qc.png
derivatives/brain_seg/nnunet_manifest.csv
```

The dashboard prioritizes manual edits rather than only showing independent
mask thumbnails. Its comparison montages show the manual contour in lime, the
MouseBrainExtractor contour in magenta, voxels added during correction in cyan,
and voxels removed during correction in orange. It also shows connected-component
metrics, case/status filters, and a copyable one-case ITK-SNAP launcher command.

Human review decisions are entered in `manual_mask_worklist.csv` using
`mask_review`, `registration_review`, and `review_notes`. Accepted review values
are `pass`, `review`, and `fail`; common variants such as `approved` and `passed`
are normalized. These fields survive subsequent workflow rebuilds. The worklist
quantification flag requires both reviews to pass, while the generated nnU-Net
manifest requires `mask_review=pass` in addition to the existing filename, grid,
changed-prelabel, and connected-component checks.

After manual correction, rerun those commands. Masks that are not explicitly
approved remain unlabeled prediction/test rows in the nnU-Net manifest.

Dry-run the T1 brain-mask nnU-Net raw dataset preparation:

```bash
conda run -n lys-bbb python scripts/masks/prepare_nnunet_brain_extraction.py \
  --manifest derivatives/brain_seg/nnunet_manifest.csv \
  --nnunet-raw derivatives/brain_seg/nnUNet_raw \
  --dry-run
```

After a brain-mask model produces predictions, validate them before
quantification. The expected default prediction layout is:

```text
derivatives/brain_seg/nnunet_preds/{case_id}.nii.gz
```

First post-process predictions into a clean candidate folder. This binarizes
the masks and keeps the largest connected component by default. Missing masks
are reported but are not treated as command failures, which allows partial
prediction batches during development:

```bash
conda run -n lys-bbb python scripts/masks/postprocess_brain_masks.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/nnunet_preds \
  -o derivatives/brain_seg/nnunet_preds_cleaned \
  --summary-csv reports/qc/brain_mask_postprocess_nnunet.csv \
  --summary-json reports/qc/brain_mask_postprocess_nnunet_summary.json
```

Build a model-mask candidate manifest from the cleaned predictions:

```bash
conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/nnunet_preds_cleaned \
  --mask-source nnunet_cleaned \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv
```

Then build the final-style analysis manifest from validated model masks:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/brain_mask_manifest.csv \
  -o derivatives/manifests/analysis_manifest.csv \
  --summary reports/qc/analysis_manifest_summary.csv
```

For development only, the same path can be exercised with current non-final
manual masks:

```bash
conda run -n lys-bbb python scripts/masks/postprocess_brain_masks.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/manual \
  --mask-pattern "{case_id}_pre_manual_mask_done.nii.gz" \
  --mask-pattern "{case_id}_pre_manual_mask.nii.gz" \
  -o derivatives/brain_seg/manual_test_cleaned \
  --summary-csv reports/qc/brain_mask_postprocess_manual_test.csv \
  --summary-json reports/qc/brain_mask_postprocess_manual_test_summary.json

conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/manual_test_cleaned \
  --mask-source manual_test_cleaned \
  --manifest-name brain_mask_manifest_manual_test_cleaned.csv \
  --summary-name brain_mask_manifest_manual_test_cleaned_summary.json

conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/brain_mask_manifest_manual_test_cleaned.csv \
  -o derivatives/manifests/analysis_manifest_manual_test_cleaned.csv \
  --summary reports/qc/analysis_manifest_manual_test_cleaned_summary.csv \
  --allow-review-masks-for-testing

conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  --roi-manifest derivatives/manifests/analysis_manifest_manual_test_cleaned.csv \
  -o derivatives/flash_v1_manual_mask_cleaned_test
```

`--allow-review-masks-for-testing` is intentionally non-final. It exists to
exercise the downstream code path before masks are approved.

Run quantification with a corrected or QC-approved predicted mask:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
  --pre path/to/pre_coronal.nii.gz \
  --post path/to/post_coronal.nii.gz \
  --mask path/to/corrected_or_predicted_pre_mask.nii.gz \
  --session-id SESSION \
  -o derivatives/flash_v1_minimal/SESSION
```

The mask must be on the same grid as the pre-contrast `_coronal.nii.gz`. The
active quantification path no longer generates a SHERM fallback mask. If no
corrected or predicted mask is available for a session, that session should be
held out from final quantification until the mask is corrected.

The retired SHERM-inspired preview code is kept under `deprecated/sherm/` only
for historical reference or controlled comparison. It should not be used as a
normal pre-label source or final mask source.

## 7. Optional Debug Outputs

Heavy intermediate NIfTIs are not written by default.

Save registered post, bias fields, bias-corrected images, and normalized images:

```bash
--save-intermediates
```

Also save extra enhancement maps:

```bash
--save-all-maps
```

Full debug example:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
  --pre path/to/pre_coronal.nii.gz \
  --post path/to/post_coronal.nii.gz \
  --mask path/to/corrected_or_predicted_pre_mask.nii.gz \
  --session-id SESSION \
  -o derivatives/flash_v1_debug/SESSION \
  --save-intermediates \
  --save-all-maps
```

Extra debug outputs may include:

```text
*_post_registered.nii.gz
*_pre_biascorr.nii.gz
*_post_registered_biascorr.nii.gz
*_pre_biasfield.nii.gz
*_post_registered_biasfield.nii.gz
*_pre_norm.nii.gz
*_post_registered_norm.nii.gz
*_post_minus_pre.nii.gz
*_post_over_pre.nii.gz
```

## 8. Intended Next Implementation Steps

1. Finish correction/QC of the cloud MouseBrainExtractor pre-labels, then define which corrected pre-contrast masks are approved for quantification.
2. Use corrected masks to decide whether the final route is manually corrected masks, template/registration propagation, or validated nnU-Net prediction.
3. Re-run cohort quantification only after the final converted image set and mask set are fixed.
4. Add a final manifest for animal ID, time point, inclusion/exclusion, brain mask path, lesion/ROI mask path, stroke side, and later treatment group.
5. Validate post-to-pre registration for every included session before accepting shared pre-mask quantification.
6. Validate leakage threshold choices, including contralateral 95th percentile, contralateral mean plus 2 SD, `z_leakage > 3`, minimum connected-component size, and sham-derived thresholds if sham data become available.
7. Add T2w high-resolution lesion images as an independent lesion-definition stream: convert T2w scans, run or import the T2w lesion model in T2 space, register T2w to pre-Gd T1 space, and transform lesion masks into the T1 pre-space with nearest-neighbor interpolation.
8. Add explicit long-format ROI outputs for whole brain, ipsilateral hemisphere, contralateral hemisphere, lesion, mirrored contralateral lesion, peri-lesional rim, outside-lesion brain, ipsilateral outside-lesion brain, and contralateral outside-lesion brain.
9. Add longitudinal D1-to-D7 outputs for raw and edema-corrected T2 lesion volume, persistent/resolved/new leakage, and T2-lesion/gad-enhancement overlap compartments.
10. Add final D1-D7 and group-statistics reporting after group labels are available and QC exclusions are locked.
11. Keep all final reporting language as semi-quantitative T1-weighted gadolinium enhancement, not Ktrans, `Ki`, `ve`, `vp`, absolute permeability, or DCE-MRI modeling.

Future lesion-centered analysis should keep brain masking, lesion
segmentation, and BBB enhancement quantification separate but connected:

```text
T2w = lesion definition
T1 pre/post = BBB leakage measurement
mirrored contralateral ROI = internal control
```

The T1w FLASH images remain the basis for semi-quantitative BBB leakage
measurement. T2w images should define the stroke lesion independently of
gadolinium enhancement, avoiding circular quantification from post-Gd
hyperintensity. After lesion masks are registered into pre-Gd T1 space, create
both lesion ROIs and mirrored contralateral lesion ROIs, then quantify
enhancement in whole brain, ipsilateral hemisphere, contralateral hemisphere,
lesion ROI, and mirrored contralateral ROI.

Future lesion-specific outputs should include lesion mean CE %, lesion median
CE %, lesion 95th percentile CE %, enhancing volume inside lesion, percent
lesion enhancing, lesion integrated leakage burden, lesion/mirrored
contralateral enhancement ratio, z-leakage metrics, peri-lesional leakage,
outside-lesion leakage, and D7-D1 change for those metrics. D1 and D7 T2w
lesion volumes should be interpreted separately because D1 is edema-sensitive
while D7 reflects later lesion evolution.

The detailed T2w-to-T1 implementation plan is tracked in:

```text
docs/t2_lesion_t1_integration.md
```

A good T2w lesion model does not replace the T1 brain-mask requirement. The T1
brain mask is still needed for tissue-only normalization, skull/background
exclusion, lesion-mask clipping, hemisphere/midline handling, whole-brain and
outside-lesion regions, and final QC.

Model development should stay staged:

```text
Dataset501_MouseBrainMask: pre-Gd T1 input, brain-mask label
Dataset502_MouseLesionT2: T2w input, lesion-mask label
Dataset503_MouseBrainLesionMultichannel: optional later combined model
```

The combined/multichannel model should be considered only after the brain-mask
and T2w lesion-segmentation tasks work independently.

## 9. Tests

Run focused tests:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n lys-bbb python -m pytest tests
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids unrelated third-party pytest plugins from the conda environment interfering with these tests.

## 10. Current Interpretation Limits

For this dataset, report outputs as:

```text
semi-quantitative T1-weighted gadolinium enhancement
```

Do not report current outputs as:

```text
absolute T1
Ktrans
absolute permeability
protocol-compliant RARE-VTR T1 mapping
DCE-MRI modeling
```
