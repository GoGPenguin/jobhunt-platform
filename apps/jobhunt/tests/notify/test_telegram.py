"""Telegram Bot API client against a fake Bot API server on localhost (spec 05, N7, N8)."""

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from jobhunt.notify.telegram import TelegramAuthError, TelegramClient, TelegramError

TOKEN = "123456:FAKE-token-for-tests"  # noqa: S105


@dataclass
class FakeBotApi:
    """Queue of (status, body) replies; records every request."""

    replies: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def api() -> Iterator[FakeBotApi]:
    fake = FakeBotApi()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            fake.requests.append((self.path, json.loads(body)))
            default = (200, {"ok": True, "result": True})
            status, reply = fake.replies.pop(0) if fake.replies else default
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:  # keep test output quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield fake
    server.shutdown()


def client(api: FakeBotApi, sleeps: list[float] | None = None) -> TelegramClient:
    record = sleeps if sleeps is not None else []
    return TelegramClient(TOKEN, api_base=api.url, sleep=record.append)


def test_send_message(api: FakeBotApi) -> None:
    api.replies.append((200, {"ok": True, "result": {"message_id": 42}}))
    assert client(api).send_message("987", "<b>hi</b>") == 42
    path, body = api.requests[0]
    assert path == f"/bot{TOKEN}/sendMessage"
    assert body == {
        "chat_id": "987",
        "text": "<b>hi</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }


def test_retries_after_429(api: FakeBotApi) -> None:
    api.replies += [
        (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}),
        (200, {"ok": True, "result": {"message_id": 1}}),
    ]
    sleeps: list[float] = []
    assert client(api, sleeps).send_message("987", "x") == 1
    assert sleeps == [3]


def test_gives_up_after_repeated_429(api: FakeBotApi) -> None:
    api.replies += [(429, {"ok": False, "parameters": {"retry_after": 1}})] * 4
    with pytest.raises(TelegramError, match="rate limited"):
        client(api).send_message("987", "x")


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_errors_hint_at_token_without_showing_it(api: FakeBotApi, status: int) -> None:
    api.replies.append((status, {"ok": False, "error_code": status, "description": "Unauthorized"}))
    with pytest.raises(TelegramAuthError, match="JOBHUNT_TELEGRAM_BOT_TOKEN") as exc:
        client(api).send_message("987", "x")
    assert TOKEN not in str(exc.value)


def test_bad_request_reports_description(api: FakeBotApi) -> None:
    reply = {"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"}
    api.replies.append((400, reply))
    with pytest.raises(TelegramError, match="can't parse entities"):
        client(api).send_message("987", "<b>")


def test_network_error_never_shows_token() -> None:
    unreachable = TelegramClient(TOKEN, api_base="http://127.0.0.1:1", sleep=lambda s: None)
    with pytest.raises(TelegramError) as exc:
        unreachable.send_message("987", "x")
    assert TOKEN not in str(exc.value)
    assert "api.telegram.org" not in str(exc.value)


def test_find_chats(api: FakeBotApi) -> None:
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 987, "type": "private", "first_name": "Alex"}}},
        {"update_id": 2, "message": {"chat": {"id": 987, "type": "private", "first_name": "Alex"}}},
        {"update_id": 3, "my_chat_member": {"chat": {"id": -5, "type": "group", "title": "Team"}}},
    ]
    api.replies.append((200, {"ok": True, "result": updates}))
    assert client(api).find_chats() == [("987", "Alex (private)"), ("-5", "Team (group)")]


@pytest.mark.parametrize("base", ["http://api.telegram.org", "ftp://127.0.0.1", "file:///etc"])
def test_only_https_except_localhost(base: str) -> None:
    with pytest.raises(ValueError, match="https"):
        TelegramClient(TOKEN, api_base=base)
