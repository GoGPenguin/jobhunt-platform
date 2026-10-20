APP := apps/jobhunt
RUN := uv run --locked --directory $(APP)
SECRETS := $(HOME)/.config/jobhunt/secrets.env
COMPOSE := docker compose --env-file $(SECRETS)
TEST_COMPOSE := docker compose -p jobhunt-test -f docker-compose.yml -f docker-compose.test.yml

.PHONY: install lint format typecheck test golden schema schema-check check collect-email digest install-timer uninstall-timer db-up db-down db-migrate test-db

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

# Read the Gmail alert label (only new mail) and store jobs; prints new/updated jobs as JSON
# lines. SINCE=3d by default; EML="file.eml ..." reads local files instead of IMAP (paths
# relative to apps/jobhunt); DRY_RUN=1 prints everything and needs no database.
collect-email:
	$(RUN) jobhunt collect email --since $(or $(SINCE),3d) $(if $(EML),--eml $(EML)) $(if $(DRY_RUN),--dry-run)

# Postgres for the Docker Compose phase (spec 04). db-up creates missing DB passwords first.
db-up:
	$(RUN) jobhunt db init-secrets
	$(COMPOSE) up -d --wait db

db-down:
	$(COMPOSE) down

db-migrate:
	$(RUN) jobhunt db bootstrap
	$(RUN) jobhunt db migrate

# Store tests against a throwaway Postgres (port 55432, in memory), removed afterwards.
test-db:
	JOBHUNT_DB_ADMIN_PASSWORD=jobhunt-test $(TEST_COMPOSE) up -d --wait db
	JOBHUNT_TEST_DATABASE_ADMIN_URL=postgresql://postgres:jobhunt-test@127.0.0.1:55432/postgres \
		$(RUN) pytest tests/store; status=$$?; \
		JOBHUNT_DB_ADMIN_PASSWORD=jobhunt-test $(TEST_COMPOSE) down -v; exit $$status

# Send the Telegram digest of postings not sent yet (spec 05).
digest:
	$(RUN) jobhunt digest send

# Daily run on this machine (systemd user timer): collect, then send the digest, at DIGEST_TIME
# (default 12:00) in preferences.yaml's timezone. Removed when collector-runtime takes over.
install-timer:
	$(RUN) jobhunt timer install --uv "$$(command -v uv)" --repo "$(CURDIR)" --at $(or $(DIGEST_TIME),12:00)
	systemctl --user daemon-reload
	systemctl --user enable --now jobhunt-daily.timer
	systemctl --user list-timers jobhunt-daily.timer --no-pager

uninstall-timer:
	-systemctl --user disable --now jobhunt-daily.timer
	$(RUN) jobhunt timer remove
	systemctl --user daemon-reload
