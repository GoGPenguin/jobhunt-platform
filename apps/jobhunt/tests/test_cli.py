import imaplib
import json
import shutil
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from jobhunt.cli import main, parse_since
from jobhunt.credentials import read_secrets_file
from jobhunt.domain.job import ParserInfo
from jobhunt.sources.registry import REGISTRY, ParserPlugin
from jobhunt.store.settings import DB_PASSWORD_KEYS

REPO = Path(__file__).resolve().parents[3]
LINKEDIN = Path(__file__).parent / "fixtures" / "sources" / "linkedin-email"
EMLS = [str(LINKEDIN / case / "input.eml") for case in ("similar-jobs", "recommendations")]
NOW = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
FAKE_PASSWORD = "zq9fakeapppass7x"  # noqa: S105


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    shutil.copy(REPO / "config" / "sources.sample.yaml", tmp_path / "sources.yaml")
    (tmp_path / "preferences.yaml").write_text("languages:\n  postings: [vi, en]\n")
    return tmp_path


Capture = pytest.CaptureFixture[str]


def cmd(config_dir: Path, *args: str) -> list[str]:
    return ["collect", "email", "--config-dir", str(config_dir), *args]


def run(argv: list[str], capsys: Capture, **kwargs: Any) -> tuple[int, list[dict[str, Any]], str]:
    code = main(argv, now=lambda: NOW, **kwargs)
    out, err = capsys.readouterr()
    return code, [json.loads(line) for line in out.splitlines()], err


def summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    assert lines[-1]["type"] == "summary"
    return lines[-1]


def test_eml_files(config_dir: Path, capsys: Capture) -> None:
    code, lines, _ = run(cmd(config_dir, "--eml", *EMLS), capsys)
    assert code == 0
    jobs = [line for line in lines if line["type"] == "job"]
    assert len(jobs) == 11
    assert jobs[0]["source"] == "linkedin-email"
    assert summary(lines) | {"type": "summary"} == {
        "type": "summary", "emails": 2, "routed": 2, "unknown_sender": 0, "unauthenticated": 0,
        "disabled": 0, "jobs": 11, "duplicates": 0, "dead_letters": 0, "dropped_languages": {},
        "parser_errors": 0, "unknown_senders": {},
    }  # fmt: skip


def test_language_filter_from_preferences(config_dir: Path, capsys: Capture) -> None:
    (config_dir / "preferences.yaml").write_text("languages:\n  postings: [ja]\n")
    _, lines, _ = run(cmd(config_dir, "--eml", *EMLS), capsys)
    # Only the Vietnamese title is detected; "unknown" jobs are always kept.
    assert summary(lines)["dropped_languages"] == {"vi": 1}
    assert summary(lines)["jobs"] == 10


def test_same_job_in_two_emails_is_printed_once(config_dir: Path, capsys: Capture) -> None:
    _, lines, _ = run(cmd(config_dir, "--eml", EMLS[0], EMLS[0]), capsys)
    assert summary(lines)["jobs"] == 6
    assert summary(lines)["duplicates"] == 6


def test_unknown_sender_counted(config_dir: Path, tmp_path: Path, capsys: Capture) -> None:
    msg = EmailMessage()
    msg["From"] = "Deals <deals@shop.example>"
    msg["Message-ID"] = "<promo@shop.example>"
    msg.set_content("Big sale\n")
    promo = tmp_path / "promo.eml"
    promo.write_bytes(msg.as_bytes())
    code, lines, _ = run(cmd(config_dir, "--eml", str(promo)), capsys)
    assert code == 0
    assert summary(lines)["unknown_sender"] == 1
    assert summary(lines)["unknown_senders"] == {"shop.example": 1}


