# 0024: Telegram Bot API client

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md), N7, N8; plan [05](../plans/05-notifications.md) task 2

## Implementation

- `jobhunt.notify.telegram.TelegramClient(token, api_base=..., sleep=...)`, standard library only (`urllib`, `json`), as decided for spec 05.
- `send_message(chat_id, html)` posts `sendMessage` with `parse_mode=HTML` and `link_preview_options.is_disabled`, and returns the message id. `find_chats()` reads `getUpdates` and lists the chats that messaged the bot (for setup).
- **Errors:**
  - 429 waits `retry_after` and retries, up to 3 times;
  - 401/403/404 (Telegram answers 404 for a malformed token) raise `TelegramAuthError` with a hint to check `JOBHUNT_TELEGRAM_BOT_TOKEN`;
  - other failures raise `TelegramError` with Telegram's description.
- **The token is never shown:** errors are built without the URL and scrubbed of the token anyway (network errors can include it).
- `api_base` must be `https`, with `http` allowed only for `127.0.0.1`/`localhost`, so the test fake can't become a way to send the token in clear text.
- 15-second timeout; `sleep` is injectable so retry tests don't wait.

## Verified

- Tests written first, against a fake Bot API server on localhost (12 new; 407 in total). They cover:
  - the exact request (path, JSON body);
  - a 429 retry honouring `retry_after`, and giving up after repeated 429s;
  - 401/403/404 → auth error with no token in the message;
  - a 400 description passed through;
  - a refused connection with no token in the message;
  - chat discovery deduplicated across updates;
  - non-https API bases rejected.
- No real Telegram call yet (task 6). No new dependencies, cost $0.
