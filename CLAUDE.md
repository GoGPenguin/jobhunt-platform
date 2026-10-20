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
- Never read or print secrets. Never run terraform apply/destroy or push without asking.

## Stack

Python 3.12 (uv, ruff, mypy --strict, pytest), Pydantic, Postgres+pgvector, k3s/kind, Helm, ArgoCD, Terraform, GitHub Actions.

## Layout

- `apps/` — application code
- `infra/` — Terraform
- `deploy/` — Helm charts and ArgoCD config
- `docs/spec/` — overview, constitution, one spec per feature
- `docs/decisions/` — per-task verification notes and decision records

## Workflow

Plan first. One task at a time. Tests before or with code. After each task, note what
was verified (IAM scope, secrets, cost) in docs/decisions/.

## Commands

make test | make up | make down
