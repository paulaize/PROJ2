# T2 Lesion To T1 FLASH Integration Plan

This document tracks the planned link between the T2w lesion-segmentation model
and the T1 FLASH gadolinium-enhancement pipeline.

## Goal

Use T2w images to define the stroke lesion independently, then quantify
semi-quantitative T1 FLASH gadolinium enhancement inside and outside that lesion
after the lesion mask has been transformed into the native pre-Gd T1 FLASH
space.

Conceptual rule:

```text
T2w image/model = lesion definition
T1 pre/post FLASH = BBB leakage measurement
T1 brain mask = valid tissue support, normalization support, clipping, and hemispheres
mirrored contralateral lesion ROI = internal control
```

This keeps lesion definition separate from the post-Gd enhancement signal and
avoids circular analysis.

## Quantification Boundary

With the current data, use the terms `contrast enhancement`, `gadolinium
enhancement`, `BBB enhancement burden`, or `semi-quantitative leakage burden`.
Do not label outputs as `Ktrans`, `Ki`, absolute permeability, permeability
surface-area product, `vp`, `ve`, or `kep`.

Those pharmacokinetic biomarkers require a different acquisition: baseline T1
mapping, ideally B1 correction where relevant, dynamic T1-weighted imaging
during and after injection, signal-to-gadolinium-concentration conversion,
input-function handling, motion correction, and tracer-kinetic modeling. If a
future acquisition ever provides those data, treat DCE-MRI as a separate V2+
branch rather than a reinterpretation of the current static pre/post scans.

## Current Code Support

The cohort quantification layer already has first-pass support for lesion and
side-aware metrics:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  output/all_mice \
  -o derivatives/flash_v1_cohort \
  --brain-mask-dir derivatives/brain_seg/manual \
  --brain-mask-pattern "{case_id}_pre_manual_mask_done.nii.gz" \
  --brain-mask-pattern "{case_id}_pre_manual_mask.nii.gz" \
  --lesion-mask-dir derivatives/lesion_seg/t2_to_t1 \
  --lesion-mask-pattern "{case_id}_lesion_mask_in_t1_pre.nii.gz" \
  --ipsilateral-side left \
  --reference-mode mirrored_roi
```

The same inputs can also be supplied through `--roi-manifest` columns:

```csv
case_id,include,brain_mask,lesion_mask,ipsilateral_side,notes
C25S1_D1,1,derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz,derivatives/lesion_seg/t2_to_t1/C25S1_D1_lesion_mask_in_t1_pre.nii.gz,left,
```

Existing outputs include lesion volume, lesion CE summary statistics,
contralateral-reference corrected CE statistics, enhancing volume, percent ROI
enhancing, integrated leakage burden, ipsi/contra ratio, and D7-D1 deltas.

Current limitation: the cohort CSV currently emits one primary ROI row per
session. When a lesion mask is supplied, that primary ROI is the lesion. A later
implementation should add a separate long-format ROI table with explicit rows
for whole brain, ipsilateral hemisphere, contralateral hemisphere, lesion,
mirrored contralateral lesion, outside-lesion brain, ipsilateral outside-lesion,
contralateral outside-lesion, and peri-lesional rim.

Another planned extension is a `z_leakage` map:

```text
delta = post_norm - pre_norm
z_leakage = (delta - mean(delta_reference)) / SD(delta_reference)
```

The reference should be a fixed, auditable contralateral region such as mirrored
contralateral lesion ROI, contralateral hemisphere, or another predeclared
control mask. `z_leakage` is useful for automated thresholding because it
expresses enhancement relative to each animal's own background variation.

## Required Spaces

Keep spaces explicit and do not mix masks without registration:

```text
T2 native/model space
  high-resolution T2w image
  T2 lesion-model output mask

T1 pre-Gd native coronal space
  pre_coronal.nii.gz
  post_coronal.nii.gz registered into pre space
  final brain mask
  T2 lesion mask transformed into pre space with nearest-neighbor interpolation
  mirrored contralateral lesion ROI
  final enhancement map
