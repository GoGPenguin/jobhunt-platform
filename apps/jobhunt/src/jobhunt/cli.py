"""Command line.

    jobhunt collect email [--since 3d] [--eml FILE ...] [--dry-run] [--config-dir DIR]
    jobhunt reparse [--source ID] [--config-dir DIR]
    jobhunt db init-secrets | bootstrap | migrate | prune-raw [--older-than 365d]

stdout gets one JSON object per line ({"type": "job" | "dead_letter" | "summary", ...}); logs
and errors go to stderr with every known password redacted. Exit codes: 0 ok, 2 config error,
3 mail server error, 4 database error. See plans 02A and 04.
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

import psycopg

from jobhunt.config_files import ConfigError
from jobhunt.credentials import ensure_secrets, imap_credentials, load_secrets
from jobhunt.logs import configure_logging
from jobhunt.pipeline import process_payloads
from jobhunt.preferences import load_accepted_languages
from jobhunt.sources.config import EmailSection, load_sources
from jobhunt.sources.imap import ImapClient, TransportError, connect_ssl, fetch_emails
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY
from jobhunt.store import migrate as db_migrate
from jobhunt.store.port import CollectionRun, JobStore
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
EXIT_OK, EXIT_CONFIG, EXIT_TRANSPORT, EXIT_DATABASE = 0, 2, 3, 4

OpenStore = Callable[[str], AbstractContextManager[JobStore]]


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
) -> int:
    args = _arguments().parse_args(argv)
    run = _Run(args, now, env, logging.DEBUG if args.verbose else logging.INFO, open_store)
    configure_logging(stream=sys.stderr, level=run.level)
    try:
        if args.command == "db":
            return run.db(args.action)
        if args.command == "reparse":
            return run.reparse()
        return run.collect_email(connect)
    except (ConfigError, ValueError, OSError) as exc:
        log.error("%s", exc)  # logged, so a secret in the message is redacted
        return EXIT_CONFIG
    except TransportError as exc:
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
        return config.email, load_accepted_languages(self.config_dir / "preferences.yaml")

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
    return parser


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
