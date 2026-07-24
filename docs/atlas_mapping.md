# Major-region atlas mapping

## Status and scientific boundary

The walking software slice is implemented and synthetic tests pass. It is
`PROVISIONAL`: no real subject has been run and the proposed major-region collapse has
not been scientifically approved. Fine Allen nuclei, cortical layers, thin tracts, and
small subregions are prohibited from result tables.

The only supported graph is:

```text
AIDAmri MRI template / Allen labels → native pre-Gd T1 → original native T2
                                                        + native lesion (unchanged)
                                                        → major-region overlap
```

Post-Gd T1 and post→pre registration are not dependencies. Waxholm and direct
pre-T1→Allen-autofluorescence registration are outside this MVP.

## Repository and input audit (2026-07-22)

- The 34 converted pre-T1 volumes were inspected independently. All are
  96×185×256, approximately 0.15×0.07784×0.078125 mm, `RSA`, finite and nonsingular,
  with left-handed affine determinant near −0.000912 mm³. All have `qform_code=0` and
  `sform_code=2`; the missing qform is recorded rather than described as agreement.
  Their physical bounds vary, so filenames or a repeated lesion voxel count cannot
  establish T1/T2 identity.
- The supplied AIDAmri template, annotation, and normalized lookup match SHA-256
  `f1bc07…b65a`, `9b7951…fec4`, and `8d62af…9279`. Template/annotation geometry is
  228×160×264 at 0.05 mm, `LIP`, with agreeing coded qform/sform. The annotation's 98
  nonzero IDs exactly match the 98 lookup rows.
- The old experimental partial-T2 support mask is a binary 256×256×18 mask at
  0.07×0.07×0.5 mm, but it is not an approved application artifact and is not imported
  automatically.
- No canonical study record proves which LYS_PROJ2 subject/session corresponds to the
  experimental T2. A real run is blocked until Paul provides that identity, the exact
  approved pre-T1 artifact, and a reviewed T2 support mask.

## Atlas release and major-region proposal

The app registers the AIDAmri resources as an immutable external release at revision
`3408ed46ea097f9fff5adbcdd7da6da6102f283a`. It rechecks every external resource hash
before registration or mapping. Atlas volumes are not committed. A separate managed,
checksummed annotation-support mask is used only as the atlas-template mask.

`config/atlas/major_regions_v1.csv` is an explicit 98-row proposal. It collapses source
labels into 14 broad anatomical classes per hemisphere (28 IDs): neocortex, olfactory
system, hippocampal formation, striatum, pallidum, septal/amygdalar complex, thalamus,
hypothalamus, midbrain, pons, medulla, cerebellum, major white-matter systems, and
claustrum/cortical subplate. Every row is marked `PROPOSED`. These choices are not
silently treated as scientific truth: the Reviews queue blocks composite generation
and regional results until Paul approves the exact scheme checksum.

## Registration methods

Native macOS-arm64 ANTs 2.6.5 is installed in the existing `lys-bbb` environment and
pinned in `environment.yml`. The installed `antsRegistration`, `antsApplyTransforms`,
`N4BiasFieldCorrection`, and `CreateJacobianDeterminantImage` interfaces were inspected
before commands were implemented. Commands use subprocess argument lists with
`shell=False` and record executable paths, version, full arguments, stdout/stderr,
return code, runtime, and source/output hashes.

Atlas→pre-T1 validates native geometry and the exact approved mask, crops processed
copies without changing physical coordinates, runs N4 only on the cropped registration
copy, then creates separate rigid and rigid→affine candidates. Both use Mattes mutual
information, a recorded provisional 4×2×1 pyramid, and physical 0.4×0.2×0 mm smoothing.
Each candidate retains intensity QC, a propagated atlas-support mask, support metrics,
scale, shear, determinant, and exact provenance. Optimizer success is never approval.
SyN is disabled until affine landmark review establishes a need.

Pre-T1→T2 uses the original T2 as fixed, original pre-T1 as moving, mutual information,
and rigid transform only. It requires the approved T1 mask and a separately reviewed T2
registration-support mask. Optional lesion exclusion is an explicit checksum-bound
method dependency. QC contains T2 intensity, transformed-T1 edges, brain/support
boundaries, lesion outline, adjacent-slice support measurements, orientation, and every
original T2 slice.

## Transform composition proof

ANTs transform order was checked with the installed 2.6.5 executable, a 27-voxel label
cube, and non-commuting translation/rotation transforms. The two command orders moved
the cube centroid to different locations (`[13,19,12]` versus `[9,15,12]`). For image
resampling, the verified direct composition is:

```text
antsApplyTransforms ... -t pre_to_t2.mat -t atlas_to_pre.mat
```

This samples atlas labels by the T2→pre→atlas output-point mapping. Synthetic tests use
a non-commuting affine/translation landmark calculation and assert this exact command
order. Labels in T2 are created directly from major labels on the original atlas grid;
the pre-T1 label image is a separate QC artifact and is never the T2 input.

## Result and state contract

Regional calculation requires a valid atlas release, approved major-region scheme,
approved atlas→pre candidate, approved pre→T2 rigid artifact, approved native-T2
composite, and current approved lesion. It reports native lesion count/volume, overlap
and lesion fraction per approved major region, mapped/unmapped and outside-support
lesion voxels, acquired-FOV absence separately from acquired zero overlap, boundary-near
voxels, and physical ±0.5 mm anterior/posterior stress results. The stress test is not a
confidence interval; orientation is checked against the native affine.

Schema-v11 stores feature-specific immutable releases, scheme reviews, support masks,
methods, jobs, candidate artifacts, exact hash-bound reviews, composites, and results.
Input/mask/atlas/scheme/lesion changes outdate only their declared downstream branch.
No file is overwritten or silently recomputed, and restart reconstruction is tested.

## Remaining real-case gate

Do not run or claim a real atlas result until these are supplied explicitly:

```text
new_unseen_mouse_001 corresponds to LYS_PROJ2 subject: ______
timepoint/session: ______
approved pre-T1 artifact: ______
reviewed T2 registration-support mask: ______
```

The first app test should run rigid and affine only, review landmarks and all original
T2 slices, approve exact artifacts, generate the direct composite, inspect it, and then
calculate the major-region sensitivity result. Parameters must not be selected based on
which registration gives a preferred lesion-region answer.
