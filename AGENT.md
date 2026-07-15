# AGENT.md - LYS BBB MRI Project Context

## Global Project Goal

The goal of this project is to build a reproducible MRI pipeline that quantifies gadolinium leakage through the blood-brain barrier (BBB) after thrombin/MAC stroke induction in mice. The final intended workflow should take a folder containing T1 gadolinium-leakage MRI data, plus an optional CSV/manifest describing animal IDs, time points, and pre/post scan roles, and produce a full experiment-level BBB leakage report across all mice.

For the current dataset, the practical V1 goal is a trustworthy whole-brain gadolinium enhancement score for each mouse at D1 and D7, plus simple ipsilateral/contralateral comparison metrics once the brain mask and midline handling are reliable. The final report should compare D1 versus D7 for each animal where available, include QC paths and processing metadata, and provide auditable quantification of BBB leakage across the experiment.

The current data are static pre/post gadolinium `T1_FLASH_3D_Glymphatic_Sag` scans. They are not RARE-VTR T1-mapping scans and not DCE-MRI time-series scans. Therefore V1 must be described as semi-quantitative T1-weighted enhancement analysis, not absolute T1, contrast concentration, Ktrans, or absolute permeability.

There is no active automatic brain-mask fallback in quantification. The current mask route is cloud MouseBrainExtractor pre-labels corrected in ITK-SNAP, with optional nnU-Net active learning once enough corrected labels exist. The older SHERM-inspired code is deprecated under `deprecated/sherm/` and must not be treated as an active default or final mask source.

The current segmentation and ROI-linkage method decision records are [docs/brain_segmentation.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/brain_segmentation.md), [docs/nnunet_active_learning.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/nnunet_active_learning.md), and [docs/t2_lesion_t1_integration.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/t2_lesion_t1_integration.md). Treat those files as the source of truth for mask status, manual-mask requirements, post-mask logic, the optional nnU-Net active-learning path, and planned T2w lesion-to-T1 FLASH ROI linkage.

## Required Environment

- Always use the conda environment `lys-bbb` for project commands, scripts, tests, and dependency checks unless the user explicitly says otherwise.
- Preferred command style: `conda run -n lys-bbb python ...`
- Raw Bruker data must remain unmodified.

## Current Dataset

Primary raw Bruker root:

```text
/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P
```

The project contains blinded treatment groups. Current output tables should include animal ID and time point, but not treatment labels unless the user later provides an unblinding table.

The main time points are:

- `D1`: day 1 after thrombin/MAC stroke induction.
- `D7`: day 7 after thrombin/MAC stroke induction.

Known scan pattern from the provided `brkraw info` example:

- Scan 1: `1_Localizer`
- Scan 2: `T2s_rapide`
- Scan 3: `T1_FLASH_3D_Glymphatic_Sag`, likely pre-contrast
- Scan 4: `FLASH_TOF_2D_flow_comp_surface_coil`
- Scan 5: `T2_haute_resolution_Turbo`
- Scan 6: `T1_FLASH_3D_Glymphatic_Sag`, likely post-contrast
- Scan 7: `T2_haute_resolution_Turbo`
- Scan 8: `1_Localizer`

The current cohort appears to have a consistent scan order, but scripts should continue using metadata, protocol names, and scan IDs rather than hard-coding only scan order. Future datasets may not follow the same order.

## Method References And Protocol Alignment

Use the following sources as method references and inspiration, not as procedures that the current dataset can fully reproduce or future acquisitions are expected to provide.

Primary protocol reference:

- Title: `In Vivo T1 Mapping of Blood-Brain Barrier Leakage in Mouse Brain Using Gadolinium Enhanced RARE-VTR MRI`
- Platform: protocols.io
- Version: v2
- DOI: `10.17504/protocols.io.bp2l6j5nkvqe/v2`
- Publication date: May 14, 2026

The protocols.io workflow is built around RARE-VTR T1 mapping with TR values `8000, 3600, 2400, 1480, 940, 650, 501.1 ms`, motion correction to the `TR=8000 ms` image, denoising, Gibbs correction, brain extraction, bias correction, voxelwise T1 fitting, atlas or ROI projection, and regional pre/post T1-shift analysis.

The current dataset does not contain detected RARE-VTR multi-TR data, and the user does not control future acquisition protocol changes. Future agents must not plan a RARE-VTR branch as an expected project outcome. The protocol is useful only for good-practice ideas such as Bruker-to-NIfTI conversion, MP-PCA denoising, Gibbs ringing correction, bias correction, registration, and careful QC.

