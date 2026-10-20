# 0017: JobStore port, in-memory store and contract tests

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), D2–D5, D8, D9; plan [04](../plans/04-dedupe-store.md) task 2

## Decision asked and answered before coding

| Question | Answer |
| -------- | ------ |
| A job without a country, when the same company + title exists in several countries | Joins only if exactly one country group exists; otherwise it stays its own posting. Spec 04 updated. |

## Implementation

- `jobhunt.store.port`: the `JobStore` protocol and result types (`StoredJob`, `Posting`, `StoreResult`). Two shared pure functions that every store must use:
  - `plan_upsert(existing, job)` decides how a sighting changes a stored job.
  - `group_postings(jobs)` decides which jobs form a posting.
  Sharing them means the fake and the Postgres store cannot drift apart on these rules.
- **Upsert rules** (derived from "latest + first/last seen"; spec wording updated):
  - All timestamps come from the job's `collected_at`, not the wall clock, so results are reproducible.
  - `first_seen_at` only moves earlier and `last_seen_at` only later. "Never changes" in the first draft would have been wrong when emails arrive out of order.
  - A repeat sighting with the same content (ignoring `collected_at`, `raw_ref`, `parser`) is `unchanged` and keeps the first sighting's data.
  - Output from an older version of the same parser (semver, so 1.10.0 > 1.9.0) never replaces newer output.
- **Dead letters** have an identity (raw_ref, parser, record), so storing the same payload twice adds them once.
- **Representative job** of a posting: one with a description first, then the earliest seen, then source and id as tie-breakers, so the choice is deterministic.
- `MemoryJobStore` stages every change on copies and swaps them in at the end, so a failure part-way stores nothing, matching a database transaction.

## Verified

- Contract tests written first (14) and run through a `store` fixture parametrized by implementation, ready for Postgres in task 4. 359 tests in total; `make check` passes.
- Covered: idempotent storing (jobs and dead letters), one job across two emails, out-of-order sightings, content updates, parser-version guard both ways, atomic failure, cross-source posting with LinkedIn (no country) + board (SG), VN/JP/no-country split, `new_postings` window and order, a posting not becoming new again when another source joins, raw payload order, retention keeping jobs.
- No new dependencies, no secrets, cost $0.
