"""Read-only IMAP transport for the Gmail alert label. See spec 02 F4, plan 02A task 4.

Only these commands are ever sent: LOGIN, EXAMINE (read-only open), UID SEARCH, UID FETCH with
BODY.PEEK[...] (does not set \\Seen), LOGOUT. Messages are never marked read, moved or deleted.

With `known` (the store's known_raw_refs), Message-ID headers are fetched first and only emails
not stored yet are fetched in full (spec 04, "Only-new mail").
"""

import imaplib
import logging
import re
import ssl
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any, Protocol

from jobhunt.credentials import ImapCredentials
from jobhunt.sources.config import ImapSettings
from jobhunt.sources.raw import RawPayload, email_origin, message_id, raw_ref_for

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
_HEADERS_ONLY = "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
_UID = re.compile(rb"\bUID (\d+)")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class TransportError(RuntimeError):
    """Fetching failed. The message never contains credentials."""


class ImapClient(Protocol):
    """The part of imaplib.IMAP4 this transport uses."""

    def login(self, user: str, password: str) -> tuple[str, list[Any]]: ...
    def select(self, mailbox: str = ..., readonly: bool = ...) -> tuple[str, list[Any]]: ...
    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]: ...
    def logout(self) -> tuple[str, list[Any]]: ...


def connect_ssl(host: str, port: int) -> ImapClient:
    return imaplib.IMAP4_SSL(
        host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SECONDS
    )


def fetch_emails(
    settings: ImapSettings,
    credentials: ImapCredentials,
    *,
    since: date,
    now: Callable[[], datetime],
    connect: Callable[[str, int], ImapClient] = connect_ssl,
    max_messages: int = 500,
    batch_size: int = 50,
    known: Callable[[Iterable[str]], set[str]] | None = None,
) -> list[RawPayload]:
    """Redacted raw payloads for messages under the label received since `since` (a day;
    IMAP SINCE has day granularity). Keeps the newest `max_messages` if there are more.
    With `known`, emails whose raw_ref it reports are skipped without fetching their bodies."""
    if not settings.label.isascii():
        raise TransportError(f"label {settings.label!r}: only ASCII label names are supported")
    client = _login(connect, settings, credentials)
    try:
        status, _ = client.select(_quote(settings.label), readonly=True)  # EXAMINE
        if status != "OK":
            raise TransportError(f"label {settings.label!r} not found in {credentials.user}")
        uids = _search_since(client, since)
        if len(uids) > max_messages:
            log.warning(
                "%d messages since %s; keeping the newest %d", len(uids), since, max_messages
            )
            uids = uids[-max_messages:]
        if known is not None:
            uids = _unknown(client, uids, known, batch_size)
        fetched_at = now()
        return [
            RawPayload.from_email(body, fetched_at=fetched_at)
            for start in range(0, len(uids), batch_size)
            for body in _fetch(client, uids[start : start + batch_size])
        ]
    finally:
        client.logout()


def _login(
    connect: Callable[[str, int], ImapClient], settings: ImapSettings, creds: ImapCredentials
) -> ImapClient:
    try:
        client = connect(settings.host, settings.port)
        client.login(creds.user, creds.password.get_secret_value())
    except imaplib.IMAP4.error as exc:
        raise TransportError(
            f"IMAP login to {settings.host} as {creds.user} failed ({exc}). Check IMAP is enabled "
            "in Gmail and that JOBHUNT_IMAP_APP_PASSWORD is an app password, not your account "
            "password."
        ) from None
    except OSError as exc:
        raise TransportError(f"cannot reach {settings.host}:{settings.port}: {exc}") from None
    return client


def _search_since(client: ImapClient, since: date) -> list[str]:
    day = f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}"  # locale-independent
    status, data = client.uid("SEARCH", "SINCE", day)
    if status != "OK":
        raise TransportError(f"IMAP search failed: {status}")
    return data[0].decode().split() if data and data[0] else []


def _fetch(client: ImapClient, uids: list[str], spec: str = "(BODY.PEEK[])") -> list[bytes]:
    return [body for _, body in _fetch_by_uid(client, uids, spec)]


def _fetch_by_uid(client: ImapClient, uids: list[str], spec: str) -> list[tuple[str, bytes]]:
    status, data = client.uid("FETCH", ",".join(uids), spec)
    if status != "OK":
        raise TransportError(f"IMAP fetch failed: {status}")
    items = [item for item in data if isinstance(item, tuple)]
    return [(m.group(1).decode() if (m := _UID.search(head)) else "", body) for head, body in items]


def _unknown(
    client: ImapClient, uids: list[str], known: Callable[[Iterable[str]], set[str]], batch: int
) -> list[str]:
    """UIDs of emails not stored yet, judged by Message-ID headers only."""
    refs: dict[str, str | None] = {}  # uid -> raw_ref, None when the email has no Message-ID
    for start in range(0, len(uids), batch):
        for uid, headers in _fetch_by_uid(client, uids[start : start + batch], _HEADERS_ONLY):
            found = message_id(headers)
            refs[uid] = raw_ref_for(email_origin(found, b"")) if found else None
    stored = known(ref for ref in refs.values() if ref)
    new = [uid for uid in uids if refs.get(uid) is None or refs[uid] not in stored]
    log.info("%d of %d emails are new", len(new), len(uids))
    return new


def _quote(mailbox: str) -> str:
    return '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'
