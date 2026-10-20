# 0008: CI on GitHub Actions and public repository

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), S5 (CI check); plan task 8

## Decisions asked and answered before acting

| Question | Answer |
| -------- | ------ |
| Create the GitHub repo and push so CI can be verified? | Yes, under the personal account `GoGPenguin` (public, per the overview's repo-visibility decision). |
| How to pin actions? | Full commit SHAs with a version comment, plus Dependabot weekly updates. |

## Implementation

- `.github/workflows/ci.yaml` runs `make install` and `make check` on pushes to `main` and on pull requests.
- `permissions: contents: read`, `persist-credentials: false` on checkout, a 10-minute timeout, and cancellation of superseded runs.
- Actions pinned: `actions/checkout` v7.0.1 (`3d3c42e…`), `astral-sh/setup-uv` v10.3.0 (`1c37ad0…`); uv pinned to 0.13.1, same as the dev machine. setup-uv's inputs were read from its `action.yml` at that exact commit.
- `.github/dependabot.yml`: weekly updates for GitHub Actions and for `apps/jobhunt/uv.lock`.

## Verified

- **Before publishing**, the whole git history (every version of every file, plus commit metadata) was scanned for personal data. No hits for: phone number, work email, employer and project names, CV-only facts (GPA, TOEIC), full name as written in the CV, relocation preferences, tokens. The only personal identifier is the commit author email the user chose (`son72ltv2@gmail.com`).
- Repo created: https://github.com/GoGPenguin/jobhunt-platform (public).
- First CI run (#39389301388) passed in 11 s. Its log shows ruff, `mypy --strict` (20 files), 167 tests and the schema drift check.
- CI uses the runner's Python 3.12.3; locally uv manages 3.12.14. Same minor version, as `requires-python` allows; the unused `cache-python` option was removed.
- The workflow token can only read the repo; no secrets are configured; GitHub Actions minutes on a public repo cost $0.

## Plan 01 status

All 8 tasks are done. Spec acceptance criteria S1–S7 are covered by tests that run in CI.