```

All final BBB quantification should happen in the T1 pre-Gd space.

Registration target decision: keep native pre-Gd T1 FLASH as the main analysis
space. Register post-Gd T1 to pre-Gd T1, and register T2w to pre-Gd T1. This
matches the current brain-mask workflow and avoids using the post-Gd leakage
signal as the space where masks are defined.

## Metadata To Track

Record these fields in the final manifest whenever they are available:

```text
Gd agent
Gd dose
injection route
injection time
post-Gd acquisition start time
post-Gd acquisition duration
TR / TE / flip angle
field strength
coil
anesthesia
body temperature
stroke side
stroke model
reperfusion status, if available
```

The post-Gd delay is especially important for static enhancement. A session
acquired 5 minutes after injection is not directly comparable to one acquired
20 minutes after injection unless timing is modeled or stratified.

## Staged Implementation

### 1. Freeze T2 Lesion Model Outputs

For each included session, save:

```text
derivatives/lesion_seg/t2_native/{case_id}/t2w.nii.gz
derivatives/lesion_seg/t2_native/{case_id}/{case_id}_lesion_mask_t2_native.nii.gz
derivatives/lesion_seg/t2_native/{case_id}/{case_id}_lesion_qc.png
```

The lesion mask must be binary and on the exact same grid as the T2w image used
for inference.

### 2. Convert, Pair, And Interpret T2w Scans

Add a T2 conversion/pairing stage before relying on lesion masks:

- identify the high-resolution T2w scan for each T1 FLASH session
- preserve scan ID, source path, voxel sizes, orientation, and acquisition notes
- write a manifest that links `case_id`, T1 pre image, T1 post image, T2 image,
  T2 lesion mask, brain mask, ipsilateral side, and inclusion status

Initial manifest target:

```text
derivatives/manifests/t1_t2_lesion_manifest.csv
```

Suggested columns:

```csv
case_id,animal_id,timepoint,include,t1_pre,t1_post,t1_brain_mask,t2w,t2_lesion_mask,t2_to_t1_transform,lesion_mask_in_t1_pre,ipsilateral_side,gd_agent,gd_dose,gd_injection_time,post_gd_delay_min,qc_status,notes
```

Interpret D1 and D7 T2w lesion masks differently:

- D1 T2w lesion volume is strongly influenced by acute/subacute edema and
  swelling.
- D7 T2w lesion volume reflects later lesion evolution and may include tissue
  loss, residual edema, cystic change, gliosis, or atrophy-related effects.
- Do not treat D1 and D7 T2w lesion volume as identical biological quantities
  without this caveat in the report.

For D1, compute both raw T2 lesion volume and an edema-corrected lesion volume
when reliable ipsilateral and contralateral hemisphere masks exist:

```text
edema_corrected_lesion_volume =
  raw_lesion_volume * contralateral_hemisphere_volume / ipsilateral_hemisphere_volume
