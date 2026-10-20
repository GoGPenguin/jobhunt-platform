# 0022: End-to-end run on the real mailbox; `extra` is not content

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md); plan [04](../plans/04-dedupe-store.md) task 7

## Manual check (real Gmail, real Postgres on this machine)

1. `make db-up`: added the 3 DB passwords to `secrets.env` (mode 600, values never shown) and started PostgreSQL 18.6 on `127.0.0.1:5432`, healthy.
2. `make db-migrate`: roles and database created, `0001_initial` applied; a second run reported "nothing: up to date".
3. `make collect-email SINCE=7d`, run 1: 4 emails, 4 routed, **19 new**, 4 raw payloads stored, 0 dead letters. But it also reported **5 updated** (see below).
4. Run 2: "0 of 4 emails are new": headers only, no bodies fetched (D7 on the real mailbox), nothing stored.
5. `new_postings(30 days)`: 19 postings, one job each (single source so far), 3 with country VN, 16 without a country.

## Finding and decision (asked)

The 5 "updated" were the 5 jobs that appear in two alert emails. The LinkedIn parser stores per-email details (`email_kind`, `badges`) in `extra`, so the second sighting looked like a change and replaced the first.

**Decision:** `extra` is ignored when deciding whether a job changed, like `collected_at`, `raw_ref` and `parser`. This follows spec 01's rule that core logic never reads `extra`. The first sighting's `extra` is kept; a real change to any other field still replaces the whole record. Spec 04 updated.

## Verified after the fix

- New contract test (same job, different `extra` → `unchanged`, first `extra` kept), run against both stores; 387 tests locally (20 skipped without a database), 68 store tests on Postgres.
- `jobhunt reparse` over the 4 stored real emails: 0 new, 0 updated, **24 unchanged** (19 jobs + 5 repeats), which also exercises reparse on real data.
- Cost $0. A Postgres container now runs locally with `restart: unless-stopped`; `make db-down` stops it, and its data stays in the `jobhunt_db-data` volume.
