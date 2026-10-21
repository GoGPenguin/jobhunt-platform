"""`jobhunt digest send | list` and `jobhunt telegram find-chat` (spec 05: N1, N2, N3, N8)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from jobhunt.cli import main
from jobhunt.notify.telegram import TelegramAuthError, TelegramError
from jobhunt.store.memory import MemoryJobStore
from jobhunt.store.port import CollectionRun

REPO = Path(__file__).resolve().parents[4]
LINKEDIN = Path(__file__).parent.parent / "fixtures" / "sources" / "linkedin-email"
EMLS = [str(LINKEDIN / case / "input.eml") for case in ("similar-jobs", "recommendations")]
NOW = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
TOKEN = "123456:FAKE-token-for-tests"  # noqa: S105
Capture = pytest.CaptureFixture[str]


class FakeTelegram:
    def __init__(self, fail_on: int | None = None, error: TelegramError | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail_on = fail_on  # 1-based message number that fails
        self.error = error or TelegramError("Telegram sendMessage: 500 server error")

    def send_message(self, chat_id: str, html: str) -> int:
        if self.fail_on == len(self.sent) + 1:
            raise self.error
        self.sent.append((chat_id, html))
        return len(self.sent)

    def find_chats(self) -> list[tuple[str, str]]:
        return [("987", "Alex (private)")]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    (tmp_path / "sources.yaml").write_text((REPO / "config" / "sources.sample.yaml").read_text())
    (tmp_path / "preferences.yaml").write_text(
        "candidate:\n  timezone: Asia/Ho_Chi_Minh\nlanguages:\n  postings: [vi, en]\n"
    )
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        f"JOBHUNT_DB_APP_PASSWORD=app-secret\nJOBHUNT_TELEGRAM_BOT_TOKEN={TOKEN}\n"
        "JOBHUNT_TELEGRAM_CHAT_ID=987\n"
    )
    secrets.chmod(0o600)
    return tmp_path


def run(
    argv: list[str],
    config_dir: Path,
    capsys: Capture,
    store: MemoryJobStore,
    telegram: FakeTelegram,
) -> tuple[int, list[dict[str, Any]], str]:
    code = main(
        [*argv, "--config-dir", str(config_dir)],
        now=lambda: NOW,
        env={},
        open_store=lambda conninfo: store,
        open_telegram=lambda token, api_base: telegram,
    )
    out, err = capsys.readouterr()
    return code, [json.loads(line) for line in out.splitlines()], err


def collected(config_dir: Path, capsys: Capture, store: MemoryJobStore) -> MemoryJobStore:
    run(["collect", "email", "--eml", *EMLS], config_dir, capsys, store, FakeTelegram())
    return store


def test_send_digest_then_nothing_new(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    telegram = FakeTelegram()
    code, lines, _ = run(["digest", "send"], config_dir, capsys, store, telegram)
    assert code == 0
    [(chat, text)] = telegram.sent
    assert chat == "987"
    header, collector = text.splitlines()[:2]
    assert header == "<b>JobHunt</b> · 11 new jobs · Wed 21 Oct"
    assert collector.startswith("Collector: last run 12:00, OK")
    assert "Senior Platform Engineer" in text
    assert lines == [{"type": "summary", "messages": 1, "postings": 11}]
    assert store.unsent_postings() == []

    again = FakeTelegram()
    run(["digest", "send"], config_dir, capsys, store, again)
    [(_, text)] = again.sent
    assert text.startswith("<b>JobHunt</b> · no new jobs")


def test_failed_send_marks_nothing(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    code, _, err = run(["digest", "send"], config_dir, capsys, store, FakeTelegram(fail_on=1))
    assert code == 3
    assert "500 server error" in err
    assert len(store.unsent_postings()) == 11


def test_bad_token_exits_3_with_hint(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    auth = TelegramAuthError("Telegram sendMessage: HTTP 401; check JOBHUNT_TELEGRAM_BOT_TOKEN")
    code, _, err = run(["digest", "send"], config_dir, capsys, store, FakeTelegram(1, auth))
    assert code == 3
    assert "JOBHUNT_TELEGRAM_BOT_TOKEN" in err
    assert TOKEN not in err


def test_second_digest_at_the_same_time_is_refused(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    telegram = FakeTelegram()
    with store.digest_lock():
        code, _, err = run(["digest", "send"], config_dir, capsys, store, telegram)
    assert code == 5
    assert "another digest" in err
    assert telegram.sent == []


def test_collector_warning_when_last_run_failed(config_dir: Path, capsys: Capture) -> None:
    store = MemoryJobStore()
    failed = CollectionRun(NOW - timedelta(minutes=5), NOW - timedelta(minutes=4), ok=False,
                           error="IMAP login failed")  # fmt: skip
    store.record_collection_run(failed)
    telegram = FakeTelegram()
    run(["digest", "send"], config_dir, capsys, store, telegram)
    assert "⚠ Collector: last run failed at 11:56: IMAP login failed" in telegram.sent[0][1]


def test_test_message_needs_no_database(config_dir: Path, capsys: Capture) -> None:
    (config_dir / "secrets.env").write_text(
        f"JOBHUNT_TELEGRAM_BOT_TOKEN={TOKEN}\nJOBHUNT_TELEGRAM_CHAT_ID=987\n"
    )
    telegram = FakeTelegram()
    code, _, _ = run(["digest", "send", "--test"], config_dir, capsys, MemoryJobStore(), telegram)
    assert code == 0
    assert telegram.sent == [("987", "JobHunt test message: the bot can reach this chat. 12:00")]


def test_missing_chat_id_points_to_find_chat(config_dir: Path, capsys: Capture) -> None:
    (config_dir / "secrets.env").write_text(f"JOBHUNT_TELEGRAM_BOT_TOKEN={TOKEN}\n")
    args = ["digest", "send", "--test"]
    code, _, err = run(args, config_dir, capsys, MemoryJobStore(), FakeTelegram())
    assert code == 2
    assert "jobhunt telegram find-chat" in err


def test_digest_list(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    run(["digest", "send"], config_dir, capsys, store, FakeTelegram())
    args = ["digest", "list", "--since", "7d"]
    code, lines, _ = run(args, config_dir, capsys, store, FakeTelegram())
    assert code == 0
    postings = [line for line in lines if line["type"] == "posting"]
    assert len(postings) == 11
    assert all(p["sent"] for p in postings)
    assert {"title", "company", "url", "sources", "first_seen_at"} <= set(postings[0])


def test_find_chat(config_dir: Path, capsys: Capture) -> None:
    args = ["telegram", "find-chat"]
    code, lines, err = run(args, config_dir, capsys, MemoryJobStore(), FakeTelegram())
    assert code == 0
    assert lines == [{"type": "chat", "chat_id": "987", "name": "Alex (private)"}]
    assert "JOBHUNT_TELEGRAM_CHAT_ID" in err


# Ranking in the digest (spec 07, M9)


def test_digest_list_has_score_and_reasons(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    args = ["digest", "list", "--since", "7d"]
    _, lines, _ = run(args, config_dir, capsys, store, FakeTelegram())
    first = lines[0]
    assert {"score", "reasons", "flags", "filtered", "sent"} <= set(first)
    scores = [line["score"] for line in lines if line["type"] == "posting"]
    assert scores == sorted(scores, reverse=True)  # no flags in this profile: plain score order


def test_broken_master_cv_still_sends_with_warning(config_dir: Path, capsys: Capture) -> None:
    store = collected(config_dir, capsys, MemoryJobStore())
    (config_dir / "master_cv.yaml").write_text("schema_version: 1\nprofile: [not, a, mapping]\n")
    telegram = FakeTelegram()
    code, _, err = run(["digest", "send"], config_dir, capsys, store, telegram)
    assert code == 0
    text = telegram.sent[0][1]
    assert "⚠ Profile invalid (master_cv.yaml)" in text
    assert "11 new jobs" in text
    assert "master_cv.yaml" in err
