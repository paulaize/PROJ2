# Repo Structure

This repo supports a staged V1 pipeline for the current static pre/post T1 FLASH mouse BBB leakage dataset. The global target is a folder-plus-optional-manifest pipeline that produces a full experiment-level BBB leakage report across all mice, including D1/D7 comparisons, QC paths, and auditable processing metadata. The current code can generate provisional pair and cohort quantification outputs; the immediate V1 target is to make those outputs trustworthy by locking corrected brain masks, post-to-pre registration QC, side/ROI metadata, threshold choices, and inclusion/exclusion decisions.

Planned/current V1 layout:

```text
AGENT.md
README.md
docs/brain_segmentation.md       # current brain-mask method decision record
docs/nnunet_active_learning.md   # corrected-mask/nnU-Net workflow
docs/t2_lesion_t1_integration.md # planned T2w lesion-to-T1 FLASH ROI linkage
buker_nifty_flip.py              # compatibility wrapper for older conversion commands
configs/                         # dataset and pipeline configuration
scripts/conversion/              # Bruker-to-NIfTI conversion CLIs
scripts/inventory/               # raw-session inventory CLIs
scripts/quantification/          # pair and cohort quantification CLIs
scripts/qc/                      # visual QC and benchmarking tools
scripts/qc/build_analysis_manifest.py
scripts/qc/build_project_status.py
scripts/masks/                   # mask editing/opening helpers
scripts/masks/build_manual_mask_workflow.py
scripts/masks/open_manual_mask_editor.py
scripts/masks/prepare_nnunet_brain_extraction.py
scripts/cloud_mbe/               # self-contained cloud MouseBrainExtractor helpers
src/lys_bbb/                     # reusable pipeline modules
src/lys_bbb/analysis_manifest.py # QC-gated quantification manifest builder
src/lys_bbb/conversion.py        # Bruker T1 FLASH conversion implementation
src/lys_bbb/mask_workflow.py     # manual-mask dashboard and nnU-Net prep helpers
src/lys_bbb/pipeline_status.py   # V1 readiness summary/report builder
deprecated/sherm/                # retired SHERM-inspired mask code
reports/inventory/               # generated scan inventories, ignored by git
reports/qc/                      # compact QC summaries, dashboards, and worklists
derivatives/                     # generated processing outputs, ignored by git
output/                          # generated conversion/Fiji-viewing outputs, ignored by git
tests/                           # focused tests as modules are added
```

Raw Bruker data remains outside the repo:

```text
/Users/paul-andreaslaize/Desktop/LYS/Thrombin_03_ESR3P
```

Do not copy raw MRI data into this repository. Use inventories and derivatives to document processing.

Current generated outputs may include:

```text
output/fiji_d1_d7_two_animals/
derivatives/flash_v1_minimal/
derivatives/flash_v1_debug/
reports/inventory/
```

These are reproducible from the scripts and may be deleted when storage is needed. The source of truth is the raw Bruker dataset plus the commands documented in `README.md`.

Output policy:

- Keep lightweight products by default: mask, main enhancement map, transform, QC PNGs, metadata, and summaries.
- Active quantification requires corrected or predicted pre-space brain masks. Cloud MouseBrainExtractor outputs are editable pre-labels, not final masks.
- Corrected brain masks should be made in native pre-contrast T1 FLASH space; final quantification should reuse that pre-space mask for the registered post image only after registration QC passes.
- Future T2w lesion integration should stay separate from T1 pre/post enhancement: T2w images define lesion ROIs, T1 pre/post images measure BBB leakage, and mirrored contralateral ROIs provide internal controls.
- Treat `docs/brain_segmentation.md`, `docs/nnunet_active_learning.md`, and `docs/t2_lesion_t1_integration.md` as the current sources of truth for mask status, validation, method alternatives, and lesion-to-enhancement linkage.
- Refresh `reports/qc/manual_mask_worklist.csv`,
  `reports/qc/manual_mask_dashboard.html`, and
  `derivatives/brain_seg/nnunet_manifest.csv` from
  `scripts/masks/build_manual_mask_workflow.py` after manual-mask edits.
- Refresh `derivatives/manifests/analysis_manifest.csv` from
  `scripts/qc/build_analysis_manifest.py` after QC updates. This is the
  intended handoff into manifest-gated cohort quantification.
- Refresh `reports/qc/project_status.md` from
  `scripts/qc/build_project_status.py` to summarize current blockers, mask
  readiness, registration readiness, nnU-Net readiness, and next commands.
- Write large debug NIfTI intermediates only when explicitly requested.
- Keep requested debug products in a clear debug folder such as `derivatives/flash_v1_debug/`.
- Generate Fiji display NIfTIs only when explicitly requested; they are visualization-only.
- New conversion commands should use `scripts/conversion/convert_bruker_t1_flash.py`.
  The root `buker_nifty_flip.py` is only a compatibility wrapper.
- The conversion CLI still writes Fiji display files by default, so normal
  quantitative conversion commands should pass `--no-fiji-display` until the
  CLI default is changed.

Final V1 should organize results by animal ID and time point where practical:

```text
derivatives/flash_v1_minimal/C25S1/D1/
derivatives/flash_v1_minimal/C25S1/D7/
```

The current batch quantification CSV is an initial engineering/QC product, not the locked final statistics product. The final downstream statistics product should be one combined CSV/report for all mice and sessions, including D1/D7 per-animal comparisons where both time points are present, after the final converted images, corrected masks, lesion/ROI masks, side assignments, and QC inclusion decisions are locked. Treatment labels are not expected because the dataset is blinded. Later T2w lesion-volume products may be linked into the report after reliable T1 BBB leakage quantification exists; lesion segmentation should remain a separate stage from brain masking and BBB enhancement quantification.
