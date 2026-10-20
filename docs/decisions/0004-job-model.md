# 0004: Canonical Job model (v1)

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md); plan task 4

## Decisions asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Job-alert emails have no description | `description` may be `""`; the public job page is fetched later to fill it in. |
| Unknown enum value | Strict on parse (error, dead letter); on read from storage it becomes `unknown`. |
| Unknown field | Strict on parse (error, catches parser typos); ignored on read from storage. |
| Salary periods | Added `week`, `day`, `unknown` to year/month/hour. |

The spec was updated with all four before implementation (commit `9529616`).

## Implementation choices (mechanical)

- `Job.from_parser(data, allow_http=...)` and `Job.from_storage(data)` are the two entry points. The strict/lenient switch and the HTTP allowance travel in Pydantic's validation context, so the same model serves both paths. Stored jobs may keep `http` URLs, because they were already checked against their source's config when written.
- List fields are tuples, so `job.tags.append(...)` is impossible, not just `job.tags = ...`. **Limitation:** the `extra` dict can still be changed in place; core logic never reads `extra` (spec rule), so this is accepted.
- `description_truncated` is computed by the model, not supplied by parsers.
- Collection fields (`locations`, `tags`, `extra`) default to empty and `schema_version` defaults to 1, so parsers don't repeat constants. Every serialized job still contains them.
- Region entries are checked by format only (`[A-Z][A-Z0-9_]{1,31}`), so country codes and open labels like `EU` or `LATAM` both pass, as decided in the spec.
- Runtime dependency added: `pydantic>=2.10,<3` (locked at 2.14.1), approved in the constitution. The `pydantic.mypy` plugin is enabled.

## Verified

- Tests written first, with three fictional fixtures (Singapore company board, APAC remote board with attribution, Vietnamese job-alert email with empty description and a net monthly VND salary). They failed before the model existed.
- 47 job-model tests, 127 in total; `make check` passes (ruff, format, `mypy --strict`, pytest).
- Spec acceptance criteria: S1 (fixtures build), S2 (one error lists title, currency, country and naive `posted_at` together; output checked by hand for readability), S4 (JSON round-trip equal, assignment fails, collections are tuples).
- Strict/lenient behaviour tested both ways, including that `from_storage` doesn't modify its input.
- No secrets, cost $0.

## For later specs

- **source-framework / collector-runtime:** jobs with an empty description need a step that politely fetches the public job page (`html_page` transport) and re-parses, before matching and summaries.
