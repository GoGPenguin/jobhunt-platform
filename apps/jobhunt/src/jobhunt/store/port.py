"""The JobStore port, its result types, and the rules every implementation shares.

`plan_upsert` (how a sighting changes a stored job) and `group_postings` (which jobs are one
posting) are plain functions used by both the in-memory and the Postgres store, so the two
cannot drift apart. See spec 04 and decision 0017.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol

from jobhunt.domain.dead_letter import BuildResult, DeadLetter
from jobhunt.domain.job import Job, ParserInfo
from jobhunt.sources.raw import RawPayload
from jobhunt.store.fingerprint import fingerprint

JobStatus = Literal["new", "updated", "unchanged"]
# Fields that differ between sightings of the same job; ignored when comparing content.
_SIGHTING_FIELDS = frozenset({"collected_at", "raw_ref", "parser"})


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


def plan_upsert(existing: StoredJob | None, job: Job) -> tuple[StoredJob, JobStatus]:
    """How a new sighting of `job` changes what is stored. Timestamps come from collected_at.

    - first_seen_at only moves earlier, last_seen_at only later.
    - Output from an older version of the same parser never replaces newer output.
    - Same content (ignoring collected_at, raw_ref, parser): the first sighting's data is kept.
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
    return job.model_dump(mode="json", exclude=set(_SIGHTING_FIELDS))


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