```

This simple correction should be marked as hemisphere-volume corrected and
kept separate from more advanced atlas/deformation-based correction.

### 3. Register T2w To T1 Pre-Gd

Register the T2w image to the matching `pre_coronal.nii.gz`. Start simple and
inspect failures:

- rigid or affine registration, depending on acquisition geometry
- use mutual information for cross-contrast registration
- constrain or initialize with brain/foreground masks when available
- save the transform and a QC montage
- transform the lesion mask with nearest-neighbor interpolation only

Planned outputs:

```text
derivatives/lesion_seg/t2_to_t1/{case_id}/{case_id}_t2_to_t1_pre.tfm
derivatives/lesion_seg/t2_to_t1/{case_id}/{case_id}_t2_in_t1_pre.nii.gz
derivatives/lesion_seg/t2_to_t1/{case_id}/{case_id}_lesion_mask_in_t1_pre.nii.gz
derivatives/lesion_seg/t2_to_t1/{case_id}/{case_id}_t2_to_t1_qc.png
```

The first implementation should be a standalone registration/QC script, for
example:

```text
scripts/qc/qc_t2_to_t1_registration.py
```

or a reusable registration script plus QC output:

```text
scripts/registration/register_t2_to_t1.py
```

### 4. QC Lesion Transfer In T1 Space

Before quantification, inspect:

- T2w overlaid on T1 pre
- T2 lesion mask overlaid on T1 pre
- lesion mask clipped by the T1 brain mask
- mirrored contralateral lesion ROI
- whether the lesion side agrees with the manifest side

The lesion mask should not extend outside the final T1 brain mask for final
metrics. Keep both the unclipped transferred mask and the clipped analysis ROI
auditable.

Add explicit exclusion masks when they can be defined reliably:

```text
ventricles / CSF
choroid plexus
large vessels
meninges
sagittal sinus
hemorrhage, if visible
motion or ghosting artifacts
injection or wraparound artifacts
```

These regions can enhance for reasons other than parenchymal stroke-related BBB
leakage and can inflate lesion, hemisphere, or whole-brain metrics.

### 5. Quantify T1 Enhancement In Lesion And Control ROIs

After post-Gd T1 is registered to pre-Gd T1 and the T2 lesion mask is in pre
space, quantify:

- whole brain
- ipsilateral hemisphere
- contralateral hemisphere
- lesion ROI
- mirrored contralateral lesion ROI
- peri-lesional rim, for example lesion dilated by 300-500 micrometers minus
  lesion
- outside-lesion brain
- ipsilateral outside-lesion brain
- contralateral outside-lesion brain

Primary candidate metrics:

- mean CE %
- median CE %
- 95th percentile CE %
- contralateral-reference corrected CE %
- enhancing volume
- percent lesion or ROI enhancing
- integrated leakage burden
- lesion/mirrored contralateral enhancement ratio
- ipsilateral/contralateral hemisphere ratio
- D7-D1 change for paired animals
- mean z-leakage
- enhancing volume based on a fixed z-leakage threshold such as `z > 3`
- fraction of T2 lesion enhancing
- fraction of enhancement outside the T2 lesion
- spatial overlap between T2 lesion and enhancement mask

Threshold metrics remain provisional until the threshold strategy is validated.
Prefer contralateral-reference thresholds first, such as mirrored ROI p95 or
contralateral hemisphere mean plus 2 SD. For `z_leakage`, use one fixed
thresholding rule across the cohort and require a minimum connected-component
size to suppress isolated noise voxels.

## Longitudinal D1 To D7 Metrics

After a D7-to-D1 within-animal registration is available and QC-approved, add
longitudinal spatial metrics:

```text
delta_t2_lesion_volume = D7 lesion volume - D1 lesion volume
delta_bbb_enhancing_volume = D7 enhancing volume - D1 enhancing volume
delta_bbb_leakage_burden = D7 leakage burden - D1 leakage burden

