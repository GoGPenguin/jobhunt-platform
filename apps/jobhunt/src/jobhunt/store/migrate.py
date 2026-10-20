"""Database bootstrap (roles, database) and numbered SQL migrations. See plan 04, task 3.

bootstrap runs as the server admin and is idempotent. migrate runs as jobhunt_owner, applies
migrations/NNNN_name.sql files in order, one transaction each, recorded in schema_migrations,
under an advisory lock so two runs can't interleave.
"""

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from jobhunt.store.settings import APP_ROLE, OWNER_ROLE, DatabaseSettings

_FILE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_LOCK_ID = 72_610_001  # pg_advisory_lock key for migrations


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str  # file name without .sql
    sql: str


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """Bundled migrations (or those in `directory`), checked to be numbered 1, 2, 3, ..."""
    root = directory or Path(str(resources.files("jobhunt.store.migrations")))
    files = sorted(p for p in root.iterdir() if p.suffix == ".sql")
    migrations = []
    for path in files:
        match = _FILE.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration files must be named NNNN_name.sql")
        migrations.append(Migration(int(match.group(1)), path.stem, path.read_text("utf-8")))
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(f"missing migration {expected:04d} before {migration.name}")
    return migrations


def bootstrap(
    admin: str, settings: DatabaseSettings, *, owner_password: str, app_password: str
) -> None:
    """Create or update both roles, and create the database owned by jobhunt_owner."""
    owner, app = sql.Identifier(OWNER_ROLE), sql.Identifier(APP_ROLE)
    database = sql.Identifier(settings.name)
    with psycopg.connect(admin, autocommit=True) as conn:
        for role, password in ((OWNER_ROLE, owner_password), (APP_ROLE, app_password)):
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            verb = sql.SQL("ALTER" if exists else "CREATE")
            statement = sql.SQL(
                "{} ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
            ).format(verb, sql.Identifier(role), sql.Literal(password))
            conn.execute(statement)
        found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.name,))
        if not found.fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(database, owner))
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database))
        conn.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(database, app))
    with psycopg.connect(_with_dbname(admin, settings.name), autocommit=True) as conn:
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(app))


def migrate(owner: str) -> list[str]:
    """Apply pending migrations; returns the names applied (empty when up to date)."""
    migrations = discover_migrations()
    known = {m.version for m in migrations}
    applied_now: list[str] = []
    with psycopg.connect(owner, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version integer PRIMARY KEY,"
                " name text NOT NULL,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = {v for (v,) in conn.execute("SELECT version FROM schema_migrations")}
            unknown = sorted(applied - known)
            if unknown:
                raise MigrationError(
                    f"database has migrations this code doesn't know: {unknown} (newer code ran?)"
                )
            for migration in migrations:
                if migration.version in applied:
                    continue
                with conn.transaction():
                    conn.execute(migration.sql.encode())
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                        (migration.version, migration.name),
                    )
                applied_now.append(migration.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied_now


def _with_dbname(conninfo: str, dbname: str) -> str:
    return make_conninfo(conninfo, dbname=dbname)