Additional DCE-MRI reference:

- Lee et al. 2023, `Deep Learning Enables Reduced Gadolinium Dose for Contrast-Enhanced Blood-Brain Barrier Opening`, `arXiv:2301.07248`

DCE/Ktrans methods require dynamic T1-weighted time-series data during contrast uptake. Those data are not present here, and the user does not expect to obtain them. Do not plan a DCE/Ktrans branch as an expected project outcome. Use the DCE paper only as background inspiration for preprocessing, masking, registration, normalization, and analysis design, not as a directly runnable method for this dataset.

Do not recommend changing future acquisition protocols unless the user asks. The user does not control future protocol design.

## Current Repo State

Main active files:

- [scripts/conversion/convert_bruker_t1_flash.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/conversion/convert_bruker_t1_flash.py): Bruker T1 FLASH conversion, sagittal-to-coronal reorientation, Fiji display copies, and conversion QC.
- [scripts/conversion/convert_inventory_t1_flash.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/conversion/convert_inventory_t1_flash.py): manifest/inventory-driven conversion into clean `output/all_mice/<case>/pre_coronal.nii.gz` and `post_coronal.nii.gz` folders.
- [scripts/quantification/quantify_flash_pair.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/quantification/quantify_flash_pair.py): one-session pre/post FLASH registration, supplied pre-space brain-mask handling, normalization, enhancement map generation, summary CSV, metadata, and QC.
- [scripts/quantification/quantify_flash_cohort.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/quantification/quantify_flash_cohort.py): initial cohort-level D1/D7 quantification table, including provisional D7-D1 rows and optional side-aware metrics when side metadata is supplied.
- [scripts/masks/open_manual_mask_editor.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/masks/open_manual_mask_editor.py): ITK-SNAP-only launcher for correcting MouseBrainExtractor pre-label masks on the matching pre-contrast image.
- [scripts/masks/build_manual_mask_workflow.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/masks/build_manual_mask_workflow.py): builds the manual T1 brain-mask worklist, local HTML review dashboard, and nnU-Net manifest from the QC manifest.
- [scripts/masks/build_brain_mask_manifest.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/masks/build_brain_mask_manifest.py): validates candidate brain masks from manual labels or model predictions before analysis-manifest gating.
- [scripts/masks/postprocess_brain_masks.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/masks/postprocess_brain_masks.py): binarizes candidate masks and keeps the largest connected component before candidate-mask QC.
- [scripts/masks/prepare_nnunet_brain_extraction.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/masks/prepare_nnunet_brain_extraction.py): validates the nnU-Net mask manifest and creates `Dataset501_MouseBrainMask` raw data when enough corrected labels are marked done.
- [scripts/qc/qc_pre_post_registration.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/qc/qc_pre_post_registration.py): registration QC for converted pre/post coronal pairs; writes raw-versus-registered montages, transforms, and a summary table without running segmentation or quantification.
- [scripts/qc/build_analysis_manifest.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/qc/build_analysis_manifest.py): builds `derivatives/manifests/analysis_manifest.csv`, the QC-gated handoff into cohort quantification.
- [scripts/qc/build_project_status.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/qc/build_project_status.py): builds `reports/qc/project_status.md/json`, the compact V1 readiness report.
- [scripts/qc/build_study_metadata.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/scripts/qc/build_study_metadata.py): builds `derivatives/manifests/study_metadata.csv`, the editable side/group/lesion/review table consumed by the analysis manifest.
- [src/lys_bbb/conversion.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/conversion.py): reusable Bruker conversion implementation; the root `buker_nifty_flip.py` is only a compatibility wrapper.
- [src/lys_bbb/flash_pair.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/flash_pair.py): reusable implementation for the current FLASH pair pipeline.
- [src/lys_bbb/flash_cohort.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/flash_cohort.py): reusable cohort discovery, metric extraction, and D7-D1 delta implementation.
- [src/lys_bbb/analysis_manifest.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/analysis_manifest.py): reusable QC gate for the final analysis manifest.
- [src/lys_bbb/brain_mask_manifest.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/brain_mask_manifest.py): reusable validator for candidate manual/model brain masks and mask-QC reports.
- [src/lys_bbb/brain_mask_postprocess.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/brain_mask_postprocess.py): reusable candidate-mask post-processing implementation.
- [src/lys_bbb/mask_workflow.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/mask_workflow.py): reusable manual-mask worklist/dashboard and nnU-Net preparation implementation.
- [src/lys_bbb/pipeline_status.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/pipeline_status.py): reusable readiness summary and Markdown/JSON status report implementation.
- [src/lys_bbb/study_metadata.py](/Users/paul-andreaslaize/Documents/LYS_PROJ2/src/lys_bbb/study_metadata.py): reusable study metadata builder and validator for side-aware quantification inputs.
- [docs/nnunet_active_learning.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/nnunet_active_learning.md): Mac/cloud active-learning workflow for corrected pre masks and nnU-Net v2.
- [docs/t2_lesion_t1_integration.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/t2_lesion_t1_integration.md): planned T2w lesion-model integration with T1 FLASH enhancement quantification.
- [deprecated/sherm/](/Users/paul-andreaslaize/Documents/LYS_PROJ2/deprecated/sherm): retired SHERM-inspired mask code, kept only for historical reference or controlled comparison.

