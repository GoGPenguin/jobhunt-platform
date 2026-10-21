"""Compose the daily digest: Telegram HTML text, no I/O. See spec 05, "The digest".

Every value is HTML-escaped (Telegram rejects a whole message for one bad tag). Messages are
split between postings so each stays within Telegram's 4,096-character limit, counted in UTF-16
code units of the HTML, which is never less than what Telegram counts after removing tags.
"""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from jobhunt.domain.job import Job, Salary
from jobhunt.matching.score import Ranked
from jobhunt.store.port import CollectionRun, Posting

MESSAGE_LIMIT = 4096
SHOWN_POSTINGS = 30
STALE_AFTER = timedelta(hours=26)
RANGE_DASH = "\u2013"  # en dash between the two amounts of a range
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # locale-independent names
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Digest:
    messages: list[str]
    postings: list[Posting]  # everything to mark as sent: shown, "and N more", filtered out


def compose(
    ranked: Sequence[Ranked],
    last_run: CollectionRun | None,
    *,
    now: datetime,
    tz: ZoneInfo,
    warnings: Sequence[str] = (),
    shown: int = SHOWN_POSTINGS,
    limit: int = MESSAGE_LIMIT,
) -> Digest:
    """`ranked` in the matcher's order (spec 07). Filtered-out postings aren't shown, only
    counted, but are returned for marking. `warnings` name profile files that failed to load."""
    visible = [r for r in ranked if r.filtered is None]
    count, filtered = len(visible), len(ranked) - len(visible)
    headline = f"{count} new job{'s' if count != 1 else ''}" if count else "no new jobs"
    head = f"<b>JobHunt</b> · {headline} · {_day(now, tz)}"
    head += f" · {filtered} filtered out" if filtered else ""
    head += f"\n{_collector_line(last_run, now, tz)}"
    if warnings:
        files = _e(", ".join(warnings))
        head += f"\n⚠ Profile invalid ({files}): ranked without it; run jobhunt profile check"
    blocks = [_block(n, r) for n, r in enumerate(visible[:shown], start=1)]
    if count > shown:
        blocks.append(f"… and {count - shown} more (see: jobhunt digest list)")
    return Digest(messages=_split(head, blocks, limit), postings=[r.posting for r in ranked])


def telegram_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def format_salary(salary: Salary) -> str:
    lo, hi = salary.min, salary.max
    millions = salary.currency == "VND"
    if lo is not None and hi is not None:
        amount = f"{_amount(lo, millions)}{RANGE_DASH}{_amount(hi, millions)}"
    elif lo is not None:
        amount = f"from {_amount(lo, millions)}"
    else:
        amount = f"up to {_amount(hi or Decimal(0), millions)}"
    text = f"{amount}{'M' if millions else ''} {salary.currency}"
    if salary.period != "unknown":
        text += f"/{salary.period}"
    if salary.basis != "unknown":
        text += f" ({salary.basis})"
    return text


def _amount(value: Decimal, millions: bool) -> str:
    if millions:
        value = value / Decimal(1_000_000)
    value = value.normalize()
    if value == value.to_integral_value():
        return f"{int(value):,}"
    return f"{value:,f}"


def _block(number: int, ranked: Ranked) -> str:
    posting = ranked.posting
    job = posting.representative.job
    why = [*ranked.reasons, *(f"({flag})" for flag in ranked.flags)]
    lines = [
        f"{number}. <b>{_e(job.title)}</b> · {_e(job.company)}",
        "   " + _e(" · ".join([str(ranked.score), *why])),
    ]
    details = [part for part in (_location(job), _workplace(job), _salary(job)) if part]
    if details:
        lines.append("   " + " · ".join(_e(part) for part in details))
    others = sorted({j.job.source for j in posting.jobs} - {job.source})
    origin = job.source + (f", also on: {', '.join(others)}" if others else "")
    lines.append(f"   {_e(job.url)}  ({_e(origin)})")
    if job.attribution:
        lines.append(f"   {_e(job.attribution.text)}")
    return "\n".join(lines)


def _location(job: Job) -> str:
    if not job.locations:
        return job.location_raw or ""
    first = job.locations[0]
    text = ", ".join(part for part in (first.city, first.region, first.country) if part)
    return text + (f" +{len(job.locations) - 1}" if len(job.locations) > 1 else "")


def _workplace(job: Job) -> str:
    return "" if job.workplace == "unknown" else str(job.workplace)


def _salary(job: Job) -> str:
    return format_salary(job.salary) if job.salary else ""


def _collector_line(run: CollectionRun | None, now: datetime, tz: ZoneInfo) -> str:
    if run is None:
        return "⚠ Collector: no run recorded yet"
    if not run.ok:
        error = (run.error or "unknown error")[:200]
        return f"⚠ Collector: last run failed at {_time(run.finished_at, tz)}: {_e(error)}"
    if now - run.finished_at > STALE_AFTER:
        when = f"{_day(run.finished_at, tz)} {_time(run.finished_at, tz)}"
        return f"⚠ Collector: no run since {when}"
    emails, new = run.summary.get("emails", 0), run.summary.get("new", 0)
    return f"Collector: last run {_time(run.finished_at, tz)}, OK ({emails} emails, {new} new jobs)"


def _split(head: str, blocks: list[str], limit: int) -> list[str]:
    """Head, a blank line, then blocks; a new message starts before a block that wouldn't fit.
    One block always fits: the Job model caps every field it shows (title 300, company 200,
    location 500, attribution 300 characters), so a block is never cut, which could break HTML."""
    messages = [head]
    for block in blocks:
        joined = f"{messages[-1]}\n\n{block}"
        if telegram_length(joined) <= limit:
            messages[-1] = joined
        else:
            messages.append(block)
    return messages


def _day(moment: datetime, tz: ZoneInfo) -> str:
    local = moment.astimezone(tz)
    return f"{_DAYS[local.weekday()]} {local.day:02d} {_MONTHS[local.month - 1]}"


def _time(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M")


def _e(text: str) -> str:
    return html.escape(text, quote=False)
