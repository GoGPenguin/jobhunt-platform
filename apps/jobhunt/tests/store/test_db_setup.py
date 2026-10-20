"""Database setup without a database: secrets, settings, migration discovery."""

import io
from pathlib import Path

import pytest

from jobhunt.credentials import ensure_secrets, read_secrets_file
from jobhunt.store.migrate import MigrationError, discover_migrations
from jobhunt.store.settings import DB_PASSWORD_KEYS, DatabaseSettings, conninfo


class TestEnsureSecrets:
    def test_creates_file_with_random_passwords(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.env"
        out = io.StringIO()
        added = ensure_secrets(path, DB_PASSWORD_KEYS, out=out)
        assert added == list(DB_PASSWORD_KEYS)
        assert path.stat().st_mode & 0o777 == 0o600
        values = read_secrets_file(path)
        assert set(values) == set(DB_PASSWORD_KEYS)
        assert len({values[k] for k in DB_PASSWORD_KEYS}) == 3  # all different
        assert all(len(values[k]) >= 32 for k in DB_PASSWORD_KEYS)
        assert not any(v in out.getvalue() for v in values.values())  # names only, never values

    def test_keeps_existing_values(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.env"
        path.write_text("JOBHUNT_IMAP_USER=me@example.com\nJOBHUNT_DB_APP_PASSWORD=keep-me\n")
        path.chmod(0o600)
        added = ensure_secrets(path, DB_PASSWORD_KEYS, out=io.StringIO())
        assert "JOBHUNT_DB_APP_PASSWORD" not in added
        values = read_secrets_file(path)
        assert values["JOBHUNT_IMAP_USER"] == "me@example.com"
        assert values["JOBHUNT_DB_APP_PASSWORD"] == "keep-me"  # noqa: S105

    def test_second_run_adds_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.env"
        ensure_secrets(path, DB_PASSWORD_KEYS, out=io.StringIO())
        before = path.read_text()
        assert ensure_secrets(path, DB_PASSWORD_KEYS, out=io.StringIO()) == []
        assert path.read_text() == before


class TestSettings:
    def test_defaults(self) -> None:
        settings = DatabaseSettings.from_env({})
        assert (settings.host, settings.port, settings.name) == ("127.0.0.1", 5432, "jobhunt")

    def test_env_overrides(self) -> None:
        env = {"JOBHUNT_DB_HOST": "db", "JOBHUNT_DB_PORT": "55432", "JOBHUNT_DB_NAME": "jh"}
        assert DatabaseSettings.from_env(env) == DatabaseSettings("db", 55432, "jh")

    def test_conninfo_quotes_password(self) -> None:
        info = conninfo(DatabaseSettings("h", 1, "d"), "u", "p a'ss\\word")
        assert "password='p a\\'ss\\\\word'" in info
        assert "dbname=d" in info


class TestDiscoverMigrations:
    def test_bundled_migrations(self) -> None:
        migrations = discover_migrations()
        assert migrations[0].version == 1
        assert migrations[0].name == "0001_initial"
        assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))

    def test_rejects_bad_names_and_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "0001_initial.sql").write_text("select 1;")
        (tmp_path / "0003_skipped.sql").write_text("select 1;")
        with pytest.raises(MigrationError, match="0002"):
            discover_migrations(tmp_path)
        (tmp_path / "0003_skipped.sql").unlink()
        (tmp_path / "2_bad.sql").write_text("select 1;")
        with pytest.raises(MigrationError, match=r"2_bad\.sql"):
            discover_migrations(tmp_path)
