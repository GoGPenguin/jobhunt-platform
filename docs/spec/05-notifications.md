# Spec 05: Notifications (daily Telegram digest)

Status: approved 2026-10-20
Depends on: [constitution](constitution.md), [04-dedupe-store](04-dedupe-store.md)
Used by: approval-tracker (buttons and replies, later), observability (collector health)

## User story

As the job seeker, I want one Telegram message a day listing the jobs that are new since the last one, each with a link, so I can check new Vietnam/Asia openings in a minute without opening any job site.

## Scope

In scope:

- A minimal Telegram Bot API client: send messages, plus finding your chat id during setup.
- `jobhunt digest send`: composes the digest from postings not sent before, sends it, then records what was sent.
- Collector run records, so the digest can say whether collection is working.
- A daily run on this machine (systemd user timer): collect, then send the digest, at 12:00 Vietnam time.

Out of scope, for later specs:

- Inline buttons (interested/skip), replies, pasting LinkedIn descriptions, approvals (approval-tracker, spec 02 phase D).
- Ranking, summaries and filtering by market (matcher, job-summary). Until then the digest lists all new postings, newest first.
- Scheduling in Docker Compose or Kubernetes (collector-runtime replaces the timer).

## Decisions (2026-10-20)

| Topic | Decision |
| ----- | -------- |
| Telegram client | Plain Bot API over HTTPS with the standard library (`urllib`, `json`). No new dependency. |
| Scope | Digest only. |
| Content | Every posting not yet sent, newest first; up to 30 shown, then "and N more". |
| Empty day | A short "no new jobs" message, so silence never hides a broken collector. |
| What was sent | Per-job notification records, written only after Telegram confirms every message of the digest. |
| Daily run | systemd user timer on this machine, 12:00 Asia/Ho_Chi_Minh, `Persistent=true` (catches up after the laptop was off). Replaced by collector-runtime. |

## Telegram setup

1. Create a bot with @BotFather and copy its token **into `~/.config/jobhunt/secrets.env` from a separate terminal**, never through the assistant chat: `JOBHUNT_TELEGRAM_BOT_TOKEN=...`.
2. Send any message to the bot from your Telegram account.
3. `jobhunt telegram find-chat` calls `getUpdates` and prints the chat id(s) that messaged the bot; add `JOBHUNT_TELEGRAM_CHAT_ID=...` to `secrets.env`.
4. `jobhunt digest send --test` sends a one-line test message.

The bot only ever sends to the configured chat id. The token is a secret: redacted from logs and errors, including URLs, because the Bot API puts the token in the request path (`/bot<token>/sendMessage`).

## The digest

```text
JobHunt · 12 new jobs · Wed 21 Oct
Collector: last run 11:58, OK (4 emails, 12 new jobs)

1. Senior DevOps Engineer · Lumen Robotics
   Đà Nẵng · hybrid · 25–35M VND/month (net)
   https://www.linkedin.com/jobs/view/1000000101/  (linkedin-email)
2. ...
… and 4 more (see: jobhunt digest list)
```

- **Order:** postings first seen most recently first. The matcher will replace this with fit ranking.
- **Each posting shows:**
  - title and company;
  - location, workplace and salary when known;
  - the representative job's URL;
  - its source, and the attribution text when the source requires one (spec 01).
  - When several sources have the same posting, "also on: …".
- **Formatting:** Telegram HTML mode with every value escaped; link previews off.
- **Length:** a message is at most 4,096 characters, so long digests are split between postings, never inside one.
- **Cap:** 30 postings shown. The rest are counted in "and N more" and **also marked as sent**, so a backlog can't keep growing. They stay queryable (`jobhunt digest list`, below).
- **Empty day:** "JobHunt · no new jobs" plus the collector line.
- **Collector line:** comes from collector run records. If the last run failed, or no run happened in 26 hours, the line becomes a warning ("⚠ last collection failed at 11:58: IMAP login failed").