persistent_leakage = D1 enhancing voxels intersect D7 enhancing voxels
resolved_leakage = D1 enhancing voxels minus D7 enhancing voxels
new_or_delayed_leakage = D7 enhancing voxels minus D1 enhancing voxels
```

Also classify voxels into four compartments:

```text
T2 lesion + gad enhancement
T2 lesion only
gad enhancement only
neither T2 lesion nor gad enhancement
```

This compartment table is useful biologically because leakage outside the T2
lesion may indicate peri-infarct BBB disruption, while T2 lesion without strong
enhancement may indicate infarcted or edematous tissue without strong static
contrast accumulation at that time point.

Candidate primary endpoint for this dataset:

```text
D1 BBB leakage burden in T2 lesion plus peri-lesional rim,
normalized or thresholded against a contralateral reference
```

Candidate secondary endpoints:

```text
D1 raw and edema-corrected T2 lesion volume
D1 fraction of T2 lesion enhancing
D1 peri-lesional leakage volume or burden
D7 persistent leakage burden
D7 new or delayed leakage outside the D1 lesion
D1 to D7 change in leakage burden
D1 to D7 change in T2 lesion volume
```

## Brain Segmentation Requirement

A T2w lesion model does not remove the need for a T1 brain mask.

The brain mask is still required to:

- define the valid tissue support for T1 pre/post normalization
- exclude skull, scalp, glands, eyes, and background from enhancement metrics
- clip transferred T2 lesion masks to brain tissue
- define hemispheres and midline for ipsilateral/contralateral metrics
- define whole-brain and outside-lesion regions
- support QC and inclusion/exclusion decisions

The current priority remains finalizing reliable T1 pre-Gd brain masks. A
brain-mask model is not strictly required if all cases can be manually corrected
and QC-approved, but some reliable brain-mask source is required. If manual
correction of every case is too slow, continue the planned nnU-Net active
learning path for pre-Gd T1 brain masks.

## Near-Term Development Tasks

1. Lock the T2 lesion-model output format and case naming.
2. Add or finish T2w conversion into a consistent NIfTI space for each session.
3. Build `t1_t2_lesion_manifest.csv` with T1, T2, lesion-mask, brain-mask, side,
   inclusion, and QC fields.
4. Implement T2-to-T1 registration and QC montage generation.
5. Transform T2 lesion masks into T1 pre space with nearest-neighbor
   interpolation and clip analysis copies to the T1 brain mask.
6. Extend cohort quantification to write a long-format ROI table with
   inside-lesion, peri-lesion, outside-lesion, ipsilateral, contralateral, and
   mirrored-ROI rows.
7. Add `delta`, `percent_enhancement`, and `z_leakage` maps to the cohort
   output, with fixed threshold rules and minimum connected-component filtering.
8. Add peri-lesional rim and exclusion-mask support.
9. Add D7-to-D1 within-animal registration and persistent/resolved/new leakage
   metrics after registration QC works.
10. Run sensitivity checks for lesion-mask transfer and brain-mask erosion before
   treating lesion-specific BBB metrics as final.

## QC Report Target

Each included animal should eventually receive a compact QC report showing:

- T2w D1 and D7 with lesion masks
- T1 pre/post registration overlay for each time point
- T2-to-T1 registration overlay
- brain mask overlay
- transferred lesion mask in T1 pre space
- mirrored contralateral lesion ROI
- peri-lesional rim
- delta, percent-enhancement, and z-leakage maps
- enhancement threshold mask
- D1-vs-D7 registration overlay when longitudinal metrics are computed
- enhancement histograms for ROI and reference regions
- summary table of metrics, QC pass/review/fail flags, and notes

## Later Statistics

After treatment/group labels are available and QC exclusions are locked, use a
longitudinal model rather than unrelated time-point tests where possible:

```text
metric ~ group * timepoint + lesion_volume + (1 | mouse)
```

Keep lesion volume or edema-corrected lesion volume as a candidate covariate
because larger infarcts can produce more leakage simply by involving more
injured tissue.

## Method References

- Ku et al. 2018, `Assessment of blood brain barrier leakage with gadolinium-enhanced MRI`, Methods in Molecular Biology:
  `https://www.mdc-berlin.de/research/publications/assessment-blood-brain-barrier-leakage-gadolinium-enhanced-mri`
- Chassidim et al. 2013, `Quantitative imaging assessment of blood-brain barrier permeability in humans`, Fluids and Barriers of the CNS:
  `https://link.springer.com/article/10.1186/2045-8118-10-9`
- Heye et al. 2016, `Tracer kinetic modelling for DCE-MRI quantification of subtle blood-brain barrier permeability`:
  `https://eprints.whiterose.ac.uk/id/eprint/106413/1/Tracer%20kinetic%20modelling%20for%20DCE-MRI%20quantification%20of%20subtle%20blood-brain%20barrier%20permeability.pdf`
- QIBA DCE-MRI Quantification Profile, public comment profile:
  `https://qibawiki.rsna.org/images/1/1f/QIBA_DCE-MRI_Profile-Stage_1-Public_Comment.pdf`
- Koch et al. 2019, `Atlas registration for edema-corrected MRI lesion volume in mouse stroke models`:
  `https://journals.sagepub.com/doi/10.1177/0271678X17726635`
