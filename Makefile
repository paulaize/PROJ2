.PHONY: lint test

lint:
	conda run -n lys-irm ruff check src scripts tests

test:
	conda run -n lys-irm env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q
