# 0018: Database setup: Compose, roles, bootstrap, migrations

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), D1, D10; plan [04](../plans/04-dedupe-store.md) task 3

## Decisions

- **Image** (plan): `pgvector/pgvector:0.8.7-pg18-trixie`, pinned by digest, in Compose and CI. Inspected after pulling: PostgreSQL 18.6, `VOLUME /var/lib/postgresql`, `PGDATA=/var/lib/postgresql/18/docker`. The named volume mounts `/var/lib/postgresql`, as the 18 images expect.
- **Roles** (asked): `jobhunt_owner` owns the database and schema and runs migrations; `jobhunt_app` has `CONNECT`/`TEMPORARY` on the database, `USAGE` on the schema, and row privileges on all current and future tables (default privileges), except writes to `schema_migrations`. `PUBLIC` has no access to the database and can't create in `public`.
- **No passwords typed:** `jobhunt db init-secrets` (also run by `make db-up`) appends random 32-byte URL-safe passwords for admin, owner and app to `secrets.env` (mode 600), keeps existing values, and prints only the names.
- **Bootstrap** (as admin, idempotent) creates or updates the roles with passwords sent as SQL literals composed by psycopg, then creates the database. The same code sets up test databases, so there's no separate init script to drift.
- **Migrations:** `NNNN_name.sql` files inside the package (`jobhunt/store/migrations/`) rather than `apps/jobhunt/migrations/` as the plan said, so an installed package or Docker image finds them. Numbering must be contiguous. Each migration runs in its own transaction under an advisory lock and is recorded in `schema_migrations`. A version in the database that the code doesn't know is an error (newer code ran first).
- **pgvector** is in the image but not enabled; the matcher's migration will create the extension.
- **Compose hardening:** port published on `127.0.0.1` only, `no-new-privileges`, healthcheck, and the admin password required (`${…:?}`) so Compose refuses to start without it.
- **Test database:** `docker-compose.test.yml` (`!override` ports, `!reset` volumes, `tmpfs`) gives `make test-db` a throwaway server on port 55432, separate from the real one and removed afterwards. Each test creates and drops its own `jobhunt_test_<random>` database with random role passwords. CI uses a service container with a CI-only password.
- **CLI:** `jobhunt db init-secrets | bootstrap | migrate`; exit code 4 for database errors, 2 for missing passwords; all three passwords are redacted from logs once loaded.

## Verified

- Tests written first. Without a database: 370 passed, 4 skipped. `make test-db` against real PostgreSQL 18.6: 51 store tests passed, then the container, network and data were removed.
- D1: bootstrap twice is fine; migrations apply once and re-running applies nothing; an unknown applied version is refused.
- Least privilege: as `jobhunt_app`, `CREATE TABLE`, `DROP TABLE jobs`, `ALTER TABLE jobs` and writing `schema_migrations` all fail with `InsufficientPrivilege`, while reading and deleting rows work.
- D10: `db bootstrap`/`migrate` against an unreachable port exit 4 and print host and port but none of the passwords; `init-secrets` prints names, never values.
- Compose config checked for both files (test override publishes only `127.0.0.1:55432`).
- New dependency: `psycopg[binary]` 3.3.6 (approved with spec 04). No real database or secret created on the user's machine yet; cost $0.
