# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## JobHunt Platform

Personal Kubernetes job-hunt system. Spec-driven: read `docs/spec/` before coding, starting with `docs/spec/00-overview.md` (goals, guardrails, architecture, MVP acceptance criteria, open decisions).

## Hard rules

- Never scrape LinkedIn or bypass logins/captchas. Respect robots.txt and source terms.
- Generated CVs may only use facts from master_cv.yaml; a validator enforces this.
- Human approves every application. No auto-submit.
- Profile-driven: never hardcode roles, skills, markets or keywords; they come from master_cv.yaml and preferences.yaml (outside the repo).
- Do not add a dependency, source, or service without a spec change.
- Never read or print secrets. Never run terraform apply/destroy without asking.
- Commit and push to `main` after each verified task (`make check` passing), so progress is easy to track. Never force-push or rewrite pushed history without asking. The remote is `GoGPenguin/jobhunt-platform`; if `GH_TOKEN` is set for another account, push with `env -u GH_TOKEN git push`.

## Stack

Python 3.12 (uv, ruff, mypy --strict, pytest), Pydantic, Postgres+pgvector, k3s/kind, Helm, ArgoCD, Terraform, GitHub Actions.

## Layout

- `apps/jobhunt/` — the one Python package (uv project, src layout) for all services; each service is an entrypoint of it
- `infra/` — Terraform
- `deploy/` — Helm charts and ArgoCD config
- `docs/spec/` — overview, constitution, one spec per feature
- `docs/plans/` — implementation plan and task list per spec
- `docs/decisions/` — numbered per-task verification notes and decision records (`NNNN-title.md`)

## Workflow

Plan first. One task at a time. Tests before or with code. After each task, note what
was verified (IAM scope, secrets, cost) in docs/decisions/.

Ask before deciding: at the start of each task, list every design choice the spec, plan and
constitution don't settle, and ask the user in one batch, with options and a recommendation.
Don't decide silently and report afterwards. Purely mechanical choices (formatting, test layout)
don't need asking. Record the answers in docs/decisions/.

## Commands

Run from the repo root. uv manages Python (pinned to an exact version in `apps/jobhunt/.python-version`, same in CI) and the venv in `apps/jobhunt/`.

- `make install` — create the venv from `uv.lock`
- `make check` — ruff lint + format check, `mypy --strict`, pytest, schema drift check (what CI runs)
- `make test`, `make lint`, `make typecheck`, `make format`
- `make schema` — regenerate `schemas/*.json` after changing a model; commit them with the model change
- `make golden` — rewrite parser golden files (`tests/fixtures/sources/<parser>/<case>/expected.json`) after an intended parser change; review the diff and bump the parser version
- Fixtures are public: fictional content only. `tests/test_fixture_privacy.py` fails on tokens, non-example email addresses, and personal strings listed in the private `~/.config/jobhunt/privacy-scan.txt`
- Single test: `uv run --directory apps/jobhunt pytest tests/test_smoke.py::test_package_imports`
- Add a dependency (only after spec approval): `uv add --directory apps/jobhunt <pkg>`
- `make collect-email` (`SINCE=3d`, `EML="a.eml b.eml"`, `DRY_RUN=1`) — `jobhunt collect email`: reads the Gmail label read-only (only emails not stored yet), stores jobs, prints new/updated ones as JSON lines; `DRY_RUN=1` needs no database. Config in `~/.config/jobhunt/`
- `jobhunt reparse [--source ID]` — re-run current parsers over stored raw payloads (after a parser fix and version bump); `jobhunt db prune-raw [--older-than 365d]` — raw-payload retention
- `make db-up` / `make db-down` — Postgres 18 + pgvector in Docker Compose (127.0.0.1 only); `db-up` first generates missing DB passwords into `secrets.env` (never type them)
- `make db-migrate` — `jobhunt db bootstrap` (roles, database; as admin) then `jobhunt db migrate` (SQL files in `jobhunt/store/migrations/`, as `jobhunt_owner`). The app connects as `jobhunt_app` (rows only, no DDL)
- `make test-db` — store tests against a throwaway Postgres (port 55432, in memory, removed afterwards); CI runs them via a service container. Without `JOBHUNT_TEST_DATABASE_ADMIN_URL`, Postgres tests are skipped
- `make digest` — `jobhunt digest send`: Telegram digest of postings not sent yet, ranked by fit (spec 07; filtered ones counted and marked, never shown; a broken profile still sends with a warning) and marked only after Telegram accepts every message; `--test` sends a test line; `jobhunt digest list [--since 7d]` (ranked, with score and reasons); `jobhunt telegram find-chat` for setup. Token and chat id in `secrets.env` (`JOBHUNT_TELEGRAM_BOT_TOKEN`, `JOBHUNT_TELEGRAM_CHAT_ID`)
- `make install-timer` (`DIGEST_TIME=12:00`) / `make uninstall-timer` — systemd user timer on this machine: collect, then send the digest daily in `preferences.yaml`'s timezone; `journalctl --user -u jobhunt-daily` for logs. Replaced by collector-runtime
- `jobhunt profile check` — validate `master_cv.yaml`, `preferences.yaml` (spec 06, samples in `config/*.sample.yaml`) and the bundled skill aliases (`jobhunt/profile/skill_aliases.yaml`); messages name entries by location, never personal values
- `make up` / `make down` for the whole stack arrive with the collector-runtime spec.
