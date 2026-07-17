# Script entry points

Scripts are grouped by pipeline stage. Reusable logic belongs in `src/lys_bbb/`;
scripts should remain thin command-line adapters unless they integrate an external tool.

| Folder | Purpose |
|---|---|
| `inventory/` | Inspect raw Bruker sessions and assign scan roles |
| `conversion/` | Convert selected T1 FLASH scans to native coronal NIfTI |
| `brain_extraction/` | Prepare Colab benchmarks and run model-specific adapters |
| `masks/` | Review, post-process, validate, and prepare approved masks |
| `qc/` | Build registration, mask, study, analysis, and readiness reports |
| `quantification/` | Run provisional pair or cohort enhancement analysis |

`brain_extraction/mbe/` is an adapter for MouseBrainExtractor, not the project-wide
brain-extraction API. New benchmarked models should receive their own adapter and must
write the common output contract described in `docs/brain_extraction.md`.

Generated images, masks, tables, and model weights do not belong under `scripts/`.
