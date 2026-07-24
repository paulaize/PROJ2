.PHONY: lint test

lint:
	conda run -n lys-bbb ruff check src tests

test:
	conda run -n lys-bbb env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q
