# Tests

Run the suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

The tests cover synthetic parsing, gating, mask workflows, registration/quantification
logic, and the Colab input packager. They do not replace visual anatomical QC or a real
raw-data-to-report validation set.

New scientific behavior requires both focused synthetic tests and, where anatomy or
registration matters, a small frozen validation dataset with explicit human review.
