"""Database connection settings and roles. See plan 04, "Roles and setup"."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from psycopg.conninfo import make_conninfo

OWNER_ROLE = "jobhunt_owner"  # owns tables, runs migrations
APP_ROLE = "jobhunt_app"  # reads and writes rows only
ADMIN_ROLE = "postgres"  # the server's superuser, used only by `jobhunt db bootstrap`

ADMIN_PASSWORD = "JOBHUNT_DB_ADMIN_PASSWORD"  # noqa: S105 - variable names, not values
OWNER_PASSWORD = "JOBHUNT_DB_OWNER_PASSWORD"  # noqa: S105
APP_PASSWORD = "JOBHUNT_DB_APP_PASSWORD"  # noqa: S105
DB_PASSWORD_KEYS = (ADMIN_PASSWORD, OWNER_PASSWORD, APP_PASSWORD)


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = "127.0.0.1"
    port: int = 5432
    name: str = "jobhunt"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        defaults = cls()
        return cls(
            host=env.get("JOBHUNT_DB_HOST", defaults.host),
            port=int(env.get("JOBHUNT_DB_PORT", defaults.port)),
            name=env.get("JOBHUNT_DB_NAME", defaults.name),
        )


def conninfo(
    settings: DatabaseSettings, user: str, password: str, dbname: str | None = None
) -> str:
    """libpq connection string; psycopg quotes the values, so any password is safe."""
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=dbname or settings.name,
        user=user,
        password=password,
        connect_timeout=10,
        application_name="jobhunt",
    )
