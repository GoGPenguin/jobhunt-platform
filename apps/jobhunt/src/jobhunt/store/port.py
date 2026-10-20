"""The JobStore port, its result types, and the rules every implementation shares.

`plan_upsert` (how a sighting changes a stored job) and `group_postings` (which jobs are one
posting) are plain functions used by both the in-memory and the Postgres store, so the two
cannot drift apart. See spec 04 and decision 0017.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from jobhunt.domain.dead_letter import BuildResult, DeadLetter
from jobhunt.domain.job import Job, ParserInfo
from jobhunt.sources.raw import RawPayload
from jobhunt.store.fingerprint import fingerprint

JobStatus = Literal["new", "updated", "unchanged"]
# Ignored when deciding whether a job changed: fields that differ between sightings of the
# same job, and `extra`, which core logic never reads (spec 01) and which holds per-sighting
# details such as the alert-email kind (decision 0022).
_NOT_CONTENT = frozenset({"collected_at", "raw_ref", "parser", "extra"})


@dataclass(frozen=True)
class StoredJob:
    job: Job
    fingerprint: str
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime

    @property
    def countries(self) -> frozenset[str]:
        return frozenset(loc.country for loc in self.job.locations if loc.country)


@dataclass(frozen=True)
class Posting:
    """Jobs from one or more sources that are the same job."""

    fingerprint: str
    countries: frozenset[str]
    jobs: tuple[StoredJob, ...]

    @property
    def first_seen_at(self) -> datetime:
        return min(j.first_seen_at for j in self.jobs)

    @property
    def representative(self) -> StoredJob:
        """The job to show: one with a description first, then the earliest seen."""

        def rank(j: StoredJob) -> tuple[bool, datetime, str, str]:
            return (j.job.description == "", j.first_seen_at, j.job.source, j.job.external_id)

        return min(self.jobs, key=rank)


@dataclass(frozen=True)
class StoreResult:
    raw_new: bool
    statuses: Mapping[tuple[str, str], JobStatus]  # (source, external_id) -> status
    dead_letters_added: int

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(self.statuses.values()))


@dataclass(frozen=True)
class CollectionRun:
    started_at: datetime
    finished_at: datetime
    ok: bool
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class DigestBusyError(RuntimeError):
    """Another digest is being composed or sent right now."""


class JobStore(Protocol):
    def known_raw_refs(self, raw_refs: Iterable[str]) -> set[str]: ...
    def store(self, payload: RawPayload, result: BuildResult) -> StoreResult:
        """Store a raw payload and its build_jobs result atomically. Idempotent."""
        ...

    def get_job(self, source: str, external_id: str) -> StoredJob | None: ...
    def new_postings(self, since: datetime) -> list[Posting]:
        """Postings first seen after `since`, newest first."""
        ...

    def raw_payloads(self) -> Iterator[RawPayload]:
        """All stored raw payloads, oldest first (for reparse)."""
        ...

    def prune_raw(self, older_than: datetime) -> int:
        """Delete raw payloads fetched before `older_than`; returns how many."""
        ...

    def dead_letter_count(self) -> int: ...

    # Notifications (spec 05)
    def unsent_postings(self) -> list[Posting]:
        """Postings none of whose jobs was in a sent digest, newest first."""
        ...

    def mark_sent(
        self, postings: Sequence[Posting], *, sent_at: datetime, telegram_message_ids: Sequence[int]
    ) -> int:
        """Record a sent digest and every job of its postings, atomically; returns its id."""
        ...

    def postings_since(self, since: datetime) -> list[tuple[Posting, bool]]:
        """Postings first seen after `since`, newest first, with whether they were sent."""
        ...

    def digest_lock(self) -> AbstractContextManager[None]:
        """Exclusive while choosing, sending and marking a digest; DigestBusyError if taken."""
        ...

    def record_collection_run(self, run: CollectionRun) -> None: ...
    def last_collection_run(self) -> CollectionRun | None: ...


def plan_upsert(existing: StoredJob | None, job: Job) -> tuple[StoredJob, JobStatus]:
    """How a new sighting of `job` changes what is stored. Timestamps come from collected_at.

    - first_seen_at only moves earlier, last_seen_at only later.
    - Output from an older version of the same parser never replaces newer output.
    - Same content (ignoring collected_at, raw_ref, parser, extra): the first sighting's data
      is kept.
    """
    seen = job.collected_at
    if existing is None:
        return StoredJob(job, fingerprint(job.company, job.title), seen, seen, seen), "new"
    first = min(existing.first_seen_at, seen)
    last = max(existing.last_seen_at, seen)
    if _is_older_parser(job, existing.job):
        return replace(existing, first_seen_at=first, last_seen_at=last), "unchanged"
    if _content(job) == _content(existing.job):
        kept = existing.job.model_copy(update={"parser": _newer_parser(job, existing.job)})
        return replace(existing, job=kept, first_seen_at=first, last_seen_at=last), "unchanged"
    return StoredJob(job, fingerprint(job.company, job.title), first, last, seen), "updated"


def _newer_parser(a: Job, b: Job) -> ParserInfo:
    return b.parser if _is_older_parser(a, b) else a.parser


def _is_older_parser(new: Job, stored: Job) -> bool:
    same_parser = new.parser.name == stored.parser.name
    return same_parser and _semver(new.parser.version) < _semver(stored.parser.version)


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _content(job: Job) -> dict[str, object]:
    return job.model_dump(mode="json", exclude=set(_NOT_CONTENT))


def group_postings(jobs: Iterable[StoredJob]) -> list[Posting]:
    """Same fingerprint and no conflicting countries. A job without a country joins only when
    exactly one country group exists; otherwise it stays its own posting (decision 0017)."""
    by_fingerprint: dict[str, list[StoredJob]] = defaultdict(list)
    for stored in jobs:
        by_fingerprint[stored.fingerprint].append(stored)
    postings: list[Posting] = []
    for key, members in by_fingerprint.items():
        by_country: dict[frozenset[str], list[StoredJob]] = defaultdict(list)
        no_country: list[StoredJob] = []
        for stored in members:
            (by_country[stored.countries] if stored.countries else no_country).append(stored)
        if len(by_country) == 1:
            next(iter(by_country.values())).extend(no_country)
            no_country = []
        groups = [*by_country.items(), *([(frozenset(), no_country)] if no_country else [])]
        postings += [Posting(key, countries, tuple(group)) for countries, group in groups]
    return postings


def newest_first(postings: Iterable[Posting]) -> list[Posting]:
    return sorted(postings, key=lambda p: (p.first_seen_at, p.fingerprint), reverse=True)


def is_sent(posting: Posting, notified: set[tuple[str, str]]) -> bool:
    return any((j.job.source, j.job.external_id) in notified for j in posting.jobs)


def select_new(postings: Iterable[Posting], since: datetime) -> list[Posting]:
    new = [p for p in postings if p.first_seen_at > since]
    return sorted(new, key=lambda p: (p.first_seen_at, p.fingerprint), reverse=True)


def dead_letter_key(letter: DeadLetter) -> str:
    """Identity of a dead letter, so storing the same payload twice adds it once."""
    identity = {
        "raw_ref": letter.raw_ref,
        "parser": letter.parser.model_dump(),
        "record": letter.record,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
