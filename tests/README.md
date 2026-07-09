# Tests

Add focused tests here as the V1 modules become reusable.

Initial priorities:

- Animal ID and D1/D7 time-point parsing.
- Bruker scan role classification for pre/post T1 FLASH scans.
- Orientation transform behavior.
- Mask-required pair quantification behavior.
- Brain-mask QC slice-range behavior, especially fixed V1 slices 50-170.
- Mask metric calculations that exclude non-brain voxels.
- Registration and normalization metadata.
- Whole-brain enhancement metric formulas.
- Ipsilateral/contralateral metric calculations on synthetic masks.
- Optional CSV/manifest parsing for animal ID, time point, scan role, and inclusion/exclusion overrides.
- D1 versus D7 per-animal comparison metrics for cohort rows.
- Future nnU-Net manifest conversion checks: image/mask shape and affine match, labels are binary, images use `_0000`, and labels do not.

Current focused coverage includes normalization, enhancement formulas, montage
slice selection, required pair masks, cohort case discovery, synthetic
ipsi/contra correction, leakage-volume thresholding, and D7-D1 delta rows.

The next useful segmentation tests should be tied to a small manual or
semi-manual validation set, not only synthetic images. Until that exists,
visual QC remains mandatory for corrected MouseBrainExtractor masks and future
nnU-Net predictions.
