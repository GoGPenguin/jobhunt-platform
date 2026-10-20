"""Contract tests every JobStore must pass (spec 04: D2, D3, D4, D5, D8, D9)."""

import json
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from jobhunt.domain.dead_letter import BuildResult, build_jobs
from jobhunt.domain.job import ParserInfo
from jobhunt.sources.raw import RawPayload
from jobhunt.store.port import CollectionRun, DigestBusyError, JobStore

FIXTURE = Path(__file__).parent.parent / "fixtures" / "jobs" / "greenhouse_style.json"
T0 = datetime(2026, 10, 18, 1, 0, tzinfo=UTC)
V1 = ParserInfo(name="test-parser", version="1.0.0")


def payload(n: int, fetched_at: datetime = T0) -> RawPayload:
    msg = EmailMessage()
    msg["From"] = "alerts@example.com"
    msg["Message-ID"] = f"<{n}@example.com>"
    msg.set_content(f"email {n}\n")
    return RawPayload.from_email(msg.as_bytes(), fetched_at=fetched_at)


def record(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for key in ("source", "raw_ref", "parser"):
        del data[key]
    return {**data, **changes}


def result(raw: RawPayload, *records: dict[str, Any], parser: ParserInfo = V1) -> BuildResult:
    return build_jobs(
        records,
        source="test-source",
        parser=parser,
        raw_ref=raw.raw_ref,
        now=lambda: raw.fetched_at,
    )


def at(t: datetime) -> str:
    return t.isoformat()


# Ingest and idempotency


def test_store_new_payload(store: JobStore) -> None:
    raw = payload(1)
    outcome = store.store(raw, result(raw, record(external_id="a"), record(external_id="b")))
    assert outcome.raw_new
    assert outcome.counts == {"new": 2}
    assert store.known_raw_refs([raw.raw_ref, "raw/email/other"]) == {raw.raw_ref}
    stored = store.get_job("test-source", "a")
    assert stored is not None
    assert stored.job.external_id == "a"
    collected = datetime.fromisoformat(record()["collected_at"])
    assert stored.first_seen_at == stored.last_seen_at == collected


def test_storing_twice_changes_nothing(store: JobStore) -> None:
    raw = payload(1)
    batch = result(raw, record(external_id="a"), record(external_id="bad", title=""))
    first = store.store(raw, batch)
    assert first.dead_letters_added == 1
    again = store.store(raw, batch)
    assert not again.raw_new
    assert again.counts == {"unchanged": 1}
    assert again.dead_letters_added == 0
    assert store.dead_letter_count() == 1


def test_same_job_in_two_emails(store: JobStore) -> None:
    first_raw, second_raw = payload(1), payload(2, T0 + timedelta(days=1))
    store.store(first_raw, result(first_raw, record(collected_at=at(T0))))
    later = T0 + timedelta(days=1)
    outcome = store.store(second_raw, result(second_raw, record(collected_at=at(later))))
    assert outcome.counts == {"unchanged": 1}
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert (stored.first_seen_at, stored.last_seen_at) == (T0, later)
    assert stored.job.raw_ref == first_raw.raw_ref  # content unchanged: first sighting kept


def test_extra_alone_is_not_a_change(store: JobStore) -> None:
    first_raw, second_raw = payload(1), payload(2)
    store.store(first_raw, result(first_raw, record(extra={"email_kind": "Viewed Jobs"})))
    other_email = record(extra={"email_kind": "Jobs You Might Be Interested In", "badges": ["x"]})
    outcome = store.store(second_raw, result(second_raw, other_email))
    assert outcome.counts == {"unchanged": 1}
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert stored.job.extra == {"email_kind": "Viewed Jobs"}  # first sighting kept


def test_last_seen_never_goes_back(store: JobStore) -> None:
    late_raw, early_raw = payload(1), payload(2)
    late = T0 + timedelta(days=2)
    store.store(late_raw, result(late_raw, record(collected_at=at(late))))
    store.store(early_raw, result(early_raw, record(collected_at=at(T0))))
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert (stored.first_seen_at, stored.last_seen_at) == (T0, late)


# Updates and the parser-version guard (D3)


def test_changed_content_updates(store: JobStore) -> None:
    first_raw, second_raw = payload(1), payload(2)
    store.store(first_raw, result(first_raw, record(collected_at=at(T0))))
    later = T0 + timedelta(hours=5)
    changed = record(collected_at=at(later), title="Staff Platform Engineer")
    outcome = store.store(second_raw, result(second_raw, changed))
    assert outcome.counts == {"updated": 1}
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert stored.job.title == "Staff Platform Engineer"
    assert (stored.first_seen_at, stored.updated_at) == (T0, later)


def test_older_parser_never_overwrites(store: JobStore) -> None:
    newer, older = ParserInfo(name="test-parser", version="1.10.0"), V1
    first_raw, second_raw = payload(1), payload(2)
    store.store(first_raw, result(first_raw, record(), parser=newer))
    outcome = store.store(second_raw, result(second_raw, record(title="Old output"), parser=older))
    assert outcome.counts == {"unchanged": 1}
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert stored.job.title == "Platform Engineer"
    assert stored.job.parser == newer


def test_newer_parser_overwrites(store: JobStore) -> None:
    first_raw, second_raw = payload(1), payload(2)
    store.store(first_raw, result(first_raw, record()))
    v2 = ParserInfo(name="test-parser", version="2.0.0")
    outcome = store.store(second_raw, result(second_raw, record(title="Better parse"), parser=v2))
    assert outcome.counts == {"updated": 1}
    stored = store.get_job("test-source", "4012345")
    assert stored is not None
    assert stored.job.parser == v2


# Atomicity (D5)


def test_failed_store_stores_nothing(store: JobStore) -> None:
    raw = payload(1)
    good = result(raw, record(external_id="a"))
    jobs = (*good.jobs, "not a job")
    broken = BuildResult(jobs=jobs, dead_letters=(), dropped_languages={})  # type: ignore[arg-type]
    with pytest.raises((TypeError, AttributeError)):
        store.store(raw, broken)
    assert store.known_raw_refs([raw.raw_ref]) == set()
    assert store.get_job("test-source", "a") is None


# Postings (D4)


def test_postings_merge_across_sources(store: JobStore) -> None:
    linkedin_raw, board_raw = payload(1), payload(2)
    alert = record(
        external_id="li-1",
        company="Lumen Robotics Pte. Ltd.",
        title="Senior DevOps Engineer",
        locations=[{"city": "Singapore"}],
        description="",
    )
    linkedin = build_jobs([alert], source="linkedin-email", parser=V1, raw_ref=linkedin_raw.raw_ref)
    board = build_jobs(
        [record(external_id="gh-1", company="Lumen Robotics", title="Senior DevOps Engineer",
                collected_at=at(T0 + timedelta(days=1)))],
        source="greenhouse:lumen-robotics", parser=V1, raw_ref=board_raw.raw_ref,
    )  # fmt: skip
    store.store(linkedin_raw, linkedin)
    store.store(board_raw, board)
    [posting] = store.new_postings(since=T0 - timedelta(days=1))
    assert {(j.job.source, j.job.external_id) for j in posting.jobs} == {
        ("linkedin-email", "li-1"),
        ("greenhouse:lumen-robotics", "gh-1"),
    }
    assert posting.countries == frozenset({"SG"})
    assert posting.representative.job.external_id == "gh-1"  # has a description


def test_postings_split_by_country(store: JobStore) -> None:
    raw = payload(1)
    store.store(raw, result(raw,
        record(external_id="vn", locations=[{"city": "Hanoi", "country": "VN"}]),
        record(external_id="jp", locations=[{"city": "Tokyo", "country": "JP"}]),
        record(external_id="none", locations=[{"city": "Somewhere"}]),
    ))  # fmt: skip
    postings = store.new_postings(since=T0 - timedelta(days=30))
    grouped = sorted(tuple(sorted(j.job.external_id for j in p.jobs)) for p in postings)
    assert grouped == [("jp",), ("none",), ("vn",)]  # ambiguous: no-country job stays alone


def test_new_postings_since_and_order(store: JobStore) -> None:
    raw = payload(1)
    store.store(raw, result(raw,
        record(external_id="old", title="Old Job", collected_at=at(T0)),
        record(external_id="new", title="New Job", collected_at=at(T0 + timedelta(days=2))),
        record(external_id="newer", title="Newer Job", collected_at=at(T0 + timedelta(days=3))),
    ))  # fmt: skip
    postings = store.new_postings(since=T0 + timedelta(days=1))
    assert [p.representative.job.external_id for p in postings] == ["newer", "new"]


def test_posting_not_new_again_when_another_source_joins(store: JobStore) -> None:
    first_raw, second_raw = payload(1), payload(2)
    store.store(first_raw, result(first_raw, record(collected_at=at(T0))))
    joining = build_jobs(
        [record(external_id="other", collected_at=at(T0 + timedelta(days=3)))],
        source="another-source", parser=V1, raw_ref=second_raw.raw_ref,
    )  # fmt: skip
    store.store(second_raw, joining)
    assert store.new_postings(since=T0 + timedelta(days=1)) == []


# Raw payloads and retention (D8)


def test_raw_payloads_round_trip(store: JobStore) -> None:
    first, second = payload(1, T0), payload(2, T0 + timedelta(days=1))
    store.store(second, result(second))
    store.store(first, result(first))
    assert list(store.raw_payloads()) == [first, second]  # oldest first


def test_prune_raw_keeps_jobs(store: JobStore) -> None:
    old, recent = payload(1, T0 - timedelta(days=400)), payload(2, T0)
    store.store(old, result(old, record(external_id="from-old")))
    store.store(recent, result(recent, record(external_id="from-recent")))
    assert store.prune_raw(older_than=T0 - timedelta(days=365)) == 1
    assert store.known_raw_refs([old.raw_ref, recent.raw_ref]) == {recent.raw_ref}
    kept = store.get_job("test-source", "from-old")
    assert kept is not None
    assert kept.job.raw_ref == old.raw_ref  # reference kept, payload gone


# Notifications and collection runs (spec 05)


def store_jobs(
    store: JobStore, n: int, *records: dict[str, Any], source: str = "test-source"
) -> None:
    raw = payload(n)
    store.store(raw, build_jobs(records, source=source, parser=V1, raw_ref=raw.raw_ref))


def test_unsent_postings_then_mark_sent(store: JobStore) -> None:
    store_jobs(store, 1,
        record(external_id="a", title="Job A", collected_at=at(T0)),
        record(external_id="b", title="Job B", collected_at=at(T0 + timedelta(hours=1))),
    )  # fmt: skip
    unsent = store.unsent_postings()
    assert [p.representative.job.external_id for p in unsent] == ["b", "a"]  # newest first
    digest_id = store.mark_sent(unsent, sent_at=T0 + timedelta(days=1), telegram_message_ids=[7])
    assert digest_id > 0
    assert store.unsent_postings() == []


def test_joining_job_does_not_revive_a_sent_posting(store: JobStore) -> None:
    store_jobs(store, 1, record(external_id="first"))
    store.mark_sent(store.unsent_postings(), sent_at=T0, telegram_message_ids=[1])
    store_jobs(store, 2, record(external_id="second"), source="another-source")
    assert store.unsent_postings() == []


def test_mark_sent_twice_is_harmless(store: JobStore) -> None:
    store_jobs(store, 1, record(external_id="a"))
    unsent = store.unsent_postings()
    store.mark_sent(unsent, sent_at=T0, telegram_message_ids=[1])
    store.mark_sent(unsent, sent_at=T0, telegram_message_ids=[2])
    assert store.unsent_postings() == []


def test_postings_since_with_sent_flag(store: JobStore) -> None:
    store_jobs(store, 1,
        record(external_id="sent", title="Sent Job", collected_at=at(T0)),
        record(external_id="new", title="New Job", collected_at=at(T0 + timedelta(hours=2))),
    )  # fmt: skip
    sent = [p for p in store.unsent_postings() if p.representative.job.external_id == "sent"]
    store.mark_sent(sent, sent_at=T0, telegram_message_ids=[1])
    listed = store.postings_since(T0 - timedelta(days=1))
    assert [(p.representative.job.external_id, was_sent) for p, was_sent in listed] == [
        ("new", False),
        ("sent", True),
    ]


def test_digest_lock_is_exclusive(store: JobStore) -> None:
    with store.digest_lock(), pytest.raises(DigestBusyError), store.digest_lock():
        pass
    with store.digest_lock():  # released again
        pass


def test_collection_runs(store: JobStore) -> None:
    assert store.last_collection_run() is None
    ok = CollectionRun(started_at=T0, finished_at=T0 + timedelta(seconds=5), ok=True,
                       summary={"emails": 4, "new": 19}, error=None)  # fmt: skip
    failed = CollectionRun(started_at=T0 + timedelta(hours=1),
                           finished_at=T0 + timedelta(hours=1, seconds=2), ok=False, summary={},
                           error="IMAP login failed")  # fmt: skip
    store.record_collection_run(ok)
    store.record_collection_run(failed)
    assert store.last_collection_run() == failed
