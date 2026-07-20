# Tests

Run the suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The tests cover synthetic parsing, gating, mask workflows, registration/quantification
logic, the Colab input packager, schema-v1 desktop project state, and connected offscreen
desktop navigation/filter/review behavior. They do not replace visual anatomical QC or
a real raw-data-to-report validation set.

As the MVP grows, add domain/service coverage for state transitions, approval gates,
artifact supersession, dependency invalidation, jobs, imports, and structured failures.
Use `pytest-qt` for navigation and interaction tests; keep scientific geometry and
measurement assertions in backend tests rather than duplicating them in UI tests.

New scientific behavior requires both focused synthetic tests and, where anatomy or
registration matters, a small frozen validation dataset with explicit human review.
