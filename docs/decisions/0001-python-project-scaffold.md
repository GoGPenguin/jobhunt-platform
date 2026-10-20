# 0001: Python project scaffold

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), plan task 1

## Decision

- One uv project at `apps/jobhunt` (src layout, `uv_build` backend) for all services; each service will be an entrypoint of the same package.
- Python pinned to 3.12 (`requires-python = ">=3.12,<3.13"`, `.python-version`), installed by uv, not the system Python (3.14 on the dev machine).
- Dev tools in a uv dependency group, exact versions locked in `uv.lock`: pytest, mypy (strict), ruff.
- Ruff rules include `S` (security) and `DTZ` (no timezone-naive datetimes, which the job schema forbids).
- Root `Makefile` is the single entry point; `make check` is what CI will run.
- uv itself is installed on the dev machine with mise (`mise use -g uv@latest`, uv 0.13.1).

## Verified

- `make check` passes: ruff lint and format check, `mypy --strict`, pytest (1 test) on Python 3.12.14.
- `make check` fails (exit 2) when a lint error is introduced.
- `.gitignore` blocks `master_cv.yaml` and `preferences.yaml` anywhere in the repo (`git check-ignore`), while `*.sample.yaml` fixtures stay committable.
- No runtime dependencies yet; nothing outside the approved tool list was added.
- No secrets, no cloud resources, cost $0.
