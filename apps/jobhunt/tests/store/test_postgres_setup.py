"""Bootstrap and migrations against a real Postgres (spec 04, D1). Skipped unless
JOBHUNT_TEST_DATABASE_ADMIN_URL points at a throwaway server (`make test-db`, or CI)."""

import psycopg
import pytest
from conftest import ScratchDatabase

from jobhunt.store.migrate import MigrationError, bootstrap, discover_migrations, migrate
from jobhunt.store.settings import APP_ROLE, OWNER_ROLE


@pytest.fixture
def db(pg_database: ScratchDatabase) -> ScratchDatabase:
    return pg_database


def test_bootstrap_is_idempotent(db: ScratchDatabase) -> None:
    passwords = {"owner_password": db.owner_password, "app_password": db.app_password}
    bootstrap(db.admin, db.settings, **passwords)
    with psycopg.connect(db.admin) as conn:
        rows = conn.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'jobhunt_%'")
        roles = {r for (r,) in rows}
        owner = conn.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
            (db.settings.name,),
        ).fetchone()
    assert {OWNER_ROLE, APP_ROLE} <= roles
    assert owner == (OWNER_ROLE,)


def test_migrate_applies_once(db: ScratchDatabase) -> None:
    assert migrate(db.owner) == []  # the fixture already migrated
    with psycopg.connect(db.owner) as conn:
        versions = [v for (v,) in conn.execute("SELECT version FROM schema_migrations ORDER BY 1")]
    assert versions == [m.version for m in discover_migrations()]


def test_app_role_reads_and_writes_rows_only(db: ScratchDatabase) -> None:
    with psycopg.connect(db.app) as conn:
        conn.execute("SELECT count(*) FROM jobs").fetchone()
        conn.execute("DELETE FROM raw_payloads")
    for statement in (
        "CREATE TABLE sneaky (id int)",
        "DROP TABLE jobs",
        "ALTER TABLE jobs ADD COLUMN x int",
        "INSERT INTO schema_migrations (version, name) VALUES (999, 'fake')",
    ):
        with psycopg.connect(db.app) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement.encode())


def test_unknown_applied_migration_is_an_error(db: ScratchDatabase) -> None:
    with psycopg.connect(db.owner) as conn:
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (9999, '9999_future')")
    with pytest.raises(MigrationError, match="9999"):
        migrate(db.owner)
