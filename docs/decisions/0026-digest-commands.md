# 0026: Digest and Telegram commands

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md), N1, N2, N3, N8; plan [05](../plans/05-notifications.md) task 4

## Implementation

- `jobhunt digest send`, inside `store.digest_lock()`:
  1. loads unsent postings and the last collection run;
  2. composes the digest in the profile's timezone (`candidate.timezone`, new `load_timezone`, UTC by default);
  3. sends every message;
  4. **only then** calls `mark_sent`, with Telegram's message ids.

  Any failure before the end marks nothing. Empty days also record a digest row (0 postings), which keeps a history of sends. It prints `{"type": "summary", "messages": n, "postings": k}`.
- `digest send --test` sends one line and needs no database. `digest list [--since 7d]` prints postings as JSON lines with `sent`, title, company, URL, sources and local first-seen time. `telegram find-chat` prints the chats that messaged the bot and says where to put the id.
- Token and chat id come from `secrets.env` / environment (`JOBHUNT_TELEGRAM_BOT_TOKEN`, `JOBHUNT_TELEGRAM_CHAT_ID`); the token is redacted as soon as it is loaded. A missing chat id explains the `find-chat` step. `JOBHUNT_TELEGRAM_API_BASE` overrides the API address (tests).
- Exit codes: Telegram errors 3 (as the mail server), and **5 when another digest holds the lock**. Spec 05's edge case said the second digest would send "no new jobs"; with the fail-fast lock from decision 0023 it stops without sending, which avoids a confusing extra message. Spec updated.
- `make digest`.

## Verified

- Tests written first (12 new; 437 in total, 26 skipped without a database), with a fake Telegram client and the in-memory store:
  - N1: 11 postings in one message, header and collector line exact; all marked.
  - N2: the next send says "no new jobs".
  - N3: a failed send exits 3 and leaves all 11 unsent.
  - N8: a bad token exits 3 with the hint and no token shown.
  - Other: busy lock → exit 5 and nothing sent; collector warning after a failed run; `--test` without a database; a missing chat id points to `find-chat`; `digest list` sent flags; `find-chat` output; timezone loading (valid, default, invalid).
- No real message sent yet (task 6). No new dependencies, cost $0.
