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

## Current implementation warning

The current pair code independently estimates a smooth correction field and a masked
median scale for pre and post images. This can make regional contrast easier to compare,
but it may remove diffuse or whole-brain enhancement. Therefore current
`percent_enhancement` outputs are provisional relative-enhancement engineering outputs,
not a validated primary endpoint.

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

## Biological confounds

Bright signal may represent vessels, venous sinuses, meninges, choroid plexus, CSF,
circumventricular structures, or extracranial enhancement rather than parenchymal BBB
passage. These compartments should be reviewed and later reported separately where the
resolution permits; they should not be hidden by an undocumented cleanup operation.
