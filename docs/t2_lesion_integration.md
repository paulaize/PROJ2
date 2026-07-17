# External T2 lesion integration

## Ownership boundary

The T2w brain-lesion segmentation model is actively developed in a different
repository. This repository must not contain a duplicate training pipeline, private
weights, or an independent reimplementation of that model.

When the external model is released, this project will consume its predictions through
a stable file/provenance contract. Until then, T2 integration is planned and must not
block T1 brain-extraction validation.

The T2 lesion mask and T1 brain mask solve different problems:

```text
T1 brain mask       valid tissue support for T1 analysis
T2 lesion mask      stroke pathology defined independently of gadolinium
pre/post T1         enhancement measurement
```

## Required external release contract

For each case/session, the external repository should provide or make derivable:

- canonical mouse and session ID;
- native T2w input image identity;
- binary lesion mask on exactly the T2w image grid;
- image/mask shape, affine, spacing, orientation, and permitted labels;
- model name, release version, code revision, and weight checksum;
- preprocessing and postprocessing description;
- automatic QC and prediction status;
- optional human review decision and reviewed-mask checksum.

The final file naming can change, but these semantics must not.

## Responsibilities of this repository

After import, this project owns:

1. selecting and validating the matching T2w scan;
2. checking the external mask against its native T2w image;
3. registering T2w to native pre-Gd T1;
4. visually approving the multimodal registration;
5. transferring the lesion mask with nearest-neighbour interpolation;
6. clipping/reporting it against the approved T1 brain mask;
7. calculating lesion, perilesional, mirrored, hemisphere, and outside-lesion
   enhancement metrics in pre-Gd T1 space;
8. preserving the complete transform and model provenance chain.

```text
T2 lesion mask ── native T2
       │
       └─ nearest-neighbour through approved T2→T1 transform
                            ↓
                     native pre-Gd T1
                            ↓
             lesion-associated enhancement metrics
```

T2 lesion volume should also be retained in native T2 space. Do not repeatedly resample
the lesion or T1 intensity images.

## Planned metrics

Once the transform is validated, useful outputs include:

- native T2 lesion volume and morphology;
- mean, median, and 95th-percentile enhancement inside lesion;
- enhancing lesion volume and percent of lesion enhancing;
- integrated positive enhancement inside and outside lesion;
- lesion-to-mirrored-contralateral ratio;
- physical-distance perilesional rings;
- ipsilateral and contralateral outside-lesion brain;
- D1-to-D7 scalar changes.

Voxelwise persistent/resolved/new compartments require an additional validated D1-to-D7
registration. They must not be inferred from scalar deltas alone.

## Atlas relationship

Atlas mapping is optional and later. An MRI-compatible atlas may register through T2,
then have its labels composed into pre-Gd T1 space. Enhancement remains measured in
native pre-Gd T1. Start with larger regions supported by the MRI resolution; do not imply
fine anatomical precision from small atlas labels.

## Integration acceptance

The external link is complete only when a small held-out set demonstrates correct case
matching, grid validation, T2-to-T1 alignment, nearest-neighbour label transfer,
provenance capture, and review gating. A lesion prediction alone is not sufficient.