def test_parser_crash_does_not_stop_run(
    config_dir: Path, capsys: Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(payload: object) -> list[dict[str, Any]]:
        raise RuntimeError("parser bug")

    crashing = ParserPlugin(info=ParserInfo(name="linkedin-email", version="9.9.9"), parse=boom)
    monkeypatch.setitem(REGISTRY._plugins, "linkedin-email", crashing)
    code, lines, err = run(cmd(config_dir, "--eml", *EMLS), capsys)
    assert code == 0
    assert summary(lines)["parser_errors"] == 2
    assert "parser bug" in err


def test_missing_sources_file(tmp_path: Path, capsys: Capture) -> None:
    code, _, err = run(cmd(tmp_path, "--eml", *EMLS), capsys)
    assert code == 2
    assert "sources.yaml: not found" in err


class FakeImap:
    def __init__(self, messages: list[bytes]) -> None:
        self.messages = messages

    def login(self, user: str, password: str) -> tuple[str, list[Any]]:
        if password != FAKE_PASSWORD:
            raise imaplib.IMAP4.error(f"[AUTHENTICATIONFAILED] bad login {password}")
        return "OK", []

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[Any]]:
        assert readonly
        return "OK", [b"1"]

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        if command == "SEARCH":
            return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]
        return "OK", [(b"1 (BODY[] {1}", self.messages[int(u) - 1]) for u in args[0].split(",")]

    def logout(self) -> tuple[str, list[Any]]:
        return "BYE", []


def test_imap_mode(config_dir: Path, capsys: Capture) -> None:
    (config_dir / "secrets.env").write_text(
        f"JOBHUNT_IMAP_USER=me@example.com\nJOBHUNT_IMAP_APP_PASSWORD={FAKE_PASSWORD}\n"
    )
    (config_dir / "secrets.env").chmod(0o600)
    fake = FakeImap([Path(EMLS[0]).read_bytes()])
    code, lines, _ = run(
        cmd(config_dir, "--since", "2026-10-17"),
        capsys,
        connect=lambda host, port: fake,
        env={},
    )
    assert code == 0
    assert summary(lines)["jobs"] == 6


def test_imap_login_failure_never_prints_password(config_dir: Path, capsys: Capture) -> None:
    env = {"JOBHUNT_IMAP_USER": "me@example.com", "JOBHUNT_IMAP_APP_PASSWORD": "wrong-pass-123"}
    code, _, err = run(
        cmd(config_dir),
        capsys,
        connect=lambda host, port: FakeImap([]),
        env=env,
    )
    assert code == 3
    assert "app password" in err
    assert "wrong-pass-123" not in err


@pytest.mark.parametrize(
    ("since", "expected"), [("3d", "2026-10-17"), ("2026-10-01", "2026-10-01")]
)
def test_since(since: str, expected: str) -> None:
    assert parse_since(since, today=NOW.date()).isoformat() == expected


def test_bad_since() -> None:
    with pytest.raises(ValueError, match="3d"):
        parse_since("yesterday", today=NOW.date())


def test_db_init_secrets_creates_passwords_without_printing(
    config_dir: Path, capsys: Capture
) -> None:
    code, _, err = run(["db", "init-secrets", "--config-dir", str(config_dir)], capsys)
    assert code == 0
    values = read_secrets_file(config_dir / "secrets.env")
    assert set(values) == set(DB_PASSWORD_KEYS)
    assert "JOBHUNT_DB_ADMIN_PASSWORD" in err
    assert not any(value in err for value in values.values())


def test_db_unreachable_exits_4_without_leaking_passwords(
    config_dir: Path, capsys: Capture
) -> None:
    run(["db", "init-secrets", "--config-dir", str(config_dir)], capsys)
    passwords = read_secrets_file(config_dir / "secrets.env").values()
    env = {"JOBHUNT_DB_PORT": "1"}  # nothing listens on port 1
    for action in ("bootstrap", "migrate"):
        code, _, err = run(["db", action, "--config-dir", str(config_dir)], capsys, env=env)
        assert code == 4
        assert "127.0.0.1:1" in err
        assert not any(p in err for p in passwords)


def test_db_missing_passwords(config_dir: Path, capsys: Capture) -> None:
    code, _, err = run(["db", "migrate", "--config-dir", str(config_dir)], capsys, env={})
    assert code == 2
    assert "JOBHUNT_DB_OWNER_PASSWORD" in err
