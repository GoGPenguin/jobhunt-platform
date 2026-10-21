"""Command line.

    jobhunt collect email [--since 3d] [--eml FILE ...] [--dry-run] [--config-dir DIR]
    jobhunt reparse [--source ID] [--config-dir DIR]
    jobhunt db init-secrets | bootstrap | migrate | prune-raw [--older-than 365d]
    jobhunt digest send [--test] | list [--since 7d]
    jobhunt telegram find-chat
    jobhunt timer install --uv PATH --repo PATH [--at 12:00] | remove
    jobhunt profile check

stdout gets one JSON object per line ({"type": "job" | "dead_letter" | "posting" | "summary",
...}); logs and errors go to stderr with every known secret redacted. Exit codes: 0 ok, 2 config
error, 3 mail server or Telegram error, 4 database error, 5 another digest is running. See plans
02A, 04 and 05.
"""

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg

from jobhunt.config_files import ConfigError
from jobhunt.credentials import ensure_secrets, imap_credentials, load_secrets
from jobhunt.logs import configure_logging
from jobhunt.matching.score import Ranked, rank
from jobhunt.notify import timer as daily_timer
from jobhunt.notify.digest import compose
from jobhunt.notify.telegram import DEFAULT_API_BASE, TelegramClient, TelegramError
from jobhunt.pipeline import process_payloads
from jobhunt.profile.load import (
    MASTER_CV,
    PREFERENCES,
    Profile,
    load_profile,
    load_profile_lenient,
)
from jobhunt.profile.preferences import load_preferences
from jobhunt.sources.config import EmailSection, load_sources
from jobhunt.sources.imap import ImapClient, TransportError, connect_ssl, fetch_emails
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY
from jobhunt.store import migrate as db_migrate
from jobhunt.store.port import CollectionRun, DigestBusyError, JobStore
from jobhunt.store.postgres import PostgresJobStore
from jobhunt.store.settings import (
    ADMIN_PASSWORD,
    ADMIN_ROLE,
    APP_PASSWORD,
    APP_ROLE,
    DB_PASSWORD_KEYS,
    OWNER_PASSWORD,
    OWNER_ROLE,
    DatabaseSettings,
    conninfo,
)

log = logging.getLogger("jobhunt.cli")

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "jobhunt"
EXIT_OK, EXIT_CONFIG, EXIT_TRANSPORT, EXIT_DATABASE, EXIT_BUSY = 0, 2, 3, 4, 5
TELEGRAM_TOKEN = "JOBHUNT_TELEGRAM_BOT_TOKEN"  # noqa: S105 - variable name, not a value
TELEGRAM_CHAT = "JOBHUNT_TELEGRAM_CHAT_ID"


class Telegram(Protocol):
    def send_message(self, chat_id: str, html: str) -> int: ...
    def find_chats(self) -> list[tuple[str, str]]: ...


OpenStore = Callable[[str], AbstractContextManager[JobStore]]
OpenTelegram = Callable[[str, str], Telegram]


def _telegram_client(token: str, api_base: str) -> Telegram:
    return TelegramClient(token, api_base=api_base)


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


def parse_days(value: str) -> timedelta:
    if value.endswith("d") and value[:-1].isdigit():
        return timedelta(days=int(value[:-1]))
    raise ValueError(f"{value!r}: use a day count like 365d")


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    connect: Callable[[str, int], ImapClient] = connect_ssl,
    env: Mapping[str, str] = os.environ,
    open_store: OpenStore = PostgresJobStore,
    open_telegram: OpenTelegram = _telegram_client,
) -> int:
    args = _arguments().parse_args(argv)
    run = _Run(args, now, env, logging.DEBUG if args.verbose else logging.INFO, open_store)
    configure_logging(stream=sys.stderr, level=run.level)
    try:
        if args.command == "db":
            return run.db(args.action)
        if args.command == "reparse":
            return run.reparse()
        if args.command == "digest":
            return run.digest(args.action, open_telegram)
        if args.command == "telegram":
            return run.find_chat(open_telegram)
        if args.command == "timer":
            return run.timer(args.action)
        if args.command == "profile":
            return run.profile_check()
        return run.collect_email(connect)
    except DigestBusyError as exc:
        log.error("%s; try again when it has finished", exc)
        return EXIT_BUSY
    except (ConfigError, ValueError, OSError) as exc:
        log.error("%s", exc)  # logged, so a secret in the message is redacted
        return EXIT_CONFIG
    except (TransportError, TelegramError) as exc:
        log.error("%s", exc)
        return EXIT_TRANSPORT
    except (psycopg.Error, db_migrate.MigrationError) as exc:
        settings = DatabaseSettings.from_env(env)
        log.error("database %s:%s: %s", settings.host, settings.port, str(exc).strip())
        return EXIT_DATABASE


