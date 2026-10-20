"""Postgres JobStore (psycopg 3). Connects as jobhunt_app. Same contract as MemoryJobStore; the
upsert and posting rules come from jobhunt.store.port. See spec 04 and plan 04 task 4."""

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from types import TracebackType
from typing import Any, Self

import psycopg
from psycopg.types.json import Jsonb

from jobhunt.domain.dead_letter import BuildResult
from jobhunt.domain.job import Job
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

_DIGEST_LOCK_ID = 72_610_002  # pg_advisory_lock key for composing and sending a digest
# Jobs of every fingerprint that has an unsent job, with whether each job was sent.
_JOBS_OF_UNSENT_FINGERPRINTS = """
    SELECT j.data, j.fingerprint, j.first_seen_at, j.last_seen_at, j.updated_at,
           n.digest_id IS NOT NULL
    FROM jobs j LEFT JOIN notified_jobs n USING (source, external_id)
    WHERE j.fingerprint IN (
        SELECT j2.fingerprint FROM jobs j2 LEFT JOIN notified_jobs n2 USING (source, external_id)
        WHERE n2.digest_id IS NULL)
"""
_JOBS_OF_FINGERPRINTS_SEEN_SINCE = """
    SELECT j.data, j.fingerprint, j.first_seen_at, j.last_seen_at, j.updated_at,
           n.digest_id IS NOT NULL
    FROM jobs j LEFT JOIN notified_jobs n USING (source, external_id)
    WHERE j.fingerprint IN (SELECT fingerprint FROM jobs WHERE first_seen_at > %s)
"""

_INSERT_JOB = """
    INSERT INTO jobs (source, external_id, data, fingerprint, language, collected_at, raw_ref,
                      parser_name, parser_version, first_seen_at, last_seen_at, updated_at)
    VALUES (%(source)s, %(external_id)s, %(data)s, %(fingerprint)s, %(language)s,
            %(collected_at)s, %(raw_ref)s, %(parser_name)s, %(parser_version)s,
            %(first_seen_at)s, %(last_seen_at)s, %(updated_at)s)
    ON CONFLICT (source, external_id) DO NOTHING
    RETURNING 1
"""
_UPDATE_JOB = """
    UPDATE jobs SET data = %(data)s, fingerprint = %(fingerprint)s, language = %(language)s,
                    collected_at = %(collected_at)s, raw_ref = %(raw_ref)s,
                    parser_name = %(parser_name)s, parser_version = %(parser_version)s,
                    first_seen_at = %(first_seen_at)s, last_seen_at = %(last_seen_at)s,
                    updated_at = %(updated_at)s
    WHERE source = %(source)s AND external_id = %(external_id)s
"""


