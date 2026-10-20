"""systemd user units for the daily run on this machine: collect, then send the digest.
See spec 05, "Daily run". Replaced by collector-runtime (scheduled jobs in Compose/Kubernetes).

`make install-timer` / `make uninstall-timer` call `jobhunt timer install|remove` and then
`systemctl --user` to load or unload the units.
"""

import re
from pathlib import Path
from zoneinfo import ZoneInfo

SERVICE = "jobhunt-daily.service"
TIMER = "jobhunt-daily.timer"
DEFAULT_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def render_service(repo: Path, uv: Path) -> str:
    run = f"{uv} run --locked --directory {repo}/apps/jobhunt jobhunt"
    return (
        "[Unit]\n"
        "Description=JobHunt: collect alert emails, then send the Telegram digest\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={repo}\n"
        # "-": a failed collection doesn't stop the digest, whose collector line reports it.
        f"ExecStart=-{run} collect email --since 2d\n"
        f"ExecStart={run} digest send\n"
    )


def render_timer(at: str, tz: ZoneInfo) -> str:
    if not _TIME.match(at):
        raise ValueError(f"digest time {at!r}: use HH:MM, e.g. 12:00")
    return (
        "[Unit]\n"
        f"Description=Daily JobHunt digest at {at} {tz.key}\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar=*-*-* {at}:00 {tz.key}\n"
        "Persistent=true\n"  # run at the next boot or login if the machine was off
        f"Unit={SERVICE}\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def install_units(unit_dir: Path, *, repo: Path, uv: Path, at: str, tz: ZoneInfo) -> list[Path]:
    timer = render_timer(at, tz)  # validate before writing anything
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path, timer_path = unit_dir / SERVICE, unit_dir / TIMER
    service_path.write_text(render_service(repo, uv), encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    return [service_path, timer_path]


def remove_units(unit_dir: Path) -> list[Path]:
    removed = []
    for name in (SERVICE, TIMER):
        path = unit_dir / name
        if path.exists():
            path.unlink()
            removed.append(path)
    return sorted(removed)
