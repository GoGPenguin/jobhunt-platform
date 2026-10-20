# 0019: Postgres JobStore

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), D2–D5, D8, D9; plan [04](../plans/04-dedupe-store.md) task 4

## Implementation

- `PostgresJobStore(conninfo)` (context manager) connects as `jobhunt_app`, in autocommit mode with an explicit transaction per `store()` call, so a payload, its jobs and its dead letters commit together or not at all (D5).
- The upsert and posting rules are the shared functions from `jobhunt.store.port` (`plan_upsert`, `group_postings`, `select_new`, `dead_letter_key`), so Postgres and the in-memory store behave the same by construction.
- **Concurrency:** each job is first inserted with `ON CONFLICT DO NOTHING`. Only on conflict is the row locked (`SELECT … FOR UPDATE`), merged with `plan_upsert` and updated. A second transaction writing the same new job waits on the unique index until the first commits, then merges with its committed row. A plain read-then-upsert would let both believe the job is new and lose the earlier `first_seen_at`.
- `new_postings(since)` loads every job of any fingerprint that has a sighting after `since`, so country groups are complete before grouping, then applies the shared rules.
- `raw_payloads()` streams through a server-side cursor; SQL is written out literally (no f-strings in queries, ruff S608).
- Jobs are read back with `Job.from_storage` (lenient read).

## Verified

- The 14 contract tests now run against both stores (D9); `make test-db`: 66 store tests passed on PostgreSQL 18.6. Without a database: 370 passed, 19 skipped.
- **Concurrency test** (Postgres only): two connections released together by a barrier store the same new job with different `collected_at`, 25 rounds; `first_seen_at`/`last_seen_at` are always the earlier/later sighting.
- **The concurrency test was checked to fail:** with `_upsert` replaced by the naive read-then-upsert, it failed in round 0. The real code was then restored from a copy taken before the change. `git checkout` couldn't restore it, because the file wasn't committed yet; the backup copy was made for exactly that case.
- No new dependencies, no secrets, cost $0.
