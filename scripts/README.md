# Script entry points

Scripts are grouped by pipeline stage. Reusable logic belongs in `src/lys_bbb/`;
scripts should remain thin command-line adapters unless they integrate an external tool.

The current application milestone is T2 review and approval. Most scripts below are
retained, tested T1 research/reproducibility tools; they are not parallel production
applications and should not be expanded while the T2 vertical slice is active.

| Folder | Purpose |
|---|---|
| `inventory/` | Inspect raw Bruker sessions and assign scan roles |
| `conversion/` | Convert selected T1 FLASH scans to native coronal NIfTI |
| `brain_extraction/` | Prepare Colab benchmarks and run model-specific adapters |
| `masks/` | Review, post-process, validate, and prepare approved masks |
| `qc/` | Build registration, mask, study, analysis, and readiness reports |
| `quantification/` | Run provisional pair or cohort enhancement analysis |

`brain_extraction/mbe/` is a frozen comparison adapter for MouseBrainExtractor, not the
project-wide brain-extraction API. The active T1 pre-label experiment is the RS2
refinement described in `docs/brain_extraction.md`.

Generated images, masks, tables, and model weights do not belong under `scripts/`.