Current conversion behavior:

- Detects Bruker scans whose protocol name contains `T1_FLASH_3D`.
- Converts matching Bruker scans to NIfTI using `brkraw`.
- Writes original sagittal NIfTI files.
- Reorients sagittal scans to coronal-primary NIfTI using nibabel orientation metadata.
- Writes native `_coronal.nii.gz` files for quantitative work.
- Currently writes `_coronal_fijiDisplay.nii.gz` files by default unless `--no-fiji-display` is passed. These include display-oriented vertical flipping and square in-plane pixels so Fiji looks closer to the QC PNGs.
- Intended V1 policy is to generate Fiji display files only for explicit viewing/review runs. Until the CLI default is changed, pass `--no-fiji-display` for normal quantitative conversion runs.
- Can write slab NIfTI outputs for visualization only when explicitly requested.
- Generates conversion QC PNGs and pre/post/difference QC PNGs when exactly two T1 FLASH scans are detected.

Current quantification behavior:

- Processes one pre/post native coronal pair at a time.
- Also has an initial cohort command that discovers converted `output/all_mice/<case>` folders, runs pair quantification, writes `cohort_sessions.csv`, `cohort_quantification.csv`, and `cohort_metadata.json`, and computes D7-D1 rows when unique D1/D7 pairs exist.
- Registers post-contrast to pre-contrast with rigid SimpleITK registration.
- Registration QC can be checked independently with `scripts/qc/qc_pre_post_registration.py`.
- Requires `--mask path/to/mask.nii.gz` for pair processing, or a resolved brain mask path for cohort processing.
- Applies the supplied pre-space mask to pre and registered-post images after post-to-pre registration.
- Applies smooth bias correction and median normalization.
- Writes a percent-enhancement map and whole-mask summary statistics; the cohort layer can additionally compute provisional side-aware correction, enhancing volume, integrated burden, and D7-D1 deltas when the required inputs are supplied.
- Writes lightweight outputs by default and heavy debug/intermediate NIfTIs only when requested.

Current limitations that future agents must respect:

- Raw MouseBrainExtractor masks are pre-labels only. Correct them in ITK-SNAP before using them for quantification or nnU-Net labels.
- The cohort CSV and side-aware/leakage-volume metrics are first-iteration engineering outputs. They are not final biological endpoints until corrected brain masks, side assignments, lesion/ROI masks, registration QC, threshold validation, and inclusion/exclusion decisions are locked.
- Atlas mapping, Allen Brain Atlas registration, and final polished lesion alignment with T2 images are not current V1 outputs. First-pass lesion-mask and side-aware hooks exist in cohort quantification, but final lesion-centered reporting still requires T2 conversion/pairing, T2-to-T1 registration QC, nearest-neighbor lesion-mask transfer into T1 pre space, explicit inside/outside-lesion ROI rows, and locked QC decisions. RARE-VTR T1 fitting and DCE/Ktrans modeling are outside the expected project scope because the needed acquisitions are not available to the user.
- Do not spend implementation effort on polished downstream reporting before the brain segmentation failure modes are understood and controlled.

## V1 Target

V1 should become a practical full pipeline for the current `Thrombin_03_ESR3P` dataset:

