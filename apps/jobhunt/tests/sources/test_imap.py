import imaplib
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Any

import pytest
from pydantic import SecretStr

from jobhunt.credentials import ImapCredentials
from jobhunt.sources.config import ImapSettings
from jobhunt.sources.imap import TransportError, fetch_emails
from jobhunt.sources.raw import RawPayload

NOW = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
CREDS = ImapCredentials(user="me@example.com", password=SecretStr("zq9fakeapppass7x"))
SETTINGS = ImapSettings(label="jobhunt")


HEADERS_ONLY = "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"


def message(n: int, with_id: bool = True) -> bytes:
    msg = EmailMessage()
    msg["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    if with_id:
        msg["Message-ID"] = f"<{n}@linkedin.com>"
    msg["Subject"] = f"Alert {n}"
    msg.set_content(f"View job: https://www.linkedin.com/comm/jobs/view/{n}/?otpToken=SECRET\n")
    return msg.as_bytes()


class FakeImap:
    """Implements the imaplib calls the transport may use. Anything that could change the
    mailbox fails the test."""

    def __init__(self, messages: dict[int, bytes], labels: tuple[str, ...] = ("jobhunt",)) -> None:
        self.messages = messages
        self.labels = labels
        self.commands: list[str] = []
        self.logged_out = False

    def login(self, user: str, password: str) -> tuple[str, list[Any]]:
        self.commands.append(f"LOGIN {user}")
        if password != "zq9fakeapppass7x":  # noqa: S105
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"LOGIN completed"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[Any]]:
        if not readonly:
            pytest.fail(f"SELECT {mailbox} would open the mailbox read-write")
        self.commands.append(f"EXAMINE {mailbox}")
        if mailbox.strip('"') not in self.labels:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        self.commands.append(f"UID {command} {' '.join(args)}")
        if command == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self.messages)).encode()]
        if command == "FETCH":
            if args[1] not in ("(BODY.PEEK[])", HEADERS_ONLY):
                pytest.fail(f"FETCH {args[1]} would mark messages as read")
            data: list[Any] = []
            for uid in args[0].split(","):
                body = self.messages[int(uid)]
                if args[1] == HEADERS_ONLY:  # like Gmail: the requested header, then a blank line
                    lines = body.split(b"\n")
                    found = [ln for ln in lines if ln.lower().startswith(b"message-id:")]
                    body = b"".join(ln + b"\r\n" for ln in found) + b"\r\n"
                part = "BODY[HEADER.FIELDS (MESSAGE-ID)]" if args[1] == HEADERS_ONLY else "BODY[]"
                data += [(f"{uid} (UID {uid} {part} {{{len(body)}}}".encode(), body), b")"]
            return "OK", data
        pytest.fail(f"UID {command} is not a read-only command")

    def logout(self) -> tuple[str, list[Any]]:
        self.logged_out = True
        self.commands.append("LOGOUT")
        return "BYE", [b"LOGOUT completed"]

    def __getattr__(self, name: str) -> Any:
        pytest.fail(f"transport called imaplib.{name}(), which is not allowed")


def run(fake: FakeImap, **kwargs: Any) -> Any:
    return fetch_emails(
        SETTINGS,
        CREDS,
        since=date(2026, 10, 17),
        now=lambda: NOW,
        connect=lambda host, port: fake,
        **kwargs,
    )


def test_read_only_command_sequence() -> None:
    fake = FakeImap({1: message(1), 2: message(2)})
    payloads = run(fake)
    assert fake.commands == [
        "LOGIN me@example.com",
        'EXAMINE "jobhunt"',
        "UID SEARCH SINCE 17-Oct-2026",
        "UID FETCH 1,2 (BODY.PEEK[])",
        "LOGOUT",
    ]
    assert [p.origin for p in payloads] == ["email:<1@linkedin.com>", "email:<2@linkedin.com>"]


def test_payloads_are_redacted_and_timestamped() -> None:
    payload = run(FakeImap({7: message(7)}))[0]
    assert b"otpToken" not in payload.content
    assert b"/jobs/view/7/" in payload.content
    assert payload.fetched_at == NOW


def test_same_email_same_raw_ref_across_runs() -> None:
    first = run(FakeImap({1: message(1)}))
    second = run(FakeImap({1: message(1)}))
    assert [p.raw_ref for p in first] == [p.raw_ref for p in second]


