"""Routing, parsing and storing a batch of raw emails (plan 04 task 6, decision 0021)."""

import io
import json
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from jobhunt.domain.job import ParserInfo
from jobhunt.pipeline import process_payloads
from jobhunt.sources.config import EmailSection, ImapSettings, load_sources
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY, ParserPlugin
from jobhunt.store.memory import MemoryJobStore

REPO = Path(__file__).resolve().parents[3]
LINKEDIN = Path(__file__).parent / "fixtures" / "sources" / "linkedin-email"
NOW = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)


def email_section() -> EmailSection:
    config = load_sources(REPO / "config" / "sources.sample.yaml", known_parsers=REGISTRY.names())
    assert config.email is not None
    return config.email


def linkedin(case: str) -> RawPayload:
    raw = (LINKEDIN / case / "input.eml").read_bytes()
    return RawPayload.from_email(raw, fetched_at=NOW)


def other_email(sender: str, auth: str | None) -> RawPayload:
    msg = EmailMessage()
    msg["From"] = sender
    msg["Message-ID"] = f"<{sender.split('@')[0]}@example.com>"
    if auth:
        msg["Authentication-Results"] = auth
    msg.set_content("hello\n")
    return RawPayload.from_email(msg.as_bytes(), fetched_at=NOW)


Lines = list[dict[str, Any]]


def run(payloads: list[RawPayload], store: MemoryJobStore | None, **kwargs: Any) -> Lines:
    out = io.StringIO()
    process_payloads(
        payloads, email_section(), accepted=None, now=lambda: NOW, out=out, store=store, **kwargs
    )
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_stores_and_prints_new_jobs() -> None:
    store = MemoryJobStore()
    lines = run([linkedin("similar-jobs"), linkedin("recommendations")], store)
    jobs = [line for line in lines if line["type"] == "job"]
    assert len(jobs) == 11
    assert {job["status"] for job in jobs} == {"new"}
    summary = lines[-1]
    assert (summary["new"], summary["updated"], summary["unchanged"]) == (11, 0, 0)
    assert summary["raw_stored"] == 2


def test_rerun_prints_summary_only() -> None:
    store = MemoryJobStore()
    payloads = [linkedin("similar-jobs")]
    run(payloads, store)
    lines = run(payloads, store)
    assert [line["type"] for line in lines] == ["summary"]
    assert (lines[-1]["new"], lines[-1]["unchanged"], lines[-1]["raw_stored"]) == (0, 6, 0)


def test_unknown_sender_raw_is_kept_for_later_reparse() -> None:
    store = MemoryJobStore()
    promo = other_email("deals@shop.example", "mx.google.com; dkim=pass header.i=@shop.example")
    lines = run([promo], store)
    assert lines[-1]["unknown_sender"] == 1
    assert store.known_raw_refs([promo.raw_ref]) == {promo.raw_ref}


def test_unauthenticated_email_is_never_stored() -> None:
    store = MemoryJobStore()
    fail = "mx.google.com; dkim=fail header.i=@linkedin.com"
    forged = other_email("jobs-noreply@linkedin.com", fail)
    lines = run([forged], store)
    assert lines[-1]["unauthenticated"] == 1
    assert store.known_raw_refs([forged.raw_ref]) == set()


def test_parser_crash_still_stores_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(payload: RawPayload) -> list[dict[str, Any]]:
        raise RuntimeError("parser bug")

    crashing = ParserPlugin(info=ParserInfo(name="linkedin-email", version="9.9.9"), parse=boom)
    monkeypatch.setitem(REGISTRY._plugins, "linkedin-email", crashing)
    store = MemoryJobStore()
    payload = linkedin("similar-jobs")
    lines = run([payload], store)
    assert lines[-1]["parser_errors"] == 1
    assert store.known_raw_refs([payload.raw_ref]) == {payload.raw_ref}


def test_dry_run_without_store_keeps_phase_a_output() -> None:
    lines = run([linkedin("similar-jobs"), linkedin("similar-jobs")], store=None)
    assert lines[-1]["jobs"] == 6
    assert lines[-1]["duplicates"] == 6
    assert "status" not in lines[0]


def test_source_filter_for_reparse() -> None:
    store = MemoryJobStore()
    lines = run([linkedin("similar-jobs")], store, only_source="some-other-source")
    assert lines[-1]["new"] == 0
    assert lines[-1]["skipped_by_filter"] == 1


def test_disabled_source_counted() -> None:
    section = email_section()
    disabled = EmailSection(
        imap=ImapSettings(label="jobhunt"),
        sources=tuple(s.model_copy(update={"enabled": False}) for s in section.sources),
    )
    store = MemoryJobStore()
    out = io.StringIO()
    payload = linkedin("similar-jobs")
    process_payloads([payload], disabled, accepted=None, now=lambda: NOW, out=out, store=store)
    summary = json.loads(out.getvalue().splitlines()[-1])
    assert summary["disabled"] == 1
    assert store.known_raw_refs([payload.raw_ref]) == {payload.raw_ref}
