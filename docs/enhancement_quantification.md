# Enhancement quantification

## Measurement scope

The available images are one pre-Gd and one static post-Gd T1-weighted volume per
session. They support relative signal enhancement measurements, not tracer-kinetic BBB
permeability.

Allowed language:

- T1-weighted gadolinium enhancement;
- contrast-enhancing volume after a validated threshold;
- relative enhancement or leakage burden.

Disallowed claims:

- absolute T1 or gadolinium concentration;
- `Ktrans`, `Ki`, `vp`, or `ve`;
- absolute BBB permeability or DCE modeling.

## Reference space and mask

Post-Gd T1 is rigidly registered to native pre-Gd T1. The same approved pre-space brain
mask is applied to both images. MRI intensities use linear interpolation; masks use
nearest-neighbour interpolation.

This post→pre transform belongs only to enhancement. Atlas mapping independently uses
MRI-atlas→pre-T1 and pre-T1→native-T2 branches and must never consume the post-Gd image
or post→pre artifact.

The full approved brain mask defines whole-brain analysis. Coronal slices 50–170 are a
standardized QC display range only. They do not crop the mask or define an anatomical
analysis slab.

## Basic maps

For registered signals `S_pre(x)` and `S_post(x)`:

```text
difference(x) = S_post(x) - S_pre(x)
ratio(x)      = S_post(x) / (S_pre(x) + epsilon)
PE(x)         = 100 × difference(x) / (S_pre(x) + epsilon)
```

These raw formulas remain sensitive to scanner gain, coil loading, bias field, motion,
injection dose, and time after injection. Acquisition metadata must be retained with
every result.

## Current implementation and warning

The typed application path requires an already approved registered post-Gd image and
the exact approved pre-space mask. It verifies their checksums and disables the legacy
pair code's registration step, so quantification cannot silently produce a different
transform. The resulting map, summary, QC, and metadata are stored with exact dependency
IDs and are explicitly marked `PROVISIONAL`.

The calculation still independently estimates a smooth correction field and a masked
median scale for pre and post images. This can make regional contrast easier to compare,
but it may remove diffuse or whole-brain enhancement. Therefore current
`percent_enhancement` outputs are provisional relative-enhancement engineering outputs,
not a validated primary endpoint. The exploratory CLI retains compatibility behavior;
it is not the app's approval path.

Do not silently rename them as quantitative percent signal change. Before production,
the code should emit explicitly differentiated maps such as:

```text
raw_registered_percent_change
paired_gain_corrected_percent_change
reference_region_corrected_enhancement
spatially_normalized_relative_enhancement
```

## Required signal-preservation tests

Create simulated post images from real pre images with known changes:

| Simulation | Purpose |
|---|---|
| Uniform +10% brain signal | Test preservation of diffuse enhancement |
| Focal +30% region | Test focal sensitivity and boundary behavior |
| One hemisphere +20% | Test broad unilateral enhancement |
| Smooth cortical +20% | Test interaction with bias correction |
| Scanner gain +10%, no biology | Test global drift correction |
| Bias-field change, no biology | Test false enhancement from coil inhomogeneity |

Run the complete registration/correction/normalization path and measure recovered signal.
Compare at minimum:

1. no intensity normalization;
2. one paired scale applied to both images;
3. a predeclared nonenhancing reference region;
4. contralateral-reference correction;
5. an external phantom if one is available.

Choose and freeze a primary method only after these tests and real QC agree. Record the
method, reference ROI, threshold, and parameters in metadata.

## Provisional outputs

Existing cohort code can calculate whole-mask summaries, side-aware values, lesion-hook
metrics, enhancing volume, integrated positive enhancement, and D1-to-D7 deltas. These
remain secondary engineering outputs until:

- brain masks and registrations are approved;
- injection timing/dose metadata are available or comparability is justified;
- normalization preserves the intended signal;
- leakage thresholds are defined on a separate control/training subset;
- duplicate sessions and exclusions are resolved.

Do not select thresholds after inspecting all experimental groups together. Prefer a
predeclared control or reference distribution and report threshold sensitivity.

## Desktop result status

Human approval of a brain mask and registration is necessary but not sufficient to make
the enhancement measurement official. Until a specific normalization/measurement
method passes the signal-preservation tests above and its method record is approved, the
desktop application must label resulting measurements `Provisional` even if their input
artifacts have been reviewed.

Artifact review, method approval, result review, and successful execution are separate
records. Updating an approved mask, registration, input image, or method marks dependent
measurements outdated; it does not delete or silently recompute their previous values.

## Biological confounds

Bright signal may represent vessels, venous sinuses, meninges, choroid plexus, CSF,
circumventricular structures, or extracranial enhancement rather than parenchymal BBB
passage. These compartments should be reviewed and later reported separately where the
resolution permits; they should not be hidden by an undocumented cleanup operation.
