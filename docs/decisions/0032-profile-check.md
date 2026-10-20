# 0032: `jobhunt profile check`; privacy scan covers config/

Date: 2026-10-20
Spec: [06-profile](../spec/06-profile.md), P1, P6 (samples), P8; plan [06](../plans/06-profile.md) task 4

## Implementation

- `jobhunt profile check [--config-dir]` loads the whole profile:
  - errors: file-level validation errors, fact skills not found by name or alias, a missing `master_cv.yaml`;
  - warnings: unreviewed Vietnamese texts, an empty LinkedIn, a missing `preferences.yaml`.

  It logs each line to stderr and prints `{"type": "summary", "errors": n, "warnings": m}`; exit 0 when there are no errors, 2 otherwise.
- Every message is a location plus our own text (decisions 0030, 0031), so the output can be shared without exposing the CV.
- The fixture privacy scan now also covers `config/*` (the three sample files and `sources.sample.yaml`), with test ids relative to the repo root.

## Verified

- Tests written first (5 new; 504 in total); `make check` passes.
- Sample profile: exit 0, one warning (`contoso-alerting` Vietnamese not reviewed). A fact skill missing from `skills` and a number missing from the text each give one error naming the fact. A planted CV sentence and email address don't appear in the output. A missing master CV is an error.
- Privacy scan: 30 checks over fixtures and `config/` pass, with the private personal-string list present.
- No new dependencies, cost $0.
