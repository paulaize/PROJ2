# Current project state

Last audited: 2026-07-19. This file records operational facts, not future design.

## Readiness summary

The T1 backend works on synthetic tests and development cases, but the cohort is not
ready for biological interpretation. The final analysis manifest currently includes
zero cases because reviewed T1 brain masks are unavailable.

| Area | Current state |
|---|---|
| Raw inventory | 36 sessions, 285 scans, no inventory failures |
| Intended T1 cases | 35 case IDs |
| Converted T1 pairs | 34 |
| Rigid registration outputs | 34; numeric similarity improved in all cases |
| Explicit registration approvals | 0 |
| MouseBrainExtractor pre-labels | 8 |
| Explicitly approved T1 brain masks | 0 |
| Final analysis cases | 0 |
| Frozen Colab benchmark inputs | 10 T1 images packaged; primary GPU run completed successfully |
| Colab benchmark implementation | Three primary models, two mismatched controls, and a separate RS2 correction experiment |
| Brain-extraction decision | RS2-Net is the visual front-runner; corrected-mask selection and reviewed-reference scoring remain pending |
| Tests | Test suite passes; biological validation is separate |

The data contain static pre/post `T1_FLASH_3D_Glymphatic_Sag` scans. They do not
contain the multi-TR or dynamic acquisitions required for quantitative T1 mapping or
DCE permeability modeling.

## Dataset exceptions

- `C23S2_D1` failed T1 conversion because `brkraw` reported no valid ParaVision study.
- `C26S5_D1` has no usable T1 pre/post pair.
- `C23S3` has both `D1` and `D1_bis`; one must be selected before a unique D1-to-D7
  comparison is possible.
- Treatment groups remain blinded.

## Brain masks

Existing MouseBrainExtractor masks cover:

```text
C23S5_D1
C24S3_D1
C24S4_D1
C24S4_D7
C25S1_D1
C26S1_D1
C26S2_D1
C26S3_D7
```

Seven corresponding editable masks are unchanged copies of their pre-label. The
`C23S5_D1` mask was edited and marked with the legacy `_done` filename, but it still
lacks an explicit review approval. Filename state is therefore insufficient.

Current final gate:

```text
8  mask_needs_review
26 missing_brain_mask
1  missing_conversion
0  included
```

Largest-component cleanup and an eight-case testing-only cohort have run successfully.
Those masks and cohort outputs are engineering artifacts, not accepted labels or
biological results.

The first model-comparison cohort is frozen in
`config/brain_extraction_benchmark_10.txt`. Its 10-image local upload archive and exact
Colab notebook generated MBE isotropic, MBE anisotropic, and RS2-Net masks successfully
under one manifest/output contract. The downloaded masks have not yet been reviewed or
scored against accepted references, so no benchmark winner has been selected.

An optional companion notebook is ready for two explicitly mismatched diagnostic
controls: the CAMRI rodent T2/T2* U-Net and human-T1 deepbet. Its outputs use the same
manifest and native-grid mask contract, and the local review launcher can combine both
archives into one five-model ITK-SNAP comparison.

The two controls performed worse than RS2-Net on visual inspection. RS2-Net closely
follows the brain but recurrently includes a bright superior skull cap, most prominently
in high-contrast images where a dark M-shaped brain--skull separation is visible.
Increasing the RS2 probability threshold did not remove this false positive reliably.

`notebooks/brain_extraction_rs2_refinement_colab.ipynb` is now ready to rerun RS2 once
and compare three T1-guided postprocessors on the same ten images: a direct M-seam cut,
marker-controlled watershed, and random walker. It preserves raw RS2, writes every
candidate separately, generates interactive and durable QC, and packages all four masks
for the existing ITK-SNAP review launcher. The algorithms were exercised locally on the
downloaded ten-case results, but the exact notebook still awaits its first Colab run and
formal human selection.

## Registration and quantification

Rigid post-Gd-to-pre-Gd registration is available for each converted pair. Improved
cross-correlation is a useful automatic check, but not a human pass. The least similar
registered cases deserve early visual review.

Pair and cohort quantification currently implement:

- rigid registration;
- supplied pre-space mask enforcement;
- smooth bias correction;
- independent masked-median normalization;
- difference, ratio, and percent-enhancement maps;
- whole-mask, side-aware, lesion-hook, and D1-to-D7 summary metrics.

The bias-correction and normalization choices may suppress broad biological
enhancement. They remain provisional until the validation experiments in
`docs/enhancement_quantification.md` pass.

## Metadata

The editable study metadata table contains 35 rows. Group, lesion side, lesion-mask
path, explicit inclusion, and review fields are currently empty. These values cannot be
inferred safely from folder names.

## Branch history

The pre-cleanup branches are a single stack. Each branch is an intermediate checkpoint,
not a maintained product line:

```text
7248265 main
  └─ e560cc8 workflow-status-orchestration
       └─ 6e89e62 candidate mask validation
            └─ b27b16f brain-mask-model-integration
                 └─ 08af420 study-metadata-scaffold
                      └─ 8f58e8e mask-review-workflow
```

Their historical purposes were:

| Branch | Added capability |
|---|---|
| `main` | Initial inventory, conversion, registration, QC, and quantification |
| `workflow-status-orchestration` | Readiness report |
| `brain-mask-model-integration` | Candidate-mask validation and postprocessing |
| `study-metadata-scaffold` | Editable study metadata and analysis-manifest merge |
| `mask-review-workflow` | Explicit manual mask and registration review |

The latest tip contains all earlier changes. Cleanup should be consolidated into one
baseline rather than copied into every historical branch. Old feature branches can be
deleted after the consolidated tip is safely published on `main`.

## Generated-state warning

MRI outputs and reports are ignored by Git and shared by all local branches. Several
current dashboard/manifests were generated on 2026-07-08 or 2026-07-09, before the
2026-07-15 mask-review commit. They must be regenerated before being used as current
workflow evidence. Preserve manual masks and decisions while regenerating derived
reports.

## Definition of the next milestone

The next milestone is complete when the same representative cases have been run through
the selected open-weight models in Colab, outputs satisfy a common grid/provenance
contract, reviewed references exist for quantitative comparison, and a model-selection
report identifies failure modes and the preferred pre-label generator.
