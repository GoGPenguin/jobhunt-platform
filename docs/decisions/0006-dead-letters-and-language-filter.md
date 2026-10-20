# 0006: Dead letters, batch building and posting-language filter

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), "Validation and invalid records", S6, S7; plan task 6

## Decisions asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Keep the parser's record in a dead letter? | Yes, next to the field errors. |
| Where does `raw_ref` come from? | Per batch: one raw payload usually holds many jobs. |
| Restrict to my languages (raised by the user) | Only vi and en postings are wanted. |
| Where to filter other languages? | Drop at collection (counted, not stored). |
| Jobs with language `unknown`? | Keep: mostly alert-email jobs without a description yet. |

The spec and overview were updated first (commit `192af7d`), and `languages.postings: [vi, en]` was added to the private `preferences.yaml`.

## Implementation

- `build_jobs(records, source=, parser=, raw_ref=, accepted_languages=, allow_http=)` in `jobhunt.domain.dead_letter` returns `BuildResult(jobs, dead_letters, dropped_languages)`.
- Batch-level `source`, `parser` and `raw_ref` override whatever a record contains, so even a broken record's dead letter points to its payload.
- `DeadLetter` holds source, raw_ref, parser, field errors (dotted `loc`, message, type), the record, and `failed_at` in UTC. A record that isn't a mapping at all becomes a dead letter of type `not_a_mapping`.
- **The language list is a parameter, not code.** The caller passes it from the profile, so the vi/en choice lives in `preferences.yaml` and other users can choose their own (constitution guardrail 5).
- The clock is injectable (`now=`) so tests are deterministic.

## Verified

- Tests written first and failed before the module existed. 10 tests, 159 in total; `make check` passes.
- S6: a batch of three with one bad record gives two jobs and one dead letter carrying the batch's source, raw_ref and parser.
- S7: with `{vi, en}`, Japanese and German jobs are dropped and counted (`{"ja": 2, "de": 1}`), `vi`, `en` and `unknown` are kept. With no filter, everything is kept.
- Input records are not modified; a dead letter with datetimes in its record round-trips through JSON.
- No new dependencies, no secrets, cost $0.

## For later specs

- **Description fetch** (source-framework / collector-runtime): re-run `build_jobs` on the fetched page with the same language filter, so a job that was `unknown` and turns out to be Japanese is dropped then.
- **Observability:** `dropped_languages` and the dead-letter count per source are the inputs for the parse-success and drift metrics in the SLOs.
