# Spec 04: Dedupe store

Status: approved 2026-10-20
Depends on: [constitution](constitution.md), [01-canonical-job-schema](01-canonical-job-schema.md), [02-source-framework](02-source-framework.md)
Used by: notifications (digest of new jobs), matcher, collector-runtime

## User story

As the job seeker, I want every collected job stored once, with where and when it was seen, so that the daily digest shows only jobs that are new to me, and a job I get from two places shows up once.

## Scope

In scope:

- Postgres schema for raw payloads, jobs and dead letters, with numbered SQL migrations.
- A `JobStore` port with a Postgres adapter and an in-memory fake that pass the same contract tests.
- Idempotent ingest of one raw payload and its `build_jobs` result, in one transaction.
- Cross-source "postings": jobs from different sources that are the same job.
- A "new postings since" query for the notifications spec.
- Only-new mail: the IMAP transport skips emails already stored.
- Raw-payload retention (1 year).
- Docker Compose with Postgres only, plus make targets to start it and run migrations.
- `jobhunt collect email` stores results; `--dry-run` keeps the phase A behaviour.

Out of scope:

- Kubernetes and CloudNativePG (deploy-gitops). The schema is plain Postgres, so it moves unchanged.
- Embeddings and fuzzy matching (matcher); pgvector is installed but unused.
- Detecting closed jobs (a later spec); this one records `last_seen_at`.
- Scheduling and the full Compose stack (collector-runtime).

## Decisions (2026-10-20)

| Topic | Decision |
| ----- | -------- |
| Same job from two sources | Exact fingerprint of normalized company and title now, fuzzy matching later (matcher spec). |
| A job seen again with different fields | Keep the latest version, with `first_seen_at`, `last_seen_at` and the parser version. Older versions can be re-derived from raw payloads. |
| Database stack | psycopg 3 and plain numbered `.sql` migrations with a small runner. No ORM. |
| Raw payloads | A Postgres table (`bytea`), behind an interface so it can move to object storage later. |
| Only new mail | Fetch Message-IDs first (read-only), then bodies only for emails not stored yet. |
| Tests | An in-memory fake for unit tests; the same contract tests also run against real Postgres (Compose locally, a service container in CI). |
| Postgres | PostgreSQL 18 with pgvector, image pinned by digest. |
| Retention | Raw payloads are deleted after 1 year; jobs and dead letters stay. |

## Data model

```text
schema_migrations (version PK, name, applied_at)

raw_payloads      (raw_ref PK, origin, content_type, content bytea, fetched_at, stored_at)

jobs              (source, external_id) PK
                  data jsonb            -- the full canonical Job (schema v1, stored shape)
                  fingerprint           -- posting key, see below
                  language, collected_at, raw_ref, parser_name, parser_version
                  first_seen_at, last_seen_at, updated_at

dead_letters      (id PK, source, raw_ref, parser_name, parser_version, errors jsonb,
                   record jsonb, failed_at)
```

- `jobs.data` is read back with `Job.from_storage` (lenient on read, spec 01), so older code can read newer rows.
- `jobs.raw_ref` and `dead_letters.raw_ref` are plain text, not foreign keys: after retention deletes a raw payload, the job keeps a reference to what it was parsed from.
- Indexes: `jobs(fingerprint)`, `jobs(first_seen_at)`, `raw_payloads(fetched_at)`.

## Ingest

`store(payload, result)` writes one raw payload and its `build_jobs` result in **one transaction**:

1. Raw payload: insert; an existing `raw_ref` is left as is.
2. Each job: insert, or update on `(source, external_id)`:
   - `first_seen_at` only ever moves earlier (an older sighting can arrive late) and `last_seen_at` only later; both come from the job's `collected_at`.
   - `data` is replaced only if the new parser version is the same or newer (semver), so an old version running during a rollout can't overwrite newer output. `updated_at` changes only when the content changes; `collected_at`, `raw_ref` and `parser` don't count as content, so a repeat sighting is `unchanged` and keeps the first sighting's data.
   - Reported per job as `new`, `updated` or `unchanged`.
3. Dead letters: appended.

Storing the same payload and result twice changes nothing and reports every job as `unchanged`.

## Postings: one job from many sources

A **posting** is the set of stored jobs with the same fingerprint and no conflicting countries.

- **Fingerprint:** SHA-256 of `normalize(company) | normalize(title)`.
  - **Normalize:** NFC, case-folded, Vietnamese and other diacritics removed ("Đà Nẵng" → "da nang"), punctuation turned into spaces, whitespace collapsed.
  - **Company also drops legal suffixes:** TNHH, JSC, Co., Ltd., Company Limited, Pte. Ltd., Inc., Corp., GmbH, and similar.
