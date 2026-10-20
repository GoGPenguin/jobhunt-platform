# 0002: Bundled ISO code lists

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), decision 2; plan task 2

## Decision

- Country (ISO 3166-1 alpha-2), currency (ISO 4217) and language (ISO 639-1) codes ship as frozensets in `jobhunt.domain.codes`, with no runtime dependency.
- Generated from Debian's `iso-codes` 4.20.1 JSON, the same data `pycountry` packages, by `apps/jobhunt/scripts/gen_iso_codes.py`. The generator is committed so the lists can be refreshed instead of edited by hand.
- The full ISO 4217 list is kept as published, including non-salary codes such as `XAU` (gold) and `XXX` (no currency). Filtering those is a parser concern, not a reason to diverge from the standard.
- Ruff rule SIM905 is disabled for the generated files only, to keep them as compact space-separated strings.

## Verified

- Tests written first and failed on import before the lists existed.
- 42 tests: expected members (`VN`, `VND`, `vi`…), common mistakes rejected (`Vietnam`, `UK`, `vn` as a language, `XYZ`, lowercase currency), exact sizes (249 / 178 / 183) and code formats.
- `make check` passes, including `mypy --strict` over the generator script.
- No new dependencies, no secrets, cost $0.
