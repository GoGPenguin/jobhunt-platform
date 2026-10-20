# 0012: Read-only IMAP transport

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), F4; plan [02A](../plans/02a-email-sources.md) task 4

## Decisions

- **Only read-only commands** (spec 02): `LOGIN`, `EXAMINE` (via `imaplib`'s `select(readonly=True)`, confirmed in the 3.12.14 source), `UID SEARCH SINCE`, `UID FETCH … (BODY.PEEK[])` (does not set `\Seen`), `LOGOUT`. No `SELECT`, `STORE`, `COPY`, `MOVE`, `EXPUNGE` or `APPEND` exists anywhere in the code.
- **Every fetched email becomes a redacted `RawPayload`** before it is returned (decision 0010).
- **Limits:** at most 500 messages per run (the newest are kept, with a warning), fetched in batches of 50, and a 30-second socket timeout with TLS from the system trust store.
- **`--since` is a day:** IMAP `SINCE` has day granularity, so a run can return mail it saw the day before. Same email, same `raw_ref`, so the dedupe-store will make it a no-op; Phase A is a dry run, as decided.
- **Label names are quoted** (spaces allowed). Non-ASCII labels are rejected with a clear error, because they would need IMAP's modified UTF-7.
- **Errors never contain the password.** A login failure explains the usual Gmail causes (IMAP disabled, account password used instead of an app password).
- **Testability:** the transport depends on a small `ImapClient` protocol; tests pass a fake, production uses `imaplib.IMAP4_SSL`.

## Verified

- Tests written first (10 new; 248 in total); `make check` passes.
- F4: a fake server records the exact command sequence and fails the test on `SELECT`, any non-PEEK fetch, any other `UID` command, or any other `imaplib` method. The transport always logs out, also when the label is missing.
- Re-running on the same mailbox gives the same `raw_ref`s; payloads are redacted (`otpToken` gone, job ids kept).
- No connection to a real mail server yet: that is the manual check in task 7. No secrets, cost $0.