1. Inventory all raw Bruker sessions.
2. Detect animal ID and time point (`D1` or `D7`) from session names and metadata.
3. Accept an optional CSV/manifest to override or supply animal ID, time point, and pre/post scan role.
4. Detect pre/post `T1_FLASH_3D_Glymphatic_Sag` scans.
5. Convert sagittal Bruker scans to native coronal NIfTI.
6. Register post to pre within each session.
7. Extract an accurate brain mask on coronal slices 50-170.
8. Correct smooth intensity bias and normalize pre/post images.
9. Quantify simple T1-weighted gadolinium enhancement metrics inside the brain mask.
10. Add ipsilateral/contralateral metrics once side assignment and midline handling are reliable.
11. Compare D1 versus D7 for each animal where both time points are present.
12. Write one combined CSV and report for all mice and sessions, plus compact QC outputs.

V1 should support independent commands for development and debugging, but the final workflow should also have a single full-pipeline command that can run inventory, optional manifest loading, conversion, preprocessing, quantification, D1/D7 comparison, and combined reporting for a folder of T1 gadolinium-leakage MRI data.

## V1 Metrics

Start with simple, transparent metrics:

- Whole-brain post/pre ratio.
- Whole-brain percent enhancement.
- Whole-brain post-minus-pre as a secondary diagnostic metric.
- Leakage-positive area or volume after a documented thresholding strategy is chosen and validated.
- Ipsilateral/contralateral ratio at D1 and D7 after robust side assignment exists.

Do not overcomplicate V1 with atlas ROI metrics or advanced modeling before the brain mask is reliable.

All metric formulas, thresholds, normalization choices, and slice ranges must be written to metadata.

## Brain Extraction Status

Active quantification requires a supplied pre-space brain mask. The current
mask production path is cloud MouseBrainExtractor pre-labels corrected in
ITK-SNAP, followed by optional nnU-Net fine-tuning once enough corrected labels
exist. The SHERM-inspired code has been moved to `deprecated/sherm/` and is not
an active fallback.

The detailed current plan is in [docs/brain_segmentation.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/brain_segmentation.md) and [docs/nnunet_active_learning.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/nnunet_active_learning.md).

The mask should closely follow the actual murine brain contour on the central
coronal slices and should not include skull, skin, glands, bright rim, or
external noise. Missing brain tissue and including non-brain tissue are both
unacceptable for final V1.

Current fixed slice policy:

- Use coronal slices 50-170 for V1 QC and interpretation.
- Slices before 50 and after 170 are too noisy or not useful enough for the current converted scans.
- Keep these values as logical defaults and constants for now. They can remain command-line options for QC display, but they do not generate a mask.

Current operational path:

- Correct MouseBrainExtractor pre-labels in ITK-SNAP.
- Save corrected masks on the exact native pre-contrast `_coronal.nii.gz` grid.
- Refresh `reports/qc/qc_manifest.csv`, then run `scripts/masks/build_manual_mask_workflow.py` to update `reports/qc/manual_mask_worklist.csv`, `reports/qc/manual_mask_dashboard.html`, and `derivatives/brain_seg/nnunet_manifest.csv`.
- The manual-mask workflow preserves `mask_review`, `registration_review`, and `review_notes` across rebuilds. Use `pass`, `review`, or `fail`. Its comparison montages show manual versus MouseBrainExtractor contours plus added/removed voxels; nnU-Net inclusion requires an explicit mask-review pass.
- Run `scripts/qc/build_analysis_manifest.py` to update `derivatives/manifests/analysis_manifest.csv`. This manifest is the preferred handoff to `scripts/quantification/quantify_flash_cohort.py --roi-manifest`.
- Keep `group`, `ipsilateral_side`, `lesion_mask_path`, and manual review decisions in `derivatives/manifests/study_metadata.csv` from `scripts/qc/build_study_metadata.py`, then rebuild the analysis manifest with `--metadata-manifest`. Metadata can request include/exclude decisions but cannot bypass missing-mask, bad-mask, or registration QC gates.
- When a brain-mask model produces predictions, run `scripts/masks/postprocess_brain_masks.py` on `derivatives/brain_seg/nnunet_preds/{case_id}.nii.gz`, then run `scripts/masks/build_brain_mask_manifest.py` on the cleaned predictions before building the analysis manifest.
- For development-only downstream testing with non-final masks, use `build_analysis_manifest.py --allow-review-masks-for-testing`; never treat those outputs as final biological results.
- Run `scripts/qc/build_project_status.py` after those manifests to update the compact current-blocker and next-command report.
- Use those corrected masks directly for quantification or as nnU-Net labels.
- Treat masks marked `_pre_manual_mask_done.nii.gz` as the default eligible nnU-Net labels after QC; unmarked review masks should not silently become training labels.
- Pre-contrast masks can be reused for registered post-contrast images only after post-to-pre registration QC is good.
- If registration QC fails, fix/review registration or exclude the case rather than creating an independent post mask.
- A later template-propagation workflow may use manually corrected pre masks to propagate masks across animals or D1/D7 time points, with QC and manual correction of failures.

