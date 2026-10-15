UV ?= uv
TEST_PATTERN ?= test*.py

.PHONY: format lint test

format:
	$(UV) run --no-sync ruff format .

lint:
	$(UV) run --no-sync ruff format --check .
	$(UV) run --no-sync ruff check .

test:
	$(UV) run --no-sync python -m unittest discover -s tests -p '$(TEST_PATTERN)' -v
