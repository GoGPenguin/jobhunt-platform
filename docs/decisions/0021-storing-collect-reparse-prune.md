# 0021: Storing collection, reparse and raw retention commands

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), D6, D8; plan [04](../plans/04-dedupe-store.md) task 6

## Decisions asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Which fetched emails get their raw payload stored? | Every email except ones that fail DKIM: routed, unknown-sender and disabled-source mail, and mail whose parser crashed. A parser added or fixed later can then `reparse` mail already received, and the IMAP pre-check doesn't fetch it again. Unauthenticated mail (possible phishing) is counted and dropped. |
| What does a storing run print? | Only new or updated jobs (with `status`), newly added dead letters, and the summary; a rerun prints just the summary. `--dry-run` keeps phase A output. |

## Implementation

- `jobhunt.pipeline.process_payloads` routes, parses and stores a batch. It is shared by `collect email` and `reparse`, and imports the parser registry itself.
- `jobhunt collect email` stores by default as `jobhunt_app`, passing `store.known_raw_refs` to the IMAP pre-check; `--dry-run` uses no database. The summary of a storing run has `new`, `updated`, `unchanged`, `dead_letters` and `raw_stored`.
- `jobhunt reparse [--source ID]` streams stored raw payloads through one connection and stores through another, so the read cursor and the write transactions don't interleave. Unknown-sender mail stored earlier is routed again, so adding a source picks it up.
- `jobhunt db prune-raw [--older-than 365d]` (spec default 1 year) runs as `jobhunt_app` (row DELETE only) and prints how many raw payloads it removed.
- Exit code 4 for any database error (`psycopg.Error`, migration errors) in every command; the app password is redacted as soon as it is loaded.
- `main(open_store=...)` lets tests use the in-memory store; production uses `PostgresJobStore`. `MemoryJobStore` became a context manager for that.

## Verified

- Tests written first (12 new across pipeline and CLI; 386 in total, 19 skipped without a database); `make check` passes.
- D6: storing prints 11 new jobs; the same run again prints only a summary with 11 unchanged; `--dry-run` output is unchanged from phase A.
- Unknown-sender mail is stored and later turned into 11 jobs by `reparse` once its source is configured; DKIM-failed mail is never stored; a crashing parser still leaves the raw payload stored.
- D8: `prune-raw --older-than 0d` removed both raw payloads.
- Database unreachable: exit 4, error shown, app password not printed.
- The real-Postgres path of these commands is covered by the store contract tests; the manual check in task 7 runs them end to end. No new dependencies, no secrets, cost $0.
