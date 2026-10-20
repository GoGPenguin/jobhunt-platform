"""Two collectors storing the same new job at the same moment (spec 04 edge case "Two runs at
the same time"). Postgres only: the in-memory store has no concurrency."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import ScratchDatabase
from test_store_contract import at, payload, record, result

from jobhunt.sources.raw import RawPayload
from jobhunt.store.postgres import PostgresJobStore

T0 = datetime(2026, 10, 18, 1, 0, tzinfo=UTC)
ROUNDS = 25


def store(
    conninfo: str,
    raw: RawPayload,
    rec: dict[str, Any],
    barrier: threading.Barrier,
    errors: list[BaseException],
) -> None:
    """One collector: connect, wait for the other, then store the same job."""
    try:
        with PostgresJobStore(conninfo) as db:
            barrier.wait()
            db.store(raw, result(raw, rec))
    except BaseException as exc:  # surfaced by the test
        errors.append(exc)


def test_concurrent_first_sightings_keep_earliest(pg_database: ScratchDatabase) -> None:
    for n in range(ROUNDS):
        early, late = T0, T0 + timedelta(hours=1)
        jobs = {
            "early": (payload(2 * n), record(external_id=f"job-{n}", collected_at=at(early))),
            "late": (payload(2 * n + 1), record(external_id=f"job-{n}", collected_at=at(late))),
        }
        barrier = threading.Barrier(len(jobs))
        errors: list[BaseException] = []
        threads = [
            threading.Thread(target=store, args=(pg_database.app, raw, rec, barrier, errors))
            for raw, rec in jobs.values()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors
        with PostgresJobStore(pg_database.app) as db:
            stored = db.get_job("test-source", f"job-{n}")
        assert stored is not None
        assert (stored.first_seen_at, stored.last_seen_at) == (early, late), f"round {n}"