The goal is not merely conservative or inclusive masking. The goal is accurate masking. Missing brain tissue and including non-brain tissue are both unacceptable for final V1.

Bad masks are the first and most important QC failure mode. Formal pass/review/fail fields are not required yet, but agents should report mask problems clearly in chat and should not present final biological conclusions from failed masks.

If masks remain unreliable near final V1, add an optional manual approval step before including sessions in the combined CSV.

## Output Policy

Default outputs should be lightweight:

- Brain mask NIfTI.
- Main enhancement map NIfTI.
- Registration transform.
- QC PNGs.
- Session metadata JSON.
- Session summary CSV while developing.
- Provisional cohort CSV for all discovered converted mice/sessions, and final combined CSV/report after masks and QC decisions are locked.

Do not write many large NIfTI intermediates by default. Provide explicit options such as `--save-intermediates`, `--save-all-maps`, or a dedicated debug output directory for requested debugging products.

Fiji-viewable NIfTI files should be generated only when explicitly requested. They are for visual review, not quantification. The current conversion CLI still writes them by default, so use `--no-fiji-display` for normal quantitative runs unless the task is specifically to make Fiji-viewable files.

When debug outputs are intentionally kept, store them in a clearly named debug folder such as `derivatives/debug/` or `derivatives/flash_v1_debug/` rather than mixing them with compact final outputs.

## Intended Directory Organization

Raw data stays outside the repo:

```text
/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P
```

Current and planned repo structure:

```text
AGENT.md
README.md
scripts/conversion/convert_bruker_t1_flash.py
configs/
scripts/
src/lys_bbb/
reports/inventory/
reports/qc/
derivatives/flash_v1_minimal/
derivatives/flash_v1_debug/
output/
tests/
```

For final V1, organize outputs by animal ID and time point where practical, for example:

```text
derivatives/flash_v1_minimal/C25S1/D1/
derivatives/flash_v1_minimal/C25S1/D7/
```

The current cohort CSV is a provisional engineering/QC product. The final downstream statistics file should be one combined CSV/report containing all included mice and sessions after corrected masks, registration QC, side/ROI metadata, and inclusion/exclusion decisions are locked.

## V1 Implementation Plan

### 1. Inventory And Pair Sessions

- Inventory all Bruker sessions under `Thrombin_03_ESR3P`.
- Parse animal ID and time point from session folder names.
- Read an optional CSV/manifest for animal ID, time point, pre/post role, scan ID, and inclusion/exclusion overrides.
- Group sessions by animal ID with D1 and D7 entries.
- Detect pre/post T1 FLASH scans using metadata and protocol names.
- Keep scan-order fallback logic because current scans appear consistent.
- Write a compact inventory and a combined planned-processing table.

### 2. Conversion And Orientation

- Convert pre/post T1 FLASH scans to native coronal NIfTI.
- Keep `_coronal.nii.gz` as the quantitative image.
- Generate Fiji display files only on request.
- Preserve affine, spacing, orientation, scan IDs, and source paths in metadata.
- Validate sagittal-to-coronal orientation with QC PNGs and known anatomy.

### 3. Registration

- Rigidly register post-contrast to pre-contrast within each session.
- Save the transform by default.
- Save registered image only when needed for debug or downstream processing.
- Add QC overlays and numeric registration diagnostics.

### 4. Brain Extraction

