APP := apps/jobhunt
RUN := uv run --locked --directory $(APP)

.PHONY: install lint format typecheck test schema schema-check check

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

# JSON Schemas in schemas/ are generated from the models; paths are relative to $(APP).
schema:
	$(RUN) python -m jobhunt.tools.export_schema --out ../../schemas

schema-check:
	$(RUN) python -m jobhunt.tools.export_schema --out ../../schemas --check

check: lint typecheck test schema-check
