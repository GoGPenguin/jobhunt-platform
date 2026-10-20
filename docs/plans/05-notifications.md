# Plan 05: Notifications (daily Telegram digest)

Spec: [05-notifications](../spec/05-notifications.md)
Status: approved 2026-10-20

## Design

**Code layout:** `jobhunt.notify` with `telegram.py` (Bot API client), `digest.py` (composing the text: pure functions, no I/O) and `timer.py` (rendering the systemd units). Store methods are added to the `JobStore` port, with both implementations and contract tests.

**Store additions** (migration `0002_notifications.sql`, with app-role grants via the default privileges from `0001`):

- `record_collection_run(started_at, finished_at, ok, summary, error)` and `last_collection_run()`.
- `unsent_postings()`: postings none of whose jobs is in `notified_jobs`, using the shared `group_postings`.
- `mark_sent(postings, sent_at, telegram_message_ids)` inserts one `digests` row and the `notified_jobs` rows in one transaction, under an advisory lock so two digests can't both send the same postings.
- `postings_since(since)` with a sent flag, for `digest list`.

**Telegram client:** `TelegramClient(token, api_base="https://api.telegram.org")`.
- Operations: `send_message(chat_id, html) -> message_id` (`parse_mode=HTML`, `link_preview_options.is_disabled`) and `get_updates() -> chat ids`.
- 15-second timeout. 429 is retried after `retry_after`, up to 3 times. 401/403 raise `TelegramAuthError`.
- The token is replaced with `***` in every error text, URLs included.
- `api_base` is overridable (`JOBHUNT_TELEGRAM_API_BASE`) so tests can use a local fake server.

**Digest text:**
- Dates and times are shown in the profile's timezone (`candidate.timezone` in `preferences.yaml`, Asia/Ho_Chi_Minh for you), falling back to UTC, using the standard library's `zoneinfo`.
- Salary is shortened per currency: VND in millions ("25–35M VND/month (net)"), others with thousands separators ("72,000–96,000 SGD/year").
- Everything is HTML-escaped. Messages split between postings at 4,096 characters (`len` of the text, as Telegram counts it).

**Daily run:** `make install-timer` renders two units into `~/.config/systemd/user/`:
- the service runs `<repo>/Makefile` targets through the uv shim (`~/.local/share/mise/shims/uv`, resolved at install time with `command -v uv`, so uv upgrades keep working): `collect-email SINCE=2d` (the overlap is harmless thanks to the header pre-check), then `digest`;
- the timer is `OnCalendar=*-*-* 12:00:00 Asia/Ho_Chi_Minh`, `Persistent=true`.

`make uninstall-timer` disables and removes them.

## Dependencies

None new (`urllib`, `json`, `zoneinfo`, `http.server` for the test fake).

## Tasks

Each task is test-first, ends with `make check` passing (store tasks also `make test-db`), a decision note, a commit and a push.

1. **Store: notifications and collection runs.** Migration `0002`; port methods; memory and Postgres implementations; contract tests for unsent postings, marking, a joining job not reviving a sent posting, the lock against two digests, collection runs. `collect email` records a run row, also on failure.
2. **Telegram client.** Against a fake Bot API server on localhost: send, 429 retry, 401, network error, `getUpdates` chat discovery, token never in error text (N7, N8).
3. **Digest text.** Golden tests for normal, empty, capped (30 + "and N more"), multi-source "also on", attribution, collector OK / failed / missing (more than 26 h), HTML escaping, splitting at 4,096 (N4, N5, N6, N9).
4. **CLI.** `jobhunt digest send [--test]`, `jobhunt digest list [--since 7d]`, `jobhunt telegram find-chat`; send-then-mark with nothing marked on failure (N1, N2, N3); `make digest`.
5. **Daily timer.** Unit rendering tests; `make install-timer` / `uninstall-timer` (N10).
6. **Manual check** (needs you): create the bot, put the token in `secrets.env` from a separate terminal, `find-chat`, `--test`, the first real digest of the 19 stored postings, install the timer and check the next run time.

## Risks

- **Telegram HTML is strict:** one unescaped `<` rejects the whole message. All values go through one escape function, and golden tests cover symbols.
- **The timer needs the Postgres container running;** the collector line makes a failure visible in the next digest.
- **First digest:** it sends all 19 stored postings (under the cap of 30), as intended.
