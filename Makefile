UV ?= uv

.PHONY: format lint test

format:
	$(UV) run --no-sync ruff format .

lint:
	$(UV) run --no-sync ruff format --check .
	$(UV) run --no-sync ruff check .

test:
	@true
