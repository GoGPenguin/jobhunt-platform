"""In-memory JobStore for unit tests and dry runs. Same contract as the Postgres store."""

from collections.abc import Iterable, Iterator
from datetime import datetime
from types import TracebackType
from typing import Self

from jobhunt.domain.dead_letter import BuildResult, DeadLetter
from jobhunt.sources.raw import RawPayload
from jobhunt.store.port import (
    JobStatus,
    Posting,
    StoredJob,
    StoreResult,
    dead_letter_key,
    group_postings,
    plan_upsert,
    select_new,
)


class MemoryJobStore:
    def __init__(self) -> None:
        self._raw: dict[str, RawPayload] = {}
        self._jobs: dict[tuple[str, str], StoredJob] = {}
        self._dead: dict[str, DeadLetter] = {}

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
