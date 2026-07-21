# T1 brain extraction

## Current decision

Create one brain mask on native pre-Gd T1, review it, and use that exact approved mask
for pre-Gd T1 and the registered post-Gd T1. Do not independently segment post-Gd T1 by
default.

The current best pre-label approach is the T1-guided RS2-Net refinement experiment in
[`notebooks/brain_extraction_rs2_refinement_colab.ipynb`](../notebooks/brain_extraction_rs2_refinement_colab.ipynb).
It is visibly better than the earlier MBE, mismatched-control, and threshold-only
experiments on this cohort. This is a practical front-runner decision, not ground truth
or formal method approval.

No individual refinement variant is yet the approved default. Raw RS2, M-seam,
marker-watershed, and random-walker masks must be reviewed consistently across the ten
frozen cases before one version is frozen for desktop integration.

## Evidence from the completed refinement run

The downloaded ten-case run:

- produced native-grid, binary, non-empty candidates for every method and case;
- preserved raw RS2 as an immutable baseline;
- allowed corrections only to remove voxels from raw RS2;
- detected a confident superior dark-gap correction in seven cases;
- left raw RS2 unchanged in three cases where the gate failed; and
- generated per-case metadata, removed-voxel masks, QC montages, and validation tables.

The main remaining risk is excessive removal of superior cortex or an anatomically
implausible discontinuity across slices. A clean central slice is insufficient evidence;
review the full posterior-anterior extent.

## Active reproducible workflow

The frozen cohort is `config/brain_extraction_benchmark_10.txt`. Rebuild its input
archive with:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --case-file config/brain_extraction_benchmark_10.txt \
  --out-dir derivatives/brain_extraction/colab \
  --package-name t1_brain_extraction_benchmark_10 \
  --overwrite
```

Run the RS2 refinement notebook in a fresh Colab T4 runtime and upload that archive.
Review the downloaded result locally:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_rs2_refinement_results.zip
```

The notebook is generated from
`scripts/brain_extraction/build_rs2_refinement_notebook.py`; the tested algorithms live
in `src/lys_bbb/brain_mask_refinement.py`. Change the source and rebuild the notebook
rather than editing its embedded algorithm cell independently.

## Three-dimensional regularity QC

A plausible 3-D mouse brain mask should usually show:

- gradual cross-sectional area changes across adjacent slices;
- a smoothly moving in-plane centroid;
- a reasonably smooth surface in physical units; and
- no isolated one-slice notch, protrusion, or internal empty slice.

`assess_mask_regularity` in `lys_bbb.brain_mask_refinement` reports:

- physical slice-area profile;
- adjacent area-change and one-slice-deviation warnings;
- physical centroid-step profile;
- connected components and internal slice gaps;
- voxel-face surface area, surface-to-volume ratio, and compactness.

These are QC signals, not anatomical truth. Thresholds are configurable heuristics and
must be calibrated against reviewed masks. They may prioritize slices for inspection or
block an automatic promotion, but they must never approve a mask or automatically alter
one. Normal anterior/posterior tapering must not be mistaken for an error.

The refinement notebook records this report for raw and corrected candidates so a
visually attractive local correction cannot hide a new 3-D discontinuity.

## Human review contract

Preserve three separate products:

```text
automatic prediction       immutable
editable correction        working copy
accepted reviewed mask     immutable after approval
```

Review in ITK-SNAP and inspect olfactory bulbs, superior cortex, cerebellum, inferior
brain, brainstem, anterior/posterior endpoints, and every regularity warning. Approval
must record reviewer, time, source prediction, correction method, and checksum.

A legacy `_done` filename is not approval.

## Selection criteria

When reviewed references exist, compare candidates using:

- Dice/Jaccard, precision, and recall;
- volume error in mm³ and percent;
- mean surface distance and 95th-percentile Hausdorff distance;
- connected components, boundary contact, and 3-D regularity warnings;
- hard-failure count and manual correction time; and
- qualitative region-specific failures.

The preferred pre-label is the reproducible method with few hard failures and low safe
correction burden, not automatically the highest mean Dice.

## Output contract

Every model/correction writes:

```text
predictions/<model>/<case_id>_brain_mask.nii.gz
metadata/<model>/<case_id>.json
logs/<model>/<case_id>.log
```

Masks must be binary and match the native input shape and affine. Metadata records model
and weight identity, code revision, preprocessing, orientation handling, threshold,
postprocessing, runtime, checksum, QC, and success/failure.

## Frozen historical comparisons

The primary benchmark notebook (MBE isotropic, MBE anisotropic, raw RS2) and optional
control notebook (rodent T2/T2* CAMRI and human-T1 deepbet) remain tracked reproducibility
assets. They established RS2 as the strongest candidate and should not be expanded.
Threshold-only RS2 changes did not reliably remove the superior skull cap.

Custom nnU-Net training is deferred. The existing preparation utilities are retained as
tested research tools, but they are not an active milestone and should not drive current
application architecture.