class PostgresJobStore:
    """Use as a context manager: `with PostgresJobStore(conninfo) as store: ...`."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._conn = psycopg.connect(conninfo, autocommit=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def known_raw_refs(self, raw_refs: Iterable[str]) -> set[str]:
        refs = list(raw_refs)
        rows = self._conn.execute(
            "SELECT raw_ref FROM raw_payloads WHERE raw_ref = ANY(%s)", (refs,)
        ).fetchall()
        return {ref for (ref,) in rows}

    def store(self, payload: RawPayload, result: BuildResult) -> StoreResult:
        statuses: dict[tuple[str, str], JobStatus] = {}
        with self._conn.transaction():
            raw_new = (
                self._conn.execute(
                    "INSERT INTO raw_payloads (raw_ref, origin, content_type, content, fetched_at)"
                    " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (raw_ref) DO NOTHING RETURNING 1",
                    (payload.raw_ref, payload.origin, payload.content_type, payload.content,
                     payload.fetched_at),
                ).fetchone()
                is not None
            )  # fmt: skip
            for job in result.jobs:
                key = (job.source, job.external_id)
                status = self._upsert(job)
                statuses[key] = "new" if statuses.get(key) == "new" else status
            added = 0
            for letter in result.dead_letters:
                cursor = self._conn.execute(
                    "INSERT INTO dead_letters (dedupe_key, source, raw_ref, parser_name,"
                    " parser_version, errors, parsed_record, failed_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (dedupe_key) DO NOTHING",
                    (dead_letter_key(letter), letter.source, letter.raw_ref, letter.parser.name,
                     letter.parser.version, Jsonb([e.model_dump() for e in letter.errors]),
                     Jsonb(letter.model_dump(mode="json")["record"]), letter.failed_at),
                )  # fmt: skip
                added += cursor.rowcount
        return StoreResult(raw_new=raw_new, statuses=statuses, dead_letters_added=added)

    def _upsert(self, job: Job) -> JobStatus:
        # Insert first: a concurrent writer of the same new job waits on the unique index here,
        # then sees our committed row below, so first_seen_at is never lost.
        stored, status = plan_upsert(None, job)
        if self._conn.execute(_INSERT_JOB, _row(stored)).fetchone() is not None:
            return status
        existing = self._conn.execute(
            "SELECT data, fingerprint, first_seen_at, last_seen_at, updated_at FROM jobs"
            " WHERE source = %s AND external_id = %s FOR UPDATE",
            (job.source, job.external_id),
        ).fetchone()
        assert existing is not None  # noqa: S101 - the insert conflicted, so the row exists
        stored, status = plan_upsert(_stored(existing), job)
        self._conn.execute(_UPDATE_JOB, _row(stored))
        return status

    def get_job(self, source: str, external_id: str) -> StoredJob | None:
        row = self._conn.execute(
            "SELECT data, fingerprint, first_seen_at, last_seen_at, updated_at FROM jobs"
            " WHERE source = %s AND external_id = %s",
            (source, external_id),
        ).fetchone()
        return _stored(row) if row else None

    def new_postings(self, since: datetime) -> list[Posting]:
        # Every job of any fingerprint with a new sighting, so country groups are complete.
        rows = self._conn.execute(
            "SELECT data, fingerprint, first_seen_at, last_seen_at, updated_at FROM jobs"
            " WHERE fingerprint IN"
            " (SELECT fingerprint FROM jobs WHERE first_seen_at > %s)",
            (since,),
        ).fetchall()
        return select_new(group_postings(_stored(row) for row in rows), since)

    def raw_payloads(self) -> Iterator[RawPayload]:
        with self._conn.transaction(), self._conn.cursor(name="raw_payloads") as cursor:
            cursor.execute(
                "SELECT raw_ref, origin, content_type, content, fetched_at FROM raw_payloads"
                " ORDER BY fetched_at, raw_ref"
            )
            for raw_ref, origin, content_type, content, fetched_at in cursor:
                yield RawPayload(
                    raw_ref=raw_ref, origin=origin, content_type=content_type,
                    content=bytes(content), fetched_at=fetched_at,
                )  # fmt: skip

    def prune_raw(self, older_than: datetime) -> int:
        cursor = self._conn.execute("DELETE FROM raw_payloads WHERE fetched_at < %s", (older_than,))
        return cursor.rowcount

    def dead_letter_count(self) -> int:
        row = self._conn.execute("SELECT count(*) FROM dead_letters").fetchone()
        return int(row[0]) if row else 0

    def unsent_postings(self) -> list[Posting]:
        jobs, notified = self._jobs_with_flags(_JOBS_OF_UNSENT_FINGERPRINTS, ())
        return newest_first(p for p in group_postings(jobs) if not is_sent(p, notified))

    def mark_sent(
        self, postings: Sequence[Posting], *, sent_at: datetime, telegram_message_ids: Sequence[int]
    ) -> int:
        with self._conn.transaction():
            row = self._conn.execute(
                "INSERT INTO digests (sent_at, postings, telegram_message_ids)"
                " VALUES (%s, %s, %s) RETURNING id",
                (sent_at, len(postings), Jsonb(list(telegram_message_ids))),
            ).fetchone()
            assert row is not None  # noqa: S101 - INSERT ... RETURNING always returns a row
            digest_id = int(row[0])
            for posting in postings:
                for stored in posting.jobs:
                    self._conn.execute(
                        "INSERT INTO notified_jobs (source, external_id, digest_id, notified_at)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (stored.job.source, stored.job.external_id, digest_id, sent_at),
                    )
        return digest_id

    def postings_since(self, since: datetime) -> list[tuple[Posting, bool]]:
        jobs, notified = self._jobs_with_flags(_JOBS_OF_FINGERPRINTS_SEEN_SINCE, (since,))
        return [(p, is_sent(p, notified)) for p in select_new(group_postings(jobs), since)]

    def _jobs_with_flags(
        self, query: str, params: tuple[Any, ...]
    ) -> tuple[list[StoredJob], set[tuple[str, str]]]:
        jobs, notified = [], set()
        for *row, sent in self._conn.execute(query.encode(), params):
            stored = _stored(tuple(row))
            jobs.append(stored)
            if sent:
                notified.add((stored.job.source, stored.job.external_id))
        return jobs, notified

    @contextmanager
    def digest_lock(self) -> Iterator[None]:
        # Its own connection: advisory locks are re-entrant within one session.
        with psycopg.connect(self._conninfo, autocommit=True) as conn:
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (_DIGEST_LOCK_ID,)).fetchone()
            if not row or not row[0]:
                raise DigestBusyError("another digest is running")
            try:
                yield
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (_DIGEST_LOCK_ID,))

    def record_collection_run(self, run: CollectionRun) -> None:
        self._conn.execute(
            "INSERT INTO collection_runs (started_at, finished_at, ok, summary, error)"
            " VALUES (%s, %s, %s, %s, %s)",
            (run.started_at, run.finished_at, run.ok, Jsonb(run.summary), run.error),
        )

    def last_collection_run(self) -> CollectionRun | None:
        row = self._conn.execute(
            "SELECT started_at, finished_at, ok, summary, error FROM collection_runs"
            " ORDER BY finished_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        started_at, finished_at, ok, summary, error = row
        return CollectionRun(started_at, finished_at, ok, summary, error)


def _row(stored: StoredJob) -> dict[str, Any]:
    job = stored.job
    return {
        "source": job.source,
        "external_id": job.external_id,
        "data": Jsonb(job.model_dump(mode="json")),
        "fingerprint": stored.fingerprint,
        "language": job.language,
        "collected_at": job.collected_at,
        "raw_ref": job.raw_ref,
        "parser_name": job.parser.name,
        "parser_version": job.parser.version,
        "first_seen_at": stored.first_seen_at,
        "last_seen_at": stored.last_seen_at,
        "updated_at": stored.updated_at,
    }


def _stored(row: tuple[Any, ...]) -> StoredJob:
    data, fingerprint, first_seen_at, last_seen_at, updated_at = row  # SELECT column order
    return StoredJob(
        job=Job.from_storage(data),
        fingerprint=fingerprint,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        updated_at=updated_at,
    )
