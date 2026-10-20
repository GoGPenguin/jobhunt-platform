# 0027: Daily systemd user timer

Date: 2026-10-20
Spec: [05-notifications](../spec/05-notifications.md), N10, "Daily run"; plan [05](../plans/05-notifications.md) task 5

## Implementation

- `jobhunt timer install --uv PATH --repo PATH [--at 12:00]` writes `jobhunt-daily.service` and `jobhunt-daily.timer` to `~/.config/systemd/user/`; `jobhunt timer remove` deletes them. `make install-timer` / `make uninstall-timer` add the `systemctl --user` steps (daemon-reload, enable/disable `--now`, list-timers).
- **Service:** `Type=oneshot`, two `ExecStart`s run in order: `collect email --since 2d`, then `digest send`. The first is prefixed with `-`, so a failed collection doesn't stop the digest, whose collector line reports the failure (spec 05). The 2-day window overlaps on purpose; the header pre-check makes re-seen mail free.
- **Timer:** `OnCalendar=*-*-* HH:MM:00 <tz>`, with the timezone from `preferences.yaml` (`candidate.timezone`) and the time from `--at` / `DIGEST_TIME` (default 12:00, as decided). `Persistent=true` catches up after the machine was off.
- **uv path:** written as resolved by `command -v uv` at install time. The plan said the mise shim; on this machine `command -v uv` gives `~/.local/share/mise/installs/uv/latest/.mise-bins/uv`, a symlink through `latest`, so uv upgrades keep it valid. Checked to run with an empty environment (`env -i HOME=…`), as systemd services start almost without one.
- The time is validated (`HH:MM`) before any file is written.

## Verified

- Tests written first (7 new; 444 in total): service command order and the `-` prefix, timer calendar/persistence/install section, invalid times, install and remove (including removing when nothing is installed).
- Units rendered for this machine into a scratch directory: `systemd-analyze --user verify` passed (its only warning concerns an unrelated system unit), and `systemd-analyze calendar` gives the next run as Wed 2026-10-21 12:00 +07 (05:00 UTC).
- The real installation happens in task 6. No new dependencies, cost $0.
