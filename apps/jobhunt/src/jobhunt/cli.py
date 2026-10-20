"""Command line. Phase A: `jobhunt collect email`, a dry run that prints JSON lines.

    jobhunt collect email [--since 3d] [--eml FILE ...] [--config-dir ~/.config/jobhunt]

stdout gets one JSON object per line: {"type": "job" | "dead_letter" | "summary", ...}.
Logs and errors go to stderr, with the IMAP password redacted. Exit codes: 0 ok, 2 config error,
3 mail server error. See plan 02A task 7.
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import jobhunt.sources.parsers  # noqa: F401 - registers the parsers
from jobhunt.config_files import ConfigError
from jobhunt.credentials import imap_credentials
from jobhunt.domain.dead_letter import build_jobs
from jobhunt.logs import configure_logging
from jobhunt.preferences import load_accepted_languages
from jobhunt.sources.config import EmailSection, load_sources
from jobhunt.sources.imap import ImapClient, TransportError, connect_ssl, fetch_emails
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY
from jobhunt.sources.routing import route

log = logging.getLogger("jobhunt.cli")

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "jobhunt"
EXIT_OK, EXIT_CONFIG, EXIT_TRANSPORT = 0, 2, 3
OUTCOMES = ("routed", "unknown_sender", "unauthenticated", "disabled")


def parse_since(value: str, *, today: date) -> date:
    """`3d` (days back from today) or an ISO date."""
    if value.endswith("d") and value[:-1].isdigit():
        return today - timedelta(days=int(value[:-1]))
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"--since {value!r}: use a day count like 3d or a date like 2026-10-17"
        ) from None


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    connect: Callable[[str, int], ImapClient] = connect_ssl,
    env: Mapping[str, str] = os.environ,
) -> int:
    args = _arguments().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(stream=sys.stderr, level=level)
    config_dir: Path = args.config_dir
    try:
        config = load_sources(config_dir / "sources.yaml", known_parsers=REGISTRY.names())
        if config.email is None:
            raise ConfigError(f"{config_dir / 'sources.yaml'}: no email section")
        accepted = load_accepted_languages(config_dir / "preferences.yaml")
        since = parse_since(args.since, today=now().astimezone().date())
        if args.eml:
            payloads = [RawPayload.from_email(p.read_bytes(), fetched_at=now()) for p in args.eml]
        else:
            creds = imap_credentials(env=env, secrets_path=config_dir / "secrets.env")
            configure_logging(
                secrets=[creds.password.get_secret_value()], stream=sys.stderr, level=level
            )
            payloads = fetch_emails(config.email.imap, creds, since=since, now=now, connect=connect)
    except (ConfigError, ValueError, OSError) as exc:
        log.error("%s", exc)  # logged, so a secret in the message is redacted
        return EXIT_CONFIG
    except TransportError as exc:
        log.error("%s", exc)
        return EXIT_TRANSPORT
    _process(payloads, config.email, accepted, now, sys.stdout)
    return EXIT_OK


def _process(
    payloads: list[RawPayload],
    email: EmailSection,
    accepted: frozenset[str] | None,
    now: Callable[[], datetime],
    out: TextIO,
) -> None:
    counts: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        routed = route(payload, email.sources, trusted_authserv_id=email.imap.trusted_authserv_id)
        counts[routed.outcome] += 1
        if routed.outcome == "unknown_sender":
            unknown[routed.sender_domain or "(no sender)"] += 1
        if routed.outcome != "routed" or routed.source is None:
            continue
        plugin = REGISTRY.get(routed.source.parser)
        try:
            records = plugin.parse(payload)
        except Exception:
            log.exception("parser %s failed on %s", plugin.info.name, payload.raw_ref)
            counts["parser_errors"] += 1
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

    summary: dict[str, Any] = {"emails": len(payloads)}
    summary |= {outcome: counts[outcome] for outcome in OUTCOMES}
    summary |= {k: counts[k] for k in ("jobs", "duplicates", "dead_letters")}
    summary |= {
        "dropped_languages": dict(dropped),
        "parser_errors": counts["parser_errors"],
        "unknown_senders": dict(unknown),
    }
    _emit(out, "summary", summary)


def _emit(out: TextIO, kind: str, data: dict[str, Any]) -> None:
    out.write(json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n")


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobhunt", description="JobHunt platform")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="collect jobs from sources")
    kinds = collect.add_subparsers(dest="kind", required=True)
    email = kinds.add_parser("email", help="parse job-alert emails (dry run, JSON lines)")
    email.add_argument("--since", default="3d", help="e.g. 3d or 2026-10-17 (default 3d)")
    email.add_argument(
        "--eml", nargs="+", type=Path, metavar="FILE", help="read .eml files instead of IMAP"
    )
    email.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    email.add_argument("-v", "--verbose", action="store_true")
    return parser


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
