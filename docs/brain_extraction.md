# T1 brain extraction

## Current decision

Create one brain mask on native pre-Gd T1, review it, and use that exact approved mask
for pre-Gd T1 and the registered post-Gd T1. Do not independently segment post-Gd T1 by
default.

The selected pre-label approach is the T1-guided RS2-Net M-seam refinement in
[`notebooks/brain_extraction_rs2_refinement_colab.ipynb`](../notebooks/brain_extraction_rs2_refinement_colab.ipynb).
Review of all four candidates across the frozen ten-case cohort found M-seam preferable
to raw RS2, marker-watershed, and random-walker. It was also visibly better than the
earlier MBE, mismatched-control, and threshold-only experiments. This selects the
automatic draft generator; it does not make any generated mask ground truth or remove
the human-review requirement.

The review identified two repeatable M-seam cleanup needs: small skull components that
remain connected only through neighbouring slices, and short abnormal slice runs
bracketed by stable, similar masks. The selected pipeline therefore adds conservative
3-D continuity cleanup after the image-guided M-seam cut. This new cleanup must be
reviewed on the same ten cases before its thresholds are frozen for desktop approval.

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

### Local macOS inference

Install the exact reviewed RS2 source and weight once:

```bash
conda run -n lys-bbb python -m pip install -e '.[t1-inference]'

conda run --no-capture-output -n lys-bbb lys-bbb-t1-mask-setup \
  --destination "$HOME/Library/Application Support/LYS BBB/models/rs2net-m-seam-v1"
```

The setup validates source commit `144b032d...` and model SHA-256
`f7fef315...f3659371`. It refuses to replace an existing release.

Generate one automatic draft directly from a native pre-Gd T1 NIfTI:

```bash
conda run --no-capture-output -n lys-bbb lys-bbb-t1-mask \
  --release "$HOME/Library/Application Support/LYS BBB/models/rs2net-m-seam-v1" \
  --input /absolute/path/to/mouse_pre_t1.nii.gz \
  --output /absolute/path/to/a/new/output_directory \
  --device auto
```

The reviewed method uses eight-way test-time mirroring. In `auto` mode it uses CUDA when
available and otherwise CPU, because exact eight-way TTA exceeded the tested M1's MPS
memory. For a faster local draft variant, explicitly use:

```bash
conda run --no-capture-output -n lys-bbb lys-bbb-t1-mask \
  --release "$HOME/Library/Application Support/LYS BBB/models/rs2net-m-seam-v1" \
  --input /absolute/path/to/mouse_pre_t1.nii.gz \
  --output /absolute/path/to/a/new/output_directory \
  --device mps \
  --disable-tta
```

Disabling TTA is recorded as `explicit_no_tta_local_draft`; it is not silently treated
as the reviewed TTA variant and still requires visual review. With the pinned MONAI 1.4
runtime, the tested M1 completed one case in approximately 83 seconds. Its raw mask had
Dice 0.980 against the Colab TTA mask for that case, which is useful compatibility
evidence but not equivalence.

The command never overwrites its output directory. It preserves raw RS2 and the final
draft as separate native-grid masks and writes a QC PNG, change masks, checksums, method
settings, regularity results, and `metadata.json`. A Metal or MPS memory error in the log
invalidates the run even if the upstream process returns success.

To apply the selected refinement to an existing raw RS2 output without rerunning the
network:

```bash
conda run -n lys-bbb lys-bbb-t1-mask \
  --input /absolute/path/to/mouse_pre_t1.nii.gz \
  --raw-mask /absolute/path/to/raw_rs2_mask.nii.gz \
  --output /absolute/path/to/a/new/output_directory
```

All outputs remain automatic drafts requiring complete 3-D review.

### Frozen benchmark reproduction

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

The selected M-seam pipeline additionally performs two narrow automatic cleanup steps:

- remove a true disconnected 3-D component, or a small secondary in-plane component,
  only in the established central brain profile;
- repair a short abnormal run only when its two flanking masks have high Dice and
  similar area, using physical signed-distance interpolation constrained to raw RS2.

Comparable bilateral components at tapering endpoints are retained. Long changes,
disagreeing flanks, and repairs above the configured change limit are left unchanged and
reported for review. Every changed and skipped slice is written to provenance.

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

## Frozen benchmark output contract

The Colab benchmark writes:

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
control notebook (rodent T2/T2* CAMRI and human-T1 deepbet) remain tracked provenance
assets. They established RS2 as the strongest candidate and should not be expanded or
treated as application entry points. The obsolete standalone MBE adapter has been
removed. Threshold-only RS2 changes did not reliably remove the superior skull cap.

Custom nnU-Net training is deferred. The existing preparation utilities are retained as
tested research tools, but they are not an active milestone and should not drive current
application architecture.
