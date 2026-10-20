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

Run from the repo root. uv manages Python 3.12 and the venv in `apps/jobhunt/`.

- `make install` — create the venv from `uv.lock`
- `make check` — ruff lint + format check, `mypy --strict`, pytest, schema drift check (what CI runs)
- `make test`, `make lint`, `make typecheck`, `make format`
- `make schema` — regenerate `schemas/*.json` after changing a model; commit them with the model change
- Single test: `uv run --directory apps/jobhunt pytest tests/test_smoke.py::test_package_imports`
- Add a dependency (only after spec approval): `uv add --directory apps/jobhunt <pkg>`
- `make up` / `make down` arrive with Docker Compose in the collector-runtime spec.
