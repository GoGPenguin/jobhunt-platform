# 0007: Committed JSON Schemas and drift check

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), "Versioning", S5; plan task 7

## Decisions asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Which shape does the schema describe? | The stored/output shape: every field always present. |
| Also commit a dead-letter schema? | Yes, `schemas/dead_letter.v1.json`; spec updated. |
| Should the schema carry rules enforced by custom code? (raised after seeing the first output) | Formats and lengths: ISO-code patterns, region pattern, language pattern, title/company/place/description length limits. Exact code membership stays in the model only. |

## Implementation

- `python -m jobhunt.tools.export_schema --out <dir> [--check]` renders `job.v1.json` and `dead_letter.v1.json` (JSON Schema 2020-12, serialization mode).
- `make schema` writes them to `schemas/` at the repo root; `make check` now also runs `schema-check`, which fails with the file names and "Run: make schema".
- Models set `json_schema_serialization_defaults_required`, so fields with defaults are still required in the stored-shape schema (28 of 28 Job fields).
- Rules enforced by custom validators are mirrored into the schema with `json_schema_extra`. They document the contract for other readers; the model remains the validator.
- `salary.min`/`max` appear as strings because Pydantic serializes `Decimal` as a string to keep exact amounts (no float rounding of e.g. 25,000,000 VND).

## Verified

- Tests written first; 8 export tests, 167 in total; `make check` passes.
- Drift check seen failing for real twice: before the files existed (both missing), and after the schema-rules change (`job.v1.json` stale). Both passed after `make schema`.
- Rendering is deterministic (same output on repeated runs).
- No new dependencies, no secrets, cost $0.
