# Tests

Run the suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The tests cover scientific geometry and gates, the RS2 notebook build, frozen
schema-v1 migration compatibility, canonical schema-v7 studies, MRI import/conversion,
T2 release/inference persistence, immutable review, approved results/CSV, and connected
offscreen desktop behavior. They do not
replace visual anatomical QC or a real raw-data-to-approved-result validation set.

`test_t2_review.py` covers T2 review transitions, corrected-mask validation, artifact
supersession, approved-result dependency invalidation, CSV gating, reopening, and the
schema-v6 draft migration.
Use `pytest-qt` for navigation and interaction tests; keep scientific geometry and
measurement assertions in backend tests rather than duplicating them in UI tests.

New scientific behavior requires both focused synthetic tests and, where anatomy or
registration matters, a small frozen validation dataset with explicit human review.
