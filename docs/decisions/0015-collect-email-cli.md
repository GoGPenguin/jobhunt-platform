# 0015: `jobhunt collect email` dry-run CLI

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), phase A; plan [02A](../plans/02a-email-sources.md) task 7

## Decision asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Also accept local `.eml` files besides IMAP? | Yes, `--eml FILE ...`: same routing, parsing and output, no network or app password. |

## Implementation

- `jobhunt collect email [--since 3d|YYYY-MM-DD] [--eml FILE ...] [--config-dir DIR] [-v]`, console script `jobhunt`, and `make collect-email` (`SINCE=`, `EML=`).
- Reads `sources.yaml`, `preferences.yaml` and `secrets.env` from `--config-dir` (default `~/.config/jobhunt`).
- **stdout** gets JSON lines: `job`, `dead_letter`, then one `summary`. The summary has emails read, each routing outcome, jobs, duplicates, dead letters, dropped languages, parser errors and unknown sender domains (useful for spotting a platform that needs a parser). **stderr** gets logs and errors.
- A job seen twice in one run (the same job in two alert emails) is printed once and counted as a duplicate. Deduplication across runs is the dedupe-store's job.
- **Errors go through the logger,** so they get the same password redaction as logs, even if a server echoes the password. Exit codes: 2 for config, input and `--since` problems; 3 for mail-server problems. A crashing parser is logged with its traceback, counted, and the run continues.
- Logging is reconfigured with the IMAP password as soon as credentials are loaded.

## Verified

- Tests written first (11 new; 320 in total); `make check` passes.
- Covered: `.eml` mode on both fixtures (11 jobs, exact summary), language filter from preferences, duplicates across emails, unknown sender counted with its domain, parser crash isolated, missing `sources.yaml` (exit 2), IMAP mode against a fake server using `secrets.env`, and a login failure whose server message contains the password: exit 3, "app password" hint, password absent from stderr.
- **Real run on the two LinkedIn sample emails** with the installed `jobhunt` command and the user's private config: exit 0, 2 routed, 14 jobs, 2 duplicates, 0 dead letters, no token in the output. The output file was deleted afterwards.
- Private `~/.config/jobhunt/sources.yaml` created from the sample (mode 600).

## Manual IMAP check (2026-10-20)

Run by the user against the real Gmail `jobhunt` label (`make collect-email SINCE=7d`): 4 emails, 4 routed (DKIM passed), 0 unauthenticated, 19 jobs, 5 duplicates, 0 dead letters, 0 parser errors. Every email yielded jobs (6, 3, 8, 2 new ones); all are the two LinkedIn kinds seen in the samples ("Jobs You Might Be Interested In", "Viewed Jobs"). Two `raw_ref`s equal those computed earlier from the downloaded `.eml` samples, confirming the same email has the same identity via IMAP and via file.

During setup an app password was typed into the assistant chat by mistake (a `!` command). It was treated as exposed: never used or stored, and the user was asked to revoke it and create a new one, writing it into `secrets.env` from a separate terminal.
