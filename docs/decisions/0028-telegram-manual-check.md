# 0028: Telegram digest end to end, timer installed

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md), N1, N10; plan [05](../plans/05-notifications.md) task 6

## Manual check

1. The user created the bot and put its token in `secrets.env`. The first `jobhunt telegram find-chat` found no chats. `getMe` showed the token belongs to `@jobhun4_bot`, and `getWebhookInfo` showed no webhook and 0 pending updates: the first message had gone to another bot. After the user messaged `@jobhun4_bot`, `find-chat` returned one private chat, whose id was added to `secrets.env` (not a secret; file kept at mode 600).
2. `jobhunt digest send --test`: exit 0, test message delivered.
3. `make collect-email SINCE=2d` (0 new emails, a successful collection run recorded), then `make digest`: **1 message with all 19 stored postings**, marked as sent. MVP acceptance criterion AC4 (daily Telegram digest of new jobs) works end to end.
4. `make install-timer`: units written, timer enabled and active; `list-timers` shows the next run Wed 2026-10-21 12:00 +07.
5. The collection step was run under systemd's own environment (`systemd-run --user --wait --pipe`) with `--dry-run`: exit 0, Gmail read. The unit's uv path, the virtualenv and the secrets work without the interactive shell. The digest step wasn't triggered, to avoid sending an extra "no new jobs" message; the first scheduled run will exercise it.

## State left on this machine

- A systemd user timer `jobhunt-daily.timer` (daily 12:00 Asia/Ho_Chi_Minh, `Persistent=true`); remove with `make uninstall-timer`. It runs while the user is logged in (linger not enabled, as specified).
- The Postgres container from spec 04 (`restart: unless-stopped`).
- Cost $0.
