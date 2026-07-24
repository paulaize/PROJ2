# Tests

Run the suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The tests cover scientific geometry and gates, the RS2 notebook build, frozen
schema-v1 migration compatibility, canonical schema-v11 studies, MRI import/conversion,
T1 release/generation/correction/approval persistence, T1 registration and provisional
enhancement dependencies, T2 release/inference persistence, immutable approval, approved
results/CSV, and connected offscreen desktop behavior.
`test_atlas_mapping_vertical.py` and `test_atlas_mapping_persistence.py` cover the
checksummed atlas contract, major-label collapse, transform order, direct propagation,
native lesion immutability, all-slice QC, exact approvals, invalidation, and reopening.
They do not
replace visual anatomical QC or a real raw-data-to-approved-result validation set.

`test_t2_review.py` covers T2 review transitions, corrected-mask validation, artifact
supersession, approved-result dependency invalidation, CSV gating, reopening, and the
schema-v6 draft and schema-v7 review migration.
`test_t1_brain_mask_integration.py` covers the T1 release, successful run, immutable
draft, correction, approval, registration, provisional enhancement, dependency
invalidation, and reopen transitions.
Use `pytest-qt` for navigation and interaction tests; keep scientific geometry and
measurement assertions in backend tests rather than duplicating them in UI tests.

New scientific behavior requires both focused synthetic tests and, where anatomy or
registration matters, a small frozen validation dataset with explicit human review.
