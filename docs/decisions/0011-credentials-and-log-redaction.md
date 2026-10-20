# 0011: Credentials and log redaction

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), F11; plan [02A](../plans/02a-email-sources.md) task 3

## Decisions

- **Where secrets come from** (decided with spec 02): the environment, or `~/.config/jobhunt/secrets.env` in Docker Compose. The environment wins, so a container or CI can override the file. Variables: `JOBHUNT_IMAP_USER`, `JOBHUNT_IMAP_APP_PASSWORD`.
- **File format:** `KEY=VALUE` lines, `#` comments, optional `export` and quotes. The common `.env` subset, parsed with the standard library, no new dependency.
- **Permission check:** a secrets file that group or others can access in any way (`mode & 0o077`) is refused, with a `chmod 600` hint.
- **Values never echoed:** a malformed line is reported by line number only; the password is a Pydantic `SecretStr`, so `repr`/`str` show `**********`.
- **Log redaction:** `jobhunt.logs.configure_logging(secrets=...)` installs one handler with a filter that replaces each secret with `***` in the formatted message (including `%` arguments and f-strings) and in tracebacks. It sits on the handler, so it covers records from every logger.
- **Module names:** `jobhunt.credentials` and `jobhunt.logs`, not `jobhunt.secrets`, which would share its name with the standard library's `secrets` module.

## Verified

- Tests written first (14 new; 238 in total); `make check` passes.
- F11: a planted fake password logged through `%s` arguments, an f-string and an exception traceback never appears in the output (each replaced by `***`), and never in the credentials' `repr`/`str` or in config errors.
- Files with modes 640, 604, 644 and 660 are refused; 600 is accepted.
- No new dependencies. No real secret was created, read or printed in this task; cost $0.

## Limits

- Redaction matches the exact secret string. A secret that a library transforms before logging (e.g. base64 in an auth header) would not match; `imaplib` doesn't log credentials unless its debug level is raised, which the CLI won't do.