## What was sent

- New tables (migration `0002`):
  - `digests (id, sent_at, postings, telegram_message_ids)`;
  - `notified_jobs (source, external_id, digest_id, notified_at)`;
  - `collection_runs (id, started_at, finished_at, ok, summary jsonb, error)`.
- **A posting is unsent while none of its jobs is in `notified_jobs`.** A job that joins an already-sent posting later (the same job from a second source) doesn't make it new again; this matches spec 04's `new_postings`.
- Records are written in one transaction **after** Telegram has accepted every message of the digest. If a send fails part-way, nothing is marked, and the next run sends the whole digest again. A rare duplicate is preferred to a lost job.
- `jobhunt collect email` writes one `collection_runs` row per run (success or failure, with its summary or error).
- `jobhunt digest list [--since 7d]` prints postings and whether they were sent, as JSON lines: a way to see the "and N more" ones.

## Daily run

- `make install-timer` writes `~/.config/systemd/user/jobhunt-daily.{service,timer}` and enables the timer: `OnCalendar=*-*-* 12:00:00 Asia/Ho_Chi_Minh`, `Persistent=true`.
- The service collects, then sends the digest. A failed collection doesn't stop the digest; the collector line reports the failure.
- `make uninstall-timer` removes it; `journalctl --user -u jobhunt-daily` shows the logs.
- User timers run while you are logged in. To also run when logged out, `loginctl enable-linger` (optional, not done automatically).
- The Postgres container must be running (Compose `restart: unless-stopped` already restarts it with Docker).

## Acceptance criteria

- **N1 (MVP AC4):** with new postings stored, `jobhunt digest send` delivers one Telegram message listing them, newest first, each with title, company, location and link.
- **N2:** a second `digest send` with nothing new sends "no new jobs" and lists nothing again.
- **N3:** if Telegram rejects the second of two messages, no job is marked as sent, and the next run sends both again.
- **N4:** a digest with more than 4,096 characters is split between postings; every message is within the limit.
- **N5:** more than 30 postings show 30 plus "and N more"; all are marked as sent; `digest list` shows them.
- **N6:** job titles or company names with `<`, `&` or similar are escaped; no message is rejected for bad HTML.
- **N7:** the bot token never appears in logs or errors, including in a failed request's URL.
- **N8:** HTTP 429 from Telegram is retried after `retry_after`; 401 (bad token) exits with code 3 and a hint.
- **N9:** the collector line shows the last run; a failed or missing run (more than 26 h) shows a warning.
- **N10:** `make install-timer` creates the units, `systemctl --user list-timers` shows the next run at 12:00, and `make uninstall-timer` removes them.

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| Laptop off at 12:00 | The timer runs at the next boot or login (`Persistent=true`). |
| Two digests started at once | The second finds the digest lock taken and stops at once with exit code 5, sending nothing (changed 2026-10-20 from "sends no new jobs": fail-fast avoids a confusing extra message). |
| A job joins a sent posting from another source | Not sent again. |
| Posting without a description (LinkedIn) | Shown normally; the description isn't part of the digest. |
| Token revoked | 401: exit 3, "check JOBHUNT_TELEGRAM_BOT_TOKEN". |
| Telegram unreachable | Exit 3; nothing marked; the next run resends. |

## Dependencies

None new.

## Test plan

- Formatting: golden tests for digest text (normal, empty, capped, multi-source, attribution, warning collector line).
- Splitting at 4,096 characters, HTML escaping.
- Telegram client against a fake Bot API server (local HTTP): success, 429 with `retry_after`, 401, network error; token redaction in errors.
- Store contract tests (both stores): unsent postings, marking after send, a joining job not making a posting new, collection runs.
- CLI tests for `digest send`, `--test`, `digest list`, `telegram find-chat`.
- The timer: unit-file content tests; a manual check of `make install-timer` on this machine.
- Manual check: a real digest arrives in your Telegram.
