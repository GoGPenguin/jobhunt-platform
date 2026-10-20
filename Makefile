APP := apps/jobhunt
RUN := uv run --locked --directory $(APP)

.PHONY: install lint format typecheck test check

install:
	uv sync --locked --directory $(APP)

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

typecheck:
	$(RUN) mypy

test:
	$(RUN) pytest

check: lint typecheck test