def test_no_messages() -> None:
    fake = FakeImap({})
    assert run(fake) == []
    assert "LOGOUT" in fake.commands
    assert not any(c.startswith("UID FETCH") for c in fake.commands)


def test_fetches_in_batches() -> None:
    fake = FakeImap({n: message(n) for n in range(1, 121)})
    assert len(run(fake, batch_size=50)) == 120
    assert sum(c.startswith("UID FETCH") for c in fake.commands) == 3


def test_caps_messages_per_run_keeping_newest(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeImap({n: message(n) for n in range(1, 6)})
    with caplog.at_level(logging.WARNING):
        payloads = run(fake, max_messages=2)
    assert [p.origin for p in payloads] == ["email:<4@linkedin.com>", "email:<5@linkedin.com>"]
    assert "5 messages" in caplog.text


def test_missing_label() -> None:
    fake = FakeImap({1: message(1)}, labels=("other",))
    with pytest.raises(TransportError, match="label 'jobhunt'"):
        run(fake)
    assert fake.logged_out


def test_login_failure_hints_app_password_without_leaking_it() -> None:
    bad = ImapCredentials(user="me@example.com", password=SecretStr("wrong-pass-123"))
    fake = FakeImap({})
    with pytest.raises(TransportError, match="app password") as exc:
        fetch_emails(
            SETTINGS, bad, since=date(2026, 10, 17), now=lambda: NOW, connect=lambda h, p: fake
        )
    assert "wrong-pass-123" not in str(exc.value)


def test_label_with_space_is_quoted() -> None:
    fake = FakeImap({}, labels=("Job Alerts",))
    fetch_emails(
        ImapSettings(label="Job Alerts"), CREDS, since=date(2026, 10, 17), now=lambda: NOW,
        connect=lambda h, p: fake,
    )  # fmt: skip
    assert 'EXAMINE "Job Alerts"' in fake.commands


def test_non_ascii_label_rejected() -> None:
    with pytest.raises(TransportError, match="ASCII"):
        fetch_emails(
            ImapSettings(label="Việc làm"), CREDS, since=date(2026, 10, 17), now=lambda: NOW,
            connect=lambda h, p: FakeImap({}),
        )  # fmt: skip


# Only-new mail (spec 04, D7)


def known_after(*runs: list[RawPayload]) -> Callable[[Iterable[str]], set[str]]:
    stored = {p.raw_ref for run in runs for p in run}
    return lambda refs: {r for r in refs if r in stored}


def body_fetches(fake: FakeImap) -> list[str]:
    return [c for c in fake.commands if c.startswith("UID FETCH") and c.endswith("(BODY.PEEK[])")]


def test_second_run_fetches_headers_only() -> None:
    messages = {1: message(1), 2: message(2)}
    first = run(FakeImap(messages), known=known_after())
    fake = FakeImap(messages)
    assert run(fake, known=known_after(first)) == []
    assert "UID FETCH 1,2 " + HEADERS_ONLY in fake.commands
    assert body_fetches(fake) == []


def test_only_unknown_bodies_are_fetched() -> None:
    stored = run(FakeImap({1: message(1)}), known=known_after())
    fake = FakeImap({1: message(1), 2: message(2), 3: message(3)})
    payloads = run(fake, known=known_after(stored))
    assert [p.origin for p in payloads] == ["email:<2@linkedin.com>", "email:<3@linkedin.com>"]
    assert body_fetches(fake) == ["UID FETCH 2,3 (BODY.PEEK[])"]


def test_message_without_id_is_always_fetched() -> None:
    messages = {1: message(1, with_id=False)}
    first = run(FakeImap(messages), known=known_after())
    fake = FakeImap(messages)
    run(fake, known=known_after(first))
    assert body_fetches(fake) == ["UID FETCH 1 (BODY.PEEK[])"]


def test_precheck_raw_ref_matches_full_email() -> None:
    fake = FakeImap({5: message(5)})
    seen: list[str] = []

    def record_and_know_nothing(refs: Iterable[str]) -> set[str]:
        seen.extend(refs)
        return set()

    run(fake, known=record_and_know_nothing)
    full = RawPayload.from_email(message(5), fetched_at=NOW)
    assert seen == [full.raw_ref]