class _Run:
    """One command invocation: arguments, clock, environment and where secrets live."""

    def __init__(
        self,
        args: argparse.Namespace,
        now: Callable[[], datetime],
        env: Mapping[str, str],
        level: int,
        open_store: OpenStore,
    ) -> None:
        self.args, self.now, self.env, self.level = args, now, env, level
        self.open_store = open_store
        self.config_dir: Path = args.config_dir
        self.secrets_path = self.config_dir / "secrets.env"
        self.settings = DatabaseSettings.from_env(env)
        self._redacted: list[str] = []

    def redact(self, *secrets: str) -> None:
        self._redacted += secrets
        configure_logging(secrets=self._redacted, stream=sys.stderr, level=self.level)

    def scrub(self, text: str) -> str:
        """`text` with every known secret replaced, for errors stored in the database."""
        for secret in self._redacted:
            text = text.replace(secret, "***")
        return text

    def email_config(self) -> tuple[EmailSection, frozenset[str] | None]:
        sources = self.config_dir / "sources.yaml"
        config = load_sources(sources, known_parsers=REGISTRY.names())
        if config.email is None:
            raise ConfigError(f"{sources}: no email section")
        return config.email, load_preferences(self.config_dir / PREFERENCES).accepted_languages

    def app_conninfo(self) -> str:
        password = load_secrets([APP_PASSWORD], self.env, self.secrets_path)[APP_PASSWORD]
        self.redact(password)
        return conninfo(self.settings, APP_ROLE, password)

    def collect_email(self, connect: Callable[[str, int], ImapClient]) -> int:
        email, accepted = self.email_config()
        since = parse_since(self.args.since, today=self.now().astimezone().date())

        def payloads(store: JobStore | None) -> list[RawPayload]:
            if self.args.eml:
                return [
                    RawPayload.from_email(p.read_bytes(), fetched_at=self.now())
                    for p in self.args.eml
                ]
            creds = imap_credentials(env=self.env, secrets_path=self.secrets_path)
            self.redact(creds.password.get_secret_value())
            known = store.known_raw_refs if store else None
            return fetch_emails(
                email.imap, creds, since=since, now=self.now, connect=connect, known=known
            )

        if self.args.dry_run:
            process_payloads(
                payloads(None), email, accepted=accepted, now=self.now, out=sys.stdout, store=None
            )
            return EXIT_OK
        with self.open_store(self.app_conninfo()) as store:
            started = self.now()
            try:
                summary = process_payloads(
                    payloads(store), email, accepted=accepted, now=self.now, out=sys.stdout,
                    store=store,
                )  # fmt: skip
            except Exception as exc:
                failed = CollectionRun(started, self.now(), ok=False, error=self.scrub(str(exc)))
                store.record_collection_run(failed)
                raise
            succeeded = CollectionRun(started, self.now(), ok=True, summary=summary)
            store.record_collection_run(succeeded)
        return EXIT_OK

    def reparse(self) -> int:
        email, accepted = self.email_config()
        app = self.app_conninfo()
        with self.open_store(app) as reader, self.open_store(app) as writer:
            process_payloads(
                reader.raw_payloads(),
                email,
                accepted=accepted,
                now=self.now,
                out=sys.stdout,
                store=writer,
                only_source=self.args.source,
            )
        return EXIT_OK

    def telegram(self, open_telegram: OpenTelegram) -> Telegram:
        token = load_secrets([TELEGRAM_TOKEN], self.env, self.secrets_path)[TELEGRAM_TOKEN]
        self.redact(token)
        return open_telegram(token, self.env.get("JOBHUNT_TELEGRAM_API_BASE", DEFAULT_API_BASE))

    def chat_id(self) -> str:
        try:
            return load_secrets([TELEGRAM_CHAT], self.env, self.secrets_path)[TELEGRAM_CHAT]
        except ConfigError:
            raise ConfigError(
                f"{TELEGRAM_CHAT} missing in {self.secrets_path}: send your bot a message, run "
                "`jobhunt telegram find-chat`, then add the chat id"
            ) from None

    def digest(self, action: str, open_telegram: OpenTelegram) -> int:
        profile, problems = load_profile_lenient(self.config_dir)
        tz = profile.preferences.timezone
        if action == "list":
            return self.digest_list(profile)
        telegram, chat = self.telegram(open_telegram), self.chat_id()
        if self.args.test:
            stamp = self.now().astimezone(tz).strftime("%H:%M")
            message = f"JobHunt test message: the bot can reach this chat. {stamp}"
            telegram.send_message(chat, message)
            return EXIT_OK
        with self.open_store(self.app_conninfo()) as store, store.digest_lock():
            ranked = rank(store.unsent_postings(), profile)
            last_run = store.last_collection_run()
            digest = compose(ranked, last_run, now=self.now(), tz=tz, warnings=problems)
            message_ids = [telegram.send_message(chat, text) for text in digest.messages]
            # Only after Telegram accepted every message: a failed send marks nothing.
            store.mark_sent(digest.postings, sent_at=self.now(), telegram_message_ids=message_ids)
        summary = {"messages": len(message_ids), "postings": len(digest.postings)}
        sys.stdout.write(json.dumps({"type": "summary", **summary}) + "\n")
        return EXIT_OK

    def digest_list(self, profile: Profile) -> int:
        tz = profile.preferences.timezone
        since = self.now() - parse_days(self.args.since)
        with self.open_store(self.app_conninfo()) as store:
            listed = store.postings_since(since)
        sent = {id(posting): was_sent for posting, was_sent in listed}
        for ranked in rank([posting for posting, _ in listed], profile):
            line = _listing(ranked, sent[id(ranked.posting)], tz)
            sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
        return EXIT_OK

    def find_chat(self, open_telegram: OpenTelegram) -> int:
        chats = self.telegram(open_telegram).find_chats()
        for chat_id, name in chats:
            sys.stdout.write(json.dumps({"type": "chat", "chat_id": chat_id, "name": name}) + "\n")
        if chats:
            log.info("add %s=<chat_id> to %s", TELEGRAM_CHAT, self.secrets_path)
        else:
            log.warning("no chats yet: send your bot any message in Telegram, then run this again")
        return EXIT_OK

    def profile_check(self) -> int:
        """Validate master_cv.yaml, preferences.yaml and the aliases. Messages name entries by
        location, never the values: the CV is private and the output may be shared."""
        errors: list[str] = []
        warnings: list[str] = []
        if not (self.config_dir / MASTER_CV).exists():
            errors.append(f"{self.config_dir / MASTER_CV}: not found")
        if not (self.config_dir / PREFERENCES).exists():
            warnings.append(f"{self.config_dir / PREFERENCES}: not found, using defaults")
        try:
            profile = load_profile(self.config_dir)
        except ConfigError as exc:
            errors += [line.strip() for line in str(exc).splitlines()[1:]] or [str(exc)]
        else:
            errors += profile.issues()
            warnings += profile.warnings()
        for message in errors:
            log.error("%s", message)
        for message in warnings:
            log.warning("%s", message)
        summary = {"type": "summary", "errors": len(errors), "warnings": len(warnings)}
        sys.stdout.write(json.dumps(summary) + "\n")
        return EXIT_CONFIG if errors else EXIT_OK

    def timer(self, action: str) -> int:
        unit_dir: Path = self.args.unit_dir
        if action == "remove":
            removed = daily_timer.remove_units(unit_dir)
            log.info("removed %s", ", ".join(map(str, removed)) or "nothing (not installed)")
            return EXIT_OK
        if not self.args.uv or not self.args.repo:
            raise ConfigError("timer install needs --uv and --repo (use make install-timer)")
        tz = load_preferences(self.config_dir / PREFERENCES).timezone
        written = daily_timer.install_units(
            unit_dir, repo=self.args.repo, uv=self.args.uv, at=self.args.at, tz=tz
        )
        log.info("wrote %s", ", ".join(map(str, written)))
        return EXIT_OK

    def db(self, action: str) -> int:
        if action == "init-secrets":
            ensure_secrets(self.secrets_path, DB_PASSWORD_KEYS, out=sys.stderr)
            return EXIT_OK
        if action == "prune-raw":
            cutoff = self.now() - parse_days(self.args.older_than)
            with self.open_store(self.app_conninfo()) as store:
                pruned = store.prune_raw(older_than=cutoff)
            sys.stdout.write(json.dumps({"type": "summary", "pruned_raw_payloads": pruned}) + "\n")
            return EXIT_OK
        passwords = load_secrets(DB_PASSWORD_KEYS, self.env, self.secrets_path)
        self.redact(*passwords.values())
        if action == "bootstrap":
            admin = conninfo(self.settings, ADMIN_ROLE, passwords[ADMIN_PASSWORD], "postgres")
            db_migrate.bootstrap(
                admin,
                self.settings,
                owner_password=passwords[OWNER_PASSWORD],
                app_password=passwords[APP_PASSWORD],
            )
            log.info("roles and database %r ready", self.settings.name)
        else:
            owner = conninfo(self.settings, OWNER_ROLE, passwords[OWNER_PASSWORD])
            applied = db_migrate.migrate(owner)
            log.info("applied %s", ", ".join(applied) if applied else "nothing: up to date")
        return EXIT_OK