- **Countries:** two jobs with the same fingerprint but different *known* countries (VN and JP) are separate postings. A job without a country (LinkedIn alerts often name only a city) joins only if exactly one country group exists; with several it stays its own posting rather than being guessed into one (decided 2026-10-20).
- **What a posting is when read:** its earliest `first_seen_at`, plus a representative job, which is the one with a description, else the earliest seen.
- Fuzzy matching (abbreviations, reordered words) comes with the matcher spec; the fingerprint stays as its first, cheap step.

`new_postings(since)` returns postings whose earliest `first_seen_at` is after `since`, newest first. This is what the Telegram digest reads.

## Only-new mail

The IMAP transport gains a pre-check: `UID FETCH <uids> (BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])` for every UID in the window. Read-only, as F4 requires. It computes each `raw_ref` the same way `RawPayload.from_email` does, asks the store which are already known, and fetches full bodies only for the rest. Messages without a Message-ID are always fetched; their `raw_ref` comes from the content.

## Retention

`jobhunt db prune-raw [--older-than 365d]` deletes raw payloads whose `fetched_at` is older than the cut-off and reports how many. Jobs and dead letters are kept. It runs on demand now; collector-runtime schedules it.

## Running Postgres (Compose phase)

- `docker-compose.yml` at the repo root with one service: PostgreSQL 18 + pgvector, image pinned by digest, a named volume, a `pg_isready` healthcheck, and the port bound to **127.0.0.1 only**.
- Credentials: `JOBHUNT_DATABASE_URL` (and the container's `POSTGRES_PASSWORD`) come from `~/.config/jobhunt/secrets.env`, never from the repo; the password is redacted from logs like the IMAP one.
- `make db-up`, `make db-down`, `make db-migrate`. `make up`/`make down` for the whole stack still arrive with collector-runtime.

## Acceptance criteria

- **D1:** `make db-up` starts Postgres reachable only on 127.0.0.1; `make db-migrate` applies pending migrations in order and is a no-op the second time; CI applies all migrations to a fresh Postgres.
- **D2 (MVP AC2):** storing the same payload twice adds nothing the second time; a job seen in two emails is stored once, with `first_seen_at` from the first and `last_seen_at` from the second.
- **D3:** output from a newer parser version replaces stored data; output from an older version never does.
- **D4:** "Senior DevOps Engineer" at "Lumen Robotics Pte. Ltd." (LinkedIn, no country) and "Senior DevOps Engineer" at "Lumen Robotics" (Greenhouse, SG) form one posting; the same title at the same company in VN and in JP are two.
- **D5:** if storing any part of a payload fails, nothing from that payload is stored.
- **D6:** `jobhunt collect email` stores by default and its summary reports new, updated and unchanged jobs; `--dry-run` stores nothing and needs no database.
- **D7:** a second run over the same mailbox fetches headers only, no bodies (checked with the fake IMAP server's command log).
- **D8:** `prune-raw` deletes only raw payloads older than the cut-off; jobs are untouched and still readable.
- **D9:** one contract test suite runs against both the in-memory fake and Postgres, so the fake can't drift from the real store.
- **D10:** the database password never appears in logs or errors.

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| Same email fetched again (overlapping `--since`) | Skipped by the pre-check; if it slips through, the insert is a no-op. |
| Parser fix re-run on stored raw payloads | Newer version: jobs updated, `first_seen_at` kept. |
| Two runs at the same time | Upserts and `raw_ref` keys make the result the same as running them one after the other. |
| Company "Công ty TNHH Phần mềm Sông Hàn" vs "Song Han Software" | Different fingerprints (different words): fuzzy matching's job later. |
| Job stored by a newer schema version | `Job.from_storage` ignores unknown fields and maps unknown enum values to `unknown`. |
| Database down | Collection fails with a clear error and exit code 4; nothing is half-stored. |

## Dependencies

- `psycopg[binary]` 3.x: the Postgres driver (approved with this spec, 2026-10-20).
- No ORM, no migration framework, no pgvector Python package yet.

## Test plan

- Contract tests for `JobStore` (idempotency, upsert rules, parser-version guard, postings, `new_postings`, retention, transactions), run against the fake always and against Postgres when `JOBHUNT_TEST_DATABASE_URL` is set: by `make test-db` locally, and by a Postgres 18 service container in CI.
- Unit tests for fingerprint normalization (Vietnamese diacritics, legal suffixes).
- Migration tests: apply all to an empty database, re-apply as a no-op.
- IMAP pre-check tests with the fake server's command log (D7).
- CLI tests for storing, `--dry-run`, and a database-down error.
