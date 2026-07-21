# Tests

Run the suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The tests cover scientific geometry and gates, the RS2 notebook build, frozen
schema-v1 migration compatibility, canonical schema-v6 studies, MRI import/conversion,
T2 release/inference persistence, and connected offscreen desktop behavior. They do not
replace visual anatomical QC or a real raw-data-to-approved-result validation set.

The next tests should cover T2 review transitions, corrected-mask validation, artifact
supersession, approved-result dependency invalidation, CSV gating, and reopening.
Use `pytest-qt` for navigation and interaction tests; keep scientific geometry and
measurement assertions in backend tests rather than duplicating them in UI tests.

New scientific behavior requires both focused synthetic tests and, where anatomy or
registration matters, a small frozen validation dataset with explicit human review.