- Correct cloud MouseBrainExtractor pre-labels in ITK-SNAP on native pre-contrast images.
- Compare corrected masks against user-provided visual expectations and, if available, manual reference slices.
- Build a corrected-mask set before treating cohort quantification as final. Start with 8-12 representative pre-contrast masks if possible; manually correcting all pre masks may be the strongest final route if the dataset remains about 35-36 pre/post pairs.
- Consider template/registration propagation from corrected pre masks if it reduces manual work without weakening QC.
- If 10-15 corrected pre masks can be made, consider an active-learning nnU-Net v2 experiment: train on corrected pre masks only, hold out animals rather than random scans, predict remaining masks, correct failures, and retrain.
- Use native pre-contrast `_coronal.nii.gz` images for nnU-Net training. Do not train on PNG QC montages, post-gadolinium images, or raw automatic masks.
- Keep mask QC PNGs mandatory.
- Do not trust enhancement summaries when mask QC fails.

### 5. Correction And Normalization

- Apply smooth bias-field correction or an equivalent low-frequency correction strategy.
- Normalize pre/post intensity inside reliable brain tissue.
- Keep assumptions explicit because static FLASH signal is not absolute concentration.
- Avoid including background or skull in normalization statistics.

### 6. Quantification

- Compute simple whole-brain enhancement metrics.
- Treat leakage area/volume and ipsilateral/contralateral ratio as provisional until threshold validation, side metadata, and mask QC are locked.
- Keep D1 and D7 as the main longitudinal time points.
- Compute D1 versus D7 comparisons for each animal where both time points are present.
- Write animal ID, time point, source session, scan IDs, mask volume, metrics, D1/D7 comparisons, and processing parameters to output tables.

### 7. Batch Pipeline

- Preserve the ability to run each step independently.
- Add a final full-pipeline command that can run inventory, optional manifest loading, conversion, preprocessing, quantification, D1/D7 comparison, and final combined report generation with locked QC inputs.
- Keep default parameters logical so the user does not need long command lines for normal use.
- Use config/manifest files later when the algorithm is stable enough for all animals.

## V1 Outputs

Final V1 should produce:

- Compact per-session QC PNGs.
- Native coronal quantitative NIfTI files when conversion is requested.
- Brain mask NIfTI per session.
- Main enhancement map per session.
- Minimal metadata JSON per session.
- One combined CSV/report for all mice and sessions with animal ID, time point, and D1/D7 comparisons.
- Optional debug folder with extra NIfTI intermediates only when requested.

The final combined CSV should include at least:

- Animal ID.
- Time point (`D1` or `D7`).
- Session ID.
- Pre scan ID and post scan ID.
- Mask voxel count and mask volume.
- Whole-brain post/pre ratio.
- Whole-brain percent enhancement.
- Leakage-positive area/volume once thresholding is validated.
- Ipsilateral/contralateral ratio once side assignment and midline handling are validated.
- D1 versus D7 change metrics where paired time points exist.
- Paths to key QC images.

## V1 Limitations

- Current V1 uses static T1-weighted FLASH enhancement, not absolute T1 or Ktrans.
- The project is scoped to the T1 gadolinium-leakage data available to the user, not future RARE-VTR or DCE acquisitions.
- Corrected brain-mask production/QC is currently the major blocker for trustworthy cohort quantification.
- Enhancement metrics are sensitive to registration, coil bias, scanner gain, injection timing, normalization, and mask quality.
- Treatment groups are blinded and should not appear in current output tables.
- Atlas mapping and combined T2w lesion/T1w BBB leakage analysis are future work.

## Future T2 Lesion Integration

Future agents should keep brain masking, lesion segmentation, and BBB
enhancement quantification as separate but connected steps.

The active plan is tracked in [docs/t2_lesion_t1_integration.md](/Users/paul-andreaslaize/Documents/LYS_PROJ2/docs/t2_lesion_t1_integration.md). A good T2w lesion model defines lesion ROIs but does not replace the T1 brain mask. The T1 brain mask remains required for T1 normalization, skull/background exclusion, lesion-mask clipping, hemisphere/midline handling, whole-brain and outside-lesion regions, and QC.

For the current static pre/post T1 FLASH data, lesion-aware outputs must still
be reported as semi-quantitative enhancement or leakage burden, not Ktrans, Ki,
absolute permeability, `vp`, `ve`, or DCE-MRI modeling. Useful planned
extensions include z-leakage maps relative to a fixed contralateral reference,
peri-lesional rims, exclusion masks for normally enhancing or artifact-prone
regions, edema-corrected D1 T2 lesion volume, and D1-to-D7 persistent,
resolved, and new/delayed leakage compartments.

Core concept:

```text
T2w = lesion definition
T1 pre/post = BBB leakage measurement
mirrored contralateral ROI = internal control
```