def _listing(ranked: Ranked, sent: bool, tz: ZoneInfo) -> dict[str, object]:
    posting = ranked.posting
    job = posting.representative.job
    return {
        "type": "posting",
        "sent": sent,
        "score": ranked.score,
        "reasons": list(ranked.reasons),
        "flags": list(ranked.flags),
        "filtered": ranked.filtered,
        "first_seen_at": posting.first_seen_at.astimezone(tz).isoformat(),
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "sources": sorted({j.job.source for j in posting.jobs}),
    }


def _arguments() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="jobhunt", description="JobHunt platform")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="collect jobs from sources")
    kinds = collect.add_subparsers(dest="kind", required=True)
    email = kinds.add_parser("email", parents=[common], help="collect job-alert emails")
    email.add_argument("--since", default="3d", help="e.g. 3d or 2026-10-17 (default 3d)")
    email.add_argument(
        "--eml", nargs="+", type=Path, metavar="FILE", help="read .eml files instead of IMAP"
    )
    email.add_argument(
        "--dry-run", action="store_true", help="print all jobs; no database needed or written"
    )

    reparse = commands.add_parser(
        "reparse", parents=[common], help="re-run current parsers over stored raw payloads"
    )
    reparse.add_argument("--source", help="only payloads routed to this source id")

    db = commands.add_parser("db", parents=[common], help="database setup and maintenance")
    db.add_argument(
        "action",
        choices=["init-secrets", "bootstrap", "migrate", "prune-raw"],
        help="init-secrets: add missing DB passwords to secrets.env; bootstrap: roles and "
        "database (as admin); migrate: apply migrations (as owner); prune-raw: delete old raw "
        "payloads",
    )
    db.add_argument("--older-than", default="365d", help="for prune-raw (default 365d)")

    digest = commands.add_parser("digest", parents=[common], help="the daily Telegram digest")
    digest.add_argument(
        "action",
        choices=["send", "list"],
        help="send: postings not sent yet; list: recent postings and whether they were sent",
    )
    digest.add_argument("--test", action="store_true", help="send: only a test message")
    digest.add_argument("--since", default="7d", help="list: how far back (default 7d)")

    telegram = commands.add_parser("telegram", parents=[common], help="Telegram setup")
    telegram.add_argument("action", choices=["find-chat"], help="chats that messaged the bot")

    timer = commands.add_parser("timer", parents=[common], help="daily run on this machine")
    timer.add_argument("action", choices=["install", "remove"])
    timer.add_argument("--uv", type=Path, help="install: absolute path of the uv binary")
    timer.add_argument("--repo", type=Path, help="install: absolute path of this repository")
    timer.add_argument("--at", default="12:00", help="install: local time HH:MM (default 12:00)")
    timer.add_argument("--unit-dir", type=Path, default=daily_timer.DEFAULT_UNIT_DIR)

    profile = commands.add_parser("profile", parents=[common], help="the master CV and preferences")
    profile.add_argument("action", choices=["check"], help="validate both files and the aliases")
    return parser


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
