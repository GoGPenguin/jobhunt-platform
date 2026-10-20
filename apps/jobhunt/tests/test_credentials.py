import io
import logging
from pathlib import Path

import pytest

from jobhunt.config_files import ConfigError
from jobhunt.credentials import imap_credentials, read_secrets_file
from jobhunt.logs import configure_logging

FAKE_PASSWORD = "zq9fakeapppass7x"  # noqa: S105 - a planted value the tests look for


def secrets_file(tmp_path: Path, text: str, mode: int = 0o600) -> Path:
    path = tmp_path / "secrets.env"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


class TestReadSecretsFile:
    def test_parses_lines(self, tmp_path: Path) -> None:
        path = secrets_file(
            tmp_path,
            "# Gmail\nJOBHUNT_IMAP_USER=me@example.com\n\n"
            f"export JOBHUNT_IMAP_APP_PASSWORD='{FAKE_PASSWORD}'\nOTHER=\"quoted value\"\n",
        )
        assert read_secrets_file(path) == {
            "JOBHUNT_IMAP_USER": "me@example.com",
            "JOBHUNT_IMAP_APP_PASSWORD": FAKE_PASSWORD,
            "OTHER": "quoted value",
        }

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert read_secrets_file(tmp_path / "secrets.env") == {}

    @pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
    def test_refuses_file_readable_by_others(self, tmp_path: Path, mode: int) -> None:
        path = secrets_file(tmp_path, f"JOBHUNT_IMAP_APP_PASSWORD={FAKE_PASSWORD}\n", mode)
        with pytest.raises(ConfigError, match="chmod 600") as exc:
            read_secrets_file(path)
        assert FAKE_PASSWORD not in str(exc.value)

    def test_bad_line_names_line_not_content(self, tmp_path: Path) -> None:
        path = secrets_file(tmp_path, f"JOBHUNT_IMAP_USER=me\n{FAKE_PASSWORD}\n")
        with pytest.raises(ConfigError, match="line 2") as exc:
            read_secrets_file(path)
        assert FAKE_PASSWORD not in str(exc.value)


class TestImapCredentials:
    def test_from_file(self, tmp_path: Path) -> None:
        path = secrets_file(
            tmp_path,
            f"JOBHUNT_IMAP_USER=me@example.com\nJOBHUNT_IMAP_APP_PASSWORD={FAKE_PASSWORD}\n",
        )
        creds = imap_credentials(env={}, secrets_path=path)
        assert creds.user == "me@example.com"
        assert creds.password.get_secret_value() == FAKE_PASSWORD

    def test_environment_wins_over_file(self, tmp_path: Path) -> None:
        path = secrets_file(tmp_path, "JOBHUNT_IMAP_USER=file@example.com\n")
        env = {"JOBHUNT_IMAP_USER": "env@example.com", "JOBHUNT_IMAP_APP_PASSWORD": FAKE_PASSWORD}
        assert imap_credentials(env=env, secrets_path=path).user == "env@example.com"

    def test_missing_names_variables_and_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="JOBHUNT_IMAP_APP_PASSWORD") as exc:
            imap_credentials(env={"JOBHUNT_IMAP_USER": "me"}, secrets_path=tmp_path / "s.env")
        assert "s.env" in str(exc.value)

    def test_never_printed(self, tmp_path: Path) -> None:
        env = {"JOBHUNT_IMAP_USER": "me@example.com", "JOBHUNT_IMAP_APP_PASSWORD": FAKE_PASSWORD}
        creds = imap_credentials(env=env, secrets_path=tmp_path / "none")
        assert FAKE_PASSWORD not in repr(creds)
        assert FAKE_PASSWORD not in str(creds)


class TestLogRedaction:
    """F11: the password never appears in log output, however it gets there."""

    @pytest.fixture
    def log_output(self) -> io.StringIO:
        stream = io.StringIO()
        configure_logging(secrets=[FAKE_PASSWORD], stream=stream, level=logging.DEBUG)
        return stream

    def test_message_args_and_exceptions(self, log_output: io.StringIO) -> None:
        log = logging.getLogger("jobhunt.test")
        log.info("login with %s", FAKE_PASSWORD)
        log.warning(f"inline {FAKE_PASSWORD} in message")
        try:
            raise RuntimeError(f"server said: bad password {FAKE_PASSWORD}")
        except RuntimeError:
            log.exception("login failed")
        output = log_output.getvalue()
        assert FAKE_PASSWORD not in output
        assert output.count("***") >= 3
        assert "login failed" in output
        assert "RuntimeError" in output

    def test_unrelated_messages_untouched(self, log_output: io.StringIO) -> None:
        logging.getLogger("jobhunt.test").info("read %d emails", 3)
        assert "read 3 emails" in log_output.getvalue()

    def test_empty_secret_ignored(self) -> None:
        stream = io.StringIO()
        configure_logging(secrets=["", FAKE_PASSWORD], stream=stream)
        logging.getLogger("jobhunt.test").info("hello")
        assert "hello" in stream.getvalue()