The current V1 brain-mask path remains first: train or apply nnU-Net on
corrected pre-Gd T1 FLASH brain masks, register post-Gd T1 to pre-Gd T1, and
quantify whole-brain plus ipsilateral/contralateral enhancement. Do not define
the stroke lesion from post-Gd enhancement as a primary route, because that
would make leakage quantification circular.

A later lesion stage should:

- Convert the high-resolution T2w scans.
- Register T2w images to the matching pre-Gd T1 FLASH space.
- Segment the stroke lesion on T2w.
- Transform the lesion mask into pre-Gd T1 space.
- Mirror the lesion ROI to the contralateral hemisphere.
- Quantify enhancement in lesion ROI, peri-lesional rim, mirrored contralateral ROI, ipsilateral hemisphere, contralateral hemisphere, outside-lesion brain, and whole brain.

Model development should stay staged:

- `Dataset501_MouseBrainMask`: input pre-Gd T1, label brain mask.
- `Dataset502_MouseLesionT2`: input T2w high-resolution image, label lesion mask.
- Optional later `Dataset503_MouseBrainLesionMultichannel` only after the brain-mask and lesion-mask tasks work independently.

Future lesion-based outputs should include lesion mean CE %, lesion median CE
%, lesion 95th percentile CE %, enhancing volume inside lesion, percent lesion
enhancing, lesion integrated leakage burden, lesion/mirrored contralateral
enhancement ratio, and D7-D1 change for all lesion-based metrics.

## V2 Roadmap

V2 should begin only after V1 can produce trustworthy brain-mask-based D1/D7 metrics.

Potential V2 goals:

- A robust folder-plus-optional-manifest command that can process a full experiment with minimal manual intervention.
- Accurate Allen Brain Atlas mapping.
- Robust nonlinear registration and transform management.
- Regional/ROI quantification beyond whole brain.
- Alignment of T2w lesion-volume images with T1 gadolinium enhancement analysis using T2w for lesion definition and T1 pre/post for BBB leakage measurement.
- Combined reporting of T2w lesion volumes and T1 BBB leakage metrics for deeper analyses.
- Better segmentation/parcellation and anatomical QC.
- nnU-Net active learning as a mask-production accelerator once enough corrected MouseBrainExtractor pre-labels exist. Learning-based outputs must remain auditable and should not replace visual QC.
- Manual-mask/template-propagation workflows if they reduce manual work while preserving final mask QC.

## Implementation Rules For Future Agents

- Do not overwrite or modify raw Bruker data.
- Use `lys-bbb` for all project commands.
- Treat V1 as current-data FLASH pre/post enhancement, not protocols.io RARE-VTR T1 mapping.
- Keep the protocols.io and DCE papers as method references only, not as roadmap branches or claims about what current data can do.
- Make correction/QC of MouseBrainExtractor pre-labels on slices 50-170 the next priority, with nnU-Net fine-tuning after enough corrected labels exist.
- Prioritize reliable brain segmentation over cohort CSVs, atlas mapping, graphing, leakage thresholds, and ipsilateral/contralateral metrics.
- Keep brain masking, T2w lesion segmentation, and T1w BBB enhancement quantification as separate stages until each one is validated.
- Keep visual QC for conversion, orientation, registration, masking, normalization, and enhancement outputs.
- Preserve affine, spacing, orientation, scan IDs, source paths, and processing parameters.
- Use native `_coronal.nii.gz` files for quantification.
- Keep `_fijiDisplay.nii.gz` and slab files separate as visualization-only products.
- For normal conversion/quantification runs, pass `--no-fiji-display` until the conversion CLI default is changed.
- Keep outputs lightweight by default.
- Put requested debug products in a clear debug folder.
- Prefer reproducible CLI scripts and explicit config over notebook-only workflows.
- Keep defaults logical so normal commands remain short.
- Do not claim provisional cohort, ipsilateral/contralateral, or leakage-volume metrics are final biological endpoints until masks, registration QC, side metadata, thresholds, and inclusion/exclusion criteria are locked. Atlas ROI analysis and combined T2w/T1w reporting are not implemented.
- Do not claim RARE-VTR T1 fitting or DCE/Ktrans modeling as implemented or planned project deliverables.
- Do not plan future RARE-VTR or DCE/Ktrans acquisition-dependent features as project goals.
- Add focused tests when adding parsing, conversion, masking, registration, normalization, metrics, and batch reporting logic.
