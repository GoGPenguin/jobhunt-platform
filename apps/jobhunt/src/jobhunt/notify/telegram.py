"""Minimal Telegram Bot API client, standard library only (spec 05, plan 05 task 2).

The Bot API puts the token in the request path (/bot<token>/method), so every error message is
scrubbed of it, and request URLs are never logged.
"""

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_API_BASE = "https://api.telegram.org"
TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
_AUTH_HINT = "check JOBHUNT_TELEGRAM_BOT_TOKEN in ~/.config/jobhunt/secrets.env"


class TelegramError(RuntimeError):
    """A Bot API call failed. The message never contains the token."""


class TelegramAuthError(TelegramError):
    """The token was rejected (revoked, mistyped) or the bot can't reach the chat."""


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parts = urlsplit(api_base)
        local = parts.hostname in ("127.0.0.1", "localhost")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise ValueError(f"Telegram API base must be https (http on localhost): {api_base}")
        self._token = token
        self._base = api_base.rstrip("/")
        self._sleep = sleep

    def send_message(self, chat_id: str, html: str) -> int:
        """Send one HTML message without link previews; returns Telegram's message id."""
        result = self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": html,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )
        return int(result["message_id"])

    def find_chats(self) -> list[tuple[str, str]]:
        """(chat id, description) of chats that recently messaged the bot, for setup."""
        chats: dict[str, str] = {}
        for update in self._call("getUpdates", {"timeout": 0}):
            for kind in ("message", "my_chat_member", "edited_message", "channel_post"):
                chat = update.get(kind, {}).get("chat")
                if chat:
                    name = chat.get("title") or chat.get("first_name") or chat.get("username")
                    chats.setdefault(str(chat["id"]), f"{name or '?'} ({chat.get('type', '?')})")
        return list(chats.items())

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        request = Request(  # noqa: S310 - scheme checked in __init__
            f"{self._base}/bot{self._token}/{method}",
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for _ in range(MAX_RETRIES + 1):
            try:
                with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                    payload = json.load(response)
            except HTTPError as exc:
                payload = _json_or_empty(exc)
                if exc.code == 429:
                    self._sleep(float(payload.get("parameters", {}).get("retry_after", 1)))
                    continue
                if exc.code in (401, 403, 404):
                    message = f"Telegram {method}: HTTP {exc.code}; {_AUTH_HINT}"
                    raise TelegramAuthError(message) from None
                raise self._error(method, _describe(payload, exc)) from None
            except (URLError, OSError, ValueError) as exc:
                raise self._error(method, str(exc)) from None
            if not payload.get("ok"):
                raise self._error(method, _describe(payload, None))
            return payload["result"]
        raise TelegramError(f"Telegram {method}: rate limited {MAX_RETRIES + 1} times, giving up")

    def _error(self, method: str, detail: str) -> TelegramError:
        return TelegramError(f"Telegram {method}: {detail}".replace(self._token, "***"))


def _json_or_empty(exc: HTTPError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.read() or b"{}")
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _describe(payload: dict[str, Any], exc: HTTPError | None) -> str:
    code = payload.get("error_code") or (exc.code if exc else "?")
    return f"{code} {payload.get('description', 'no description')}"
