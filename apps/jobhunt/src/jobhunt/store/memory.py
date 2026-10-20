"""In-memory JobStore for unit tests and dry runs. Same contract as the Postgres store."""

import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from types import TracebackType
from typing import Self

from jobhunt.domain.dead_letter import BuildResult, DeadLetter
from jobhunt.sources.raw import RawPayload
from jobhunt.store.port import (
    CollectionRun,
    DigestBusyError,
    JobStatus,
    Posting,
    StoredJob,
    StoreResult,
    dead_letter_key,
    group_postings,
    is_sent,
    newest_first,
    plan_upsert,
    select_new,
)


class MemoryJobStore:
    def __init__(self) -> None:
        self._raw: dict[str, RawPayload] = {}
        self._jobs: dict[tuple[str, str], StoredJob] = {}
        self._dead: dict[str, DeadLetter] = {}
        self._notified: dict[tuple[str, str], int] = {}  # job key -> digest id
        self._digests = 0
        self._runs: list[CollectionRun] = []
        self._digest_lock = threading.Lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def known_raw_refs(self, raw_refs: Iterable[str]) -> set[str]:
        return {ref for ref in raw_refs if ref in self._raw}

    def store(self, payload: RawPayload, result: BuildResult) -> StoreResult:
        # Work on copies and swap at the end, so a failure part-way stores nothing.
        raw, jobs, dead = dict(self._raw), dict(self._jobs), dict(self._dead)
        raw_new = payload.raw_ref not in raw
        raw.setdefault(payload.raw_ref, payload)
        statuses: dict[tuple[str, str], JobStatus] = {}
        for job in result.jobs:
            key = (job.source, job.external_id)
            jobs[key], status = plan_upsert(jobs.get(key), job)
            statuses[key] = "new" if statuses.get(key) == "new" else status
        added = 0
        for letter in result.dead_letters:
            letter_key = dead_letter_key(letter)
            if letter_key not in dead:
                dead[letter_key] = letter
                added += 1
        self._raw, self._jobs, self._dead = raw, jobs, dead
        return StoreResult(raw_new=raw_new, statuses=statuses, dead_letters_added=added)

    def get_job(self, source: str, external_id: str) -> StoredJob | None:
        return self._jobs.get((source, external_id))

    def new_postings(self, since: datetime) -> list[Posting]:
        return select_new(group_postings(self._jobs.values()), since)

    def raw_payloads(self) -> Iterator[RawPayload]:
        yield from sorted(self._raw.values(), key=lambda p: (p.fetched_at, p.raw_ref))

    def prune_raw(self, older_than: datetime) -> int:
        old = [ref for ref, p in self._raw.items() if p.fetched_at < older_than]
        for ref in old:
            del self._raw[ref]
        return len(old)

    def dead_letter_count(self) -> int:
        return len(self._dead)

    def unsent_postings(self) -> list[Posting]:
        notified = set(self._notified)
        postings = group_postings(self._jobs.values())
        return newest_first(p for p in postings if not is_sent(p, notified))

    def mark_sent(
        self, postings: Sequence[Posting], *, sent_at: datetime, telegram_message_ids: Sequence[int]
    ) -> int:
        self._digests += 1
        for posting in postings:
            for stored in posting.jobs:
                key = (stored.job.source, stored.job.external_id)
                self._notified.setdefault(key, self._digests)
        return self._digests

    def postings_since(self, since: datetime) -> list[tuple[Posting, bool]]:
        notified = set(self._notified)
        postings = select_new(group_postings(self._jobs.values()), since)
        return [(p, is_sent(p, notified)) for p in postings]

    @contextmanager
    def digest_lock(self) -> Iterator[None]:
        if not self._digest_lock.acquire(blocking=False):
            raise DigestBusyError("another digest is running")
        try:
            yield
        finally:
            self._digest_lock.release()

    def record_collection_run(self, run: CollectionRun) -> None:
        self._runs.append(run)

    def last_collection_run(self) -> CollectionRun | None:
        return max(self._runs, key=lambda r: r.finished_at, default=None)
