# Plan 04: Dedupe store

Spec: [04-dedupe-store](../spec/04-dedupe-store.md)
Status: approved 2026-10-20

## Decisions for this plan (asked 2026-10-20)

| Question | Answer |
| -------- | ------ |
| Database roles | Two: `jobhunt_owner` owns the tables and runs migrations; `jobhunt_app` can only read and write rows (no DDL). |
| Reparse command | Included: `jobhunt reparse` re-runs current parsers over stored raw payloads. |

## Design

**Postgres image:** `pgvector/pgvector:0.8.7-pg18-trixie@sha256:9d9c930220cb9bf2f956d10a8f909cf9973d9672ca0278aef2c1e6facccad2e0` (PostgreSQL 18, pgvector 0.8.7, released 2026-10-01), the same image in Compose and CI.

**Roles and setup, without typing passwords:**

1. `jobhunt db init-secrets` adds `JOBHUNT_DB_ADMIN_PASSWORD`, `JOBHUNT_DB_OWNER_PASSWORD` and `JOBHUNT_DB_APP_PASSWORD` to `~/.config/jobhunt/secrets.env` if they're missing. Random values, file kept at mode 600, never printed. Nobody has to type or paste a database password.
2. `make db-up` starts Postgres with the admin password, port `127.0.0.1:5432` only, named volume, healthcheck.
3. `jobhunt db bootstrap` (as admin, idempotent) creates both roles, sets their passwords, and creates the `jobhunt` database owned by `jobhunt_owner`.
4. `jobhunt db migrate` (as owner) applies `migrations/NNNN_name.sql` in order, recorded in `schema_migrations`. The first migration grants `jobhunt_app` row privileges, including on future tables.
5. Collectors, reparse and the digest connect as `jobhunt_app`.

The same bootstrap-and-migrate code sets up the test database locally and in CI, so there's no separate init script to keep in sync.

**Connection settings:** host, port and database name default to `127.0.0.1`, `5432`, `jobhunt`, overridable with `JOBHUNT_DB_HOST`, `JOBHUNT_DB_PORT`, `JOBHUNT_DB_NAME`; passwords come from the secrets file or environment. All three passwords are redacted from logs.

**Code layout:** `jobhunt.store` with `fingerprint.py`, `port.py` (the `JobStore` protocol and result types), `memory.py` (fake), `postgres.py` (psycopg adapter), `migrations.py` (runner and bootstrap); SQL files in `apps/jobhunt/migrations/`.

## Dependencies (approved with the spec)

`psycopg[binary]` 3.x. Standard library for the rest (`secrets` for password generation).

## Tasks

Each task is test-first, ends with `make check` passing, a decision note, a commit and a push.

1. **Fingerprints.** `normalize_company`, `normalize_title`, `fingerprint`: NFC, casefold, diacritics removed (đ/Đ included, which Unicode decomposition alone misses), punctuation to spaces, legal suffixes removed from company names. Tests with Vietnamese and English company names.
2. **Store port, fake and contract tests.** `JobStore` (`known_raw_refs`, `store`, `postings`, `new_postings`, `raw_payloads`, `prune_raw`), result types (`new`/`updated`/`unchanged`), the in-memory fake, and one contract suite covering D2–D5 and D8, run against the fake.
3. **Database setup.** `docker-compose.yml`, `db init-secrets`, `db bootstrap`, `db migrate`, migration `0001_initial.sql`; `make db-up`, `db-down`, `db-migrate`. Tests: migrations apply to an empty database and re-apply as a no-op; `jobhunt_app` cannot create or drop tables. Covers D1 and D10.
4. **Postgres adapter.** psycopg implementation; the contract suite from task 2 runs against Postgres when `JOBHUNT_TEST_DATABASE_ADMIN_URL` is set (`make test-db` starts Compose and sets it). CI gets a Postgres service container with the pinned image, so the contract suite runs against both stores on every push. Covers D9.
5. **Only-new mail.** IMAP pre-check: fetch Message-ID headers (`BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]`), skip known `raw_ref`s, fetch the rest. The fake IMAP server's command log proves a second run fetches no bodies. Covers D7.
6. **CLI.** `jobhunt collect email` stores by default (summary gains new/updated/unchanged), `--dry-run` keeps phase A behaviour; `jobhunt db prune-raw [--older-than 365d]`; `jobhunt reparse [--source ID] [--parser NAME]`; exit code 4 when the database is unreachable. Covers D6 and D8.
7. **Manual check.** On your machine: `make db-up`, bootstrap, migrate, then `make collect-email SINCE=7d` twice. The first run stores the jobs; the second fetches headers only and reports 0 new. Then a quick look at the postings.

## Risks

- **Fingerprints miss renamed companies or reworded titles,** e.g. "Công ty TNHH Phần mềm Sông Hàn" vs "Song Han Software". Accepted in the spec; fuzzy matching comes with the matcher.
- **Docker volume loss loses the data.** Acceptable in the Compose phase; backups come with CloudNativePG (S3) in the Kubernetes phase.
- **CI time grows** with the Postgres service, by an estimated 10–20 s.
