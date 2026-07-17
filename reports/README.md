# Generated reports

Generated inventory, QC, review, validation, and readiness reports live here and are
ignored except for this file.

```text
inventory/   raw Bruker inventory tables
qc/          compact registration/mask review and project-readiness products
```

Reports can be older than the checked-out code because ignored files are shared across
branches. Preserve editable review decisions before rebuilding a report, and record the
code/model revision for any result used beyond development.

Large NIfTI files belong in `derivatives/`, not `reports/`.
