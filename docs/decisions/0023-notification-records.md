# 0023: Notification records, digest lock and collection runs

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md); plan [05](../plans/05-notifications.md) task 1

## Implementation

- Migration `0002_notifications`: `digests`, `notified_jobs` (primary key `(source, external_id)`, foreign keys to `digests` and to `jobs` with `ON DELETE CASCADE`) and `collection_runs`. `jobhunt_app` gets row access through the default privileges from `0001`; no grants needed.
- `JobStore` gains `unsent_postings`, `mark_sent`, `postings_since`, `digest_lock`, `record_collection_run` and `last_collection_run`, in both stores. Both use the shared `group_postings`, and new shared helpers `is_sent` and `newest_first`.
- **A posting is sent when any of its jobs is in `notified_jobs`,** so a job joining a sent posting from another source doesn't revive it (spec 05). `mark_sent` records every job of each posting, ignores jobs already recorded (marking twice is harmless) and returns the digest id.
- **`digest_lock()`** guards the whole choose → send → mark sequence. Spec 05's "two digests at once" case needs the lock across the Telegram send, not only around the insert. Postgres uses `pg_try_advisory_lock` **on its own connection**: advisory locks are re-entrant within a session, so taking it on the store's connection would let a second attempt in the same process succeed. A second digest fails fast with `DigestBusyError` instead of waiting.
- **`collect email` records a run** (start, finish, ok, summary, or error) in storing mode, also when fetching fails. The stored error passes through the same secret scrubbing as the logs. Configuration errors before the database is open aren't recorded; the digest's "no run in 26 h" warning covers them.
- The user's real database was migrated to `0002`.

## Verified

- Tests written first (8 new; 395 in total, 26 skipped without a database); `make test-db`: 80 store tests on PostgreSQL 18.6.
- Unsent → marked → nothing unsent; joining job doesn't revive; marking twice; `postings_since` sent flags; the lock is exclusive and released; the last collection run is the latest one.
- A failed IMAP login records `ok=false` with the "app password" hint and without the password.
- No new dependencies, cost $0.
