"""systemd user units for the daily run (spec 05, N10)."""

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jobhunt.notify.timer import (
    SERVICE,
    TIMER,
    install_units,
    remove_units,
    render_service,
    render_timer,
)

REPO = Path("/home/alex/jobhunt-platform")
UV = Path("/home/alex/.local/share/mise/installs/uv/latest/.mise-bins/uv")


def test_service_collects_then_sends_even_if_collection_fails() -> None:
    service = render_service(REPO, UV)
    assert "Type=oneshot" in service
    run = f"{UV} run --locked --directory {REPO}/apps/jobhunt jobhunt"
    collect = f"ExecStart=-{run} collect email --since 2d"  # "-": a failure doesn't stop the unit
    send = f"ExecStart={run} digest send"
    lines = service.splitlines()
    assert lines.index(collect) < lines.index(send)


def test_timer_runs_daily_in_profile_timezone_and_catches_up() -> None:
    timer = render_timer("12:00", ZoneInfo("Asia/Ho_Chi_Minh"))
    assert "OnCalendar=*-*-* 12:00:00 Asia/Ho_Chi_Minh" in timer.splitlines()
    assert "Persistent=true" in timer.splitlines()
    assert f"Unit={SERVICE}" in timer.splitlines()
    assert "WantedBy=timers.target" in timer.splitlines()


@pytest.mark.parametrize("at", ["12", "25:00", "noon", "12:60"])
def test_bad_time_rejected(at: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        render_timer(at, ZoneInfo("UTC"))


def test_install_and_remove(tmp_path: Path) -> None:
    written = install_units(tmp_path, repo=REPO, uv=UV, at="07:30", tz=ZoneInfo("UTC"))
    assert sorted(p.name for p in written) == sorted([SERVICE, TIMER])
    assert "OnCalendar=*-*-* 07:30:00 UTC" in (tmp_path / TIMER).read_text()
    assert remove_units(tmp_path) == sorted(written)
    assert list(tmp_path.iterdir()) == []
    assert remove_units(tmp_path) == []  # nothing left: harmless
