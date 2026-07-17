# Generated derivatives

This directory is ignored except for this file. It contains working predictions, masks,
transforms, manifests, maps, and tables produced from raw data and explicit code/model
versions.

Preserve user-created manual masks and review decisions. Other derivatives should be
reproducible, but a branch switch does not regenerate or remove them.

Recommended organization for new work:

```text
brain_extraction/   automatic, editable, reviewed, and benchmark masks
registration/       transforms, registered images, and QC
manifests/          generated internal handoffs
quantification/     enhancement maps and cohort outputs
```

Existing `brain_seg/` and `flash_v1_*` folders are transitional historical outputs. Do
not bulk-delete them until manual masks and review state have been migrated and checked.

Whole-brain quantification uses the full approved mask. Slices 50–170 are only the
standard QC display range.
