# Script entry points

Scripts are grouped by pipeline stage. Reusable logic belongs in `src/lys_bbb/`;
scripts should remain thin command-line adapters unless they integrate an external tool.

The T2 review and approval slice is complete. The current application milestone is T1
brain-mask generation and review. Scripts below remain thin research/reproducibility
adapters rather than parallel applications; the local production-facing T1 commands are
the package entry points `lys-bbb-t1-mask-setup` and `lys-bbb-t1-mask`.

| Folder | Purpose |
|---|---|
| `inventory/` | Inspect raw Bruker sessions and assign scan roles |
| `conversion/` | Convert selected T1 FLASH scans to native coronal NIfTI |
| `brain_extraction/` | Prepare, run, and review the selected RS2/M-seam workflow |
| `masks/` | Review, post-process, validate, and prepare approved masks |
| `qc/` | Build registration, mask, study, analysis, and readiness reports |
| `quantification/` | Run provisional pair or cohort enhancement analysis |

The obsolete standalone MouseBrainExtractor adapter was removed after RS2/M-seam was
selected. Frozen comparison notebooks remain as scientific provenance, but they are not
application entry points. The active workflow is described in
`docs/brain_extraction.md`.

Generated images, masks, tables, and model weights do not belong under `scripts/`.
