APP := apps/jobhunt
RUN := uv run --locked --directory $(APP)

.PHONY: install lint format typecheck test golden schema schema-check check collect-email

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

# Rewrite parser golden files (tests/fixtures/sources/*/*/expected.json); review the diff.
golden:
	JOBHUNT_UPDATE_GOLDEN=1 $(RUN) pytest tests/sources/test_golden.py

# JSON Schemas in schemas/ are generated from the models; paths are relative to $(APP).
schema:
	$(RUN) python -m jobhunt.tools.export_schema --out ../../schemas

schema-check:
	$(RUN) python -m jobhunt.tools.export_schema --out ../../schemas --check

check: lint typecheck test schema-check

# Dry run: read the Gmail alert label and print jobs as JSON lines. SINCE=3d by default;
# EML="file.eml ..." reads local files instead of IMAP (paths relative to apps/jobhunt).
collect-email:
	$(RUN) jobhunt collect email --since $(or $(SINCE),3d) $(if $(EML),--eml $(EML))
