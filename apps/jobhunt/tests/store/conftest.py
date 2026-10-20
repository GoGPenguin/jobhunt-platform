"""Store fixtures.

`store` runs every contract test against each JobStore implementation. `pg_database` creates a
fresh, bootstrapped and migrated database on the throwaway Postgres server named by
JOBHUNT_TEST_DATABASE_ADMIN_URL (`make test-db` locally, a service container in CI), and drops it
afterwards. Without that variable, Postgres tests are skipped.
"""

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from jobhunt.store.memory import MemoryJobStore
from jobhunt.store.migrate import bootstrap, migrate
from jobhunt.store.port import JobStore
from jobhunt.store.postgres import PostgresJobStore
from jobhunt.store.settings import APP_ROLE, OWNER_ROLE, DatabaseSettings, conninfo

ADMIN_URL = os.environ.get("JOBHUNT_TEST_DATABASE_ADMIN_URL")


@dataclass(frozen=True)
class ScratchDatabase:
    settings: DatabaseSettings
    admin: str  # admin connection to the maintenance database "postgres"
    owner: str
    app: str
    owner_password: str
    app_password: str


@pytest.fixture
def pg_database() -> Iterator[ScratchDatabase]:
    if not ADMIN_URL:
        pytest.skip("JOBHUNT_TEST_DATABASE_ADMIN_URL not set (run make test-db)")
    params = conninfo_to_dict(ADMIN_URL)
    settings = DatabaseSettings(
        host=str(params.get("host", "127.0.0.1")),
        port=int(str(params.get("port") or 5432)),
        name=f"jobhunt_test_{secrets.token_hex(4)}",
    )
    owner_password, app_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    db = ScratchDatabase(
        settings=settings,
        admin=ADMIN_URL,
        owner=conninfo(settings, OWNER_ROLE, owner_password),
        app=conninfo(settings, APP_ROLE, app_password),
        owner_password=owner_password,
        app_password=app_password,
    )
    bootstrap(ADMIN_URL, settings, owner_password=owner_password, app_password=app_password)
    migrate(db.owner)
    yield db
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        drop = sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(settings.name))
        conn.execute(drop)


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[JobStore]:
    if request.param == "memory":
        yield MemoryJobStore()
        return
    db: ScratchDatabase = request.getfixturevalue("pg_database")  # skips without a server
    with PostgresJobStore(db.app) as postgres:
        yield postgres
