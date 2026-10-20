"""Route, parse and (optionally) store a batch of raw emails. Used by `collect email` and
`reparse`. See plans 02A (task 7) and 04 (task 6), decision 0021.

With a store:
- every email except unauthenticated ones has its raw payload stored, so a parser added or
  fixed later can `reparse` it, and the IMAP pre-check doesn't fetch it again;
- only new or updated jobs are printed (with their status), plus newly added dead letters.
Without a store (dry run) every job is printed once per run, as in phase A.
"""

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, TextIO

import jobhunt.sources.parsers  # noqa: F401 - registers the parsers used below
from jobhunt.domain.dead_letter import BuildResult, build_jobs
from jobhunt.sources.config import EmailSection
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY
from jobhunt.sources.routing import route
from jobhunt.store.port import JobStore

log = logging.getLogger(__name__)

OUTCOMES = ("routed", "unknown_sender", "unauthenticated", "disabled")
_NOTHING = BuildResult(jobs=(), dead_letters=(), dropped_languages={})


def process_payloads(
    payloads: Iterable[RawPayload],
    email: EmailSection,
    *,
    accepted: frozenset[str] | None,
    now: Callable[[], datetime],
    out: TextIO,
    store: JobStore | None,
    only_source: str | None = None,
) -> dict[str, Any]:
    """Process payloads, print JSON lines to `out`, and return (and print) the summary."""
    counts: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()  # dry run only: print each job once
    for payload in payloads:
        counts["emails"] += 1
        routed = route(payload, email.sources, trusted_authserv_id=email.imap.trusted_authserv_id)
        counts[routed.outcome] += 1
        if routed.outcome == "unauthenticated":
            continue  # possible forgery: never stored, never parsed
        if routed.outcome == "unknown_sender":
            unknown[routed.sender_domain or "(no sender)"] += 1
        if routed.outcome != "routed" or routed.source is None:
            _store(store, payload, _NOTHING, counts)
            continue
        if only_source and routed.source.id != only_source:
            counts["skipped_by_filter"] += 1
            continue
        plugin = REGISTRY.get(routed.source.parser)
        try:
            records = plugin.parse(payload)
        except Exception:
            log.exception("parser %s failed on %s", plugin.info.name, payload.raw_ref)
            counts["parser_errors"] += 1
            _store(store, payload, _NOTHING, counts)  # kept for reparse after the fix
            continue
        result = build_jobs(
            records,
            source=routed.source.id,
            parser=plugin.info,
            raw_ref=payload.raw_ref,
            accepted_languages=accepted,
            now=now,
        )
        dropped.update(result.dropped_languages)
        if store is None:
            _print_dry_run(result, seen, counts, out)
        else:
            _print_stored(store, payload, result, counts, out)

    summary = _summary(counts, dropped, unknown, stored=store is not None)
    _emit(out, "summary", summary)
    return summary


def _store(
    store: JobStore | None, payload: RawPayload, result: BuildResult, counts: Counter[str]
) -> None:
    if store is not None and store.store(payload, result).raw_new:
        counts["raw_stored"] += 1


def _print_stored(
    store: JobStore, payload: RawPayload, result: BuildResult, counts: Counter[str], out: TextIO
) -> None:
    outcome = store.store(payload, result)
    counts["raw_stored"] += outcome.raw_new
    counts.update(outcome.statuses.values())
    for job in result.jobs:
        status = outcome.statuses[(job.source, job.external_id)]
        if status != "unchanged":
            _emit(out, "job", {"status": status, **job.model_dump(mode="json")})
    if outcome.dead_letters_added:
        counts["dead_letters"] += outcome.dead_letters_added
        for letter in result.dead_letters:
            _emit(out, "dead_letter", letter.model_dump(mode="json"))


def _print_dry_run(
    result: BuildResult, seen: set[tuple[str, str]], counts: Counter[str], out: TextIO
) -> None:
    for job in result.jobs:
        if (job.source, job.external_id) in seen:
            counts["duplicates"] += 1
            continue
        seen.add((job.source, job.external_id))
        counts["jobs"] += 1
        _emit(out, "job", job.model_dump(mode="json"))
    for letter in result.dead_letters:
        counts["dead_letters"] += 1
        _emit(out, "dead_letter", letter.model_dump(mode="json"))


def _summary(
    counts: Counter[str], dropped: Counter[str], unknown: Counter[str], *, stored: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {"emails": counts["emails"]}
    summary |= {outcome: counts[outcome] for outcome in OUTCOMES}
    keys: tuple[str, ...]
    if stored:
        keys = ("new", "updated", "unchanged", "dead_letters", "raw_stored")
    else:
        keys = ("jobs", "duplicates", "dead_letters")
    summary |= {key: counts[key] for key in keys}
    summary |= {
        "dropped_languages": dict(dropped),
        "parser_errors": counts["parser_errors"],
        "unknown_senders": dict(unknown),
    }
    if counts["skipped_by_filter"]:
        summary["skipped_by_filter"] = counts["skipped_by_filter"]
    return summary


def _emit(out: TextIO, kind: str, data: dict[str, Any]) -> None:
    out.write(json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n")
