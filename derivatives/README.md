# Derivatives

Generated pipeline outputs go here during local development.

This folder is ignored by git because MRI derivatives can be large and should be regenerated from raw Bruker data plus explicit configuration.

V1 output policy:

- Keep default outputs lightweight.
- Store compact pair outputs under `derivatives/flash_v1_minimal/` or the
  chosen quantification output folder.
- Store initial cohort outputs under the chosen `derivatives/flash_v1_cohort/`
  style folder. These cohort tables are engineering/QC products until final
  masks and inclusion decisions are locked.
- Store requested debug/intermediate outputs under a clear debug folder such as `derivatives/flash_v1_debug/`.
- Do not mix visualization-only Fiji/slab outputs with quantitative derivatives.

The most important V1 derivatives are trustworthy corrected brain masks on
coronal slices 50-170. Quantification should not be trusted when mask QC or
post-to-pre registration QC fails.

Final V1 should produce one locked combined CSV/report for all included
mice/sessions, while keeping per-session artifacts compact and reproducible.
