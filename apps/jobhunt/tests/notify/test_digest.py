"""Digest text (spec 05: N4, N5, N6, N9). Pure functions, exact expected text."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from jobhunt.domain.job import Job, Salary
from jobhunt.matching.score import Ranked
from jobhunt.notify.digest import compose, format_salary, telegram_length
from jobhunt.store.fingerprint import fingerprint
from jobhunt.store.port import CollectionRun, Posting, StoredJob

HCM = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)  # Wed 21 Oct, 12:00 in Ho Chi Minh City
FIXTURES = Path(__file__).parent.parent / "fixtures" / "jobs"
OK_RUN = CollectionRun(
    started_at=NOW - timedelta(minutes=2, seconds=5),
    finished_at=NOW - timedelta(minutes=2),
    ok=True,
    summary={"emails": 4, "new": 12},
)


def job(name: str = "greenhouse_style", **changes: Any) -> Job:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")) | changes
    return Job.from_parser(data)


def posting(*jobs: Job, seen: datetime = NOW - timedelta(hours=1)) -> Posting:
    stored = tuple(StoredJob(j, fingerprint(j.company, j.title), seen, seen, seen) for j in jobs)
    return Posting(stored[0].fingerprint, frozenset(), stored)


def ranked(p: Posting, *, flags: tuple[str, ...] = (), filtered: str | None = None) -> Ranked:
    return Ranked(p, 80, ("title ✓", "vietnam (1st)"), flags, filtered)


def text(postings: list[Posting], run: CollectionRun | None = OK_RUN, **kwargs: Any) -> str:
    items = [ranked(p) for p in postings]
    return "\n".join(compose(items, run, now=NOW, tz=HCM, **kwargs).messages)


def test_normal_digest() -> None:
    linkedin = job(
        "vietnamese_email",
        source="linkedin-email",
        external_id="1000000101",
        url="https://www.linkedin.com/jobs/view/1000000101/",
        workplace="hybrid",
    )
    board = job("remote_board")
    assert text([posting(linkedin), posting(board)]) == (
        "<b>JobHunt</b> · 2 new jobs · Wed 21 Oct\n"
        "Collector: last run 11:58, OK (4 emails, 12 new jobs)\n"
        "\n"
        "1. <b>Kỹ sư DevOps (Junior)</b> · Công ty TNHH Phần mềm Sông Hàn\n"
        "   80 · title ✓ · vietnam (1st)\n"
        "   Đà Nẵng, VN · hybrid · 15–25M VND/month (net)\n"
        "   https://www.linkedin.com/jobs/view/1000000101/  (linkedin-email)\n"
        "\n"
        "2. <b>Site Reliability Engineer</b> · Northwind Cloud\n"
        "   80 · title ✓ · vietnam (1st)\n"
        "   APAC only · remote\n"
        "   https://remotive.com/remote-jobs/devops/site-reliability-engineer-1987654  (remotive)\n"
        "   Job listing from Remotive"
    )


def test_empty_day() -> None:
    assert text([]) == (
        "<b>JobHunt</b> · no new jobs · Wed 21 Oct\n"
        "Collector: last run 11:58, OK (4 emails, 12 new jobs)"
    )


@pytest.mark.parametrize(
    ("run", "line"),
    [
        (None, "⚠ Collector: no run recorded yet"),
        (CollectionRun(NOW - timedelta(minutes=3), NOW - timedelta(minutes=2), ok=False,
                       error="IMAP login to imap.gmail.com failed <b>"),
         "⚠ Collector: last run failed at 11:58: IMAP login to imap.gmail.com failed &lt;b&gt;"),
        (CollectionRun(NOW - timedelta(hours=30), NOW - timedelta(hours=30), ok=True),
         "⚠ Collector: no run since Tue 20 Oct 06:00"),
    ],
)  # fmt: skip
def test_collector_warnings(run: CollectionRun | None, line: str) -> None:
    assert text([], run).splitlines()[1] == line


def test_escaping() -> None:
    tricky = job(title="C++ <Senior> & Lead", company="R&D <Labs>")
    first_line = text([posting(tricky)]).splitlines()[3]
    assert first_line == "1. <b>C++ &lt;Senior&gt; &amp; Lead</b> · R&amp;D &lt;Labs&gt;"


def test_url_ampersands_escaped() -> None:
    linked = job(url="https://boards.greenhouse.io/x/jobs/1?gh_src=a&b=c")
    assert "https://boards.greenhouse.io/x/jobs/1?b=c&amp;gh_src=a" in text([posting(linked)])


def test_multi_source_posting() -> None:
    board = job()
    alert = job(source="linkedin-email", external_id="li-9", description="",
                url="https://www.linkedin.com/jobs/view/9/")  # fmt: skip
    lines = text([posting(alert, board)]).splitlines()
    assert lines[6] == (
        "   https://boards.greenhouse.io/lumenrobotics/jobs/4012345  "
        "(greenhouse:lumen-robotics, also on: linkedin-email)"
    )


def test_cap_and_more() -> None:
    many = [ranked(posting(job(external_id=str(n), title=f"Job {n}"))) for n in range(35)]
    digest = compose(many, OK_RUN, now=NOW, tz=HCM)
    full = "\n".join(digest.messages)
    assert "30. <b>Job 29</b>" in full
    assert "31." not in full
    assert full.endswith("… and 5 more (see: jobhunt digest list)")
    assert len(digest.postings) == 35  # all marked as sent


def test_long_digest_splits_between_postings() -> None:
    long_title = "Platform Engineer " + "x" * 250
    many = [ranked(posting(job(external_id=str(n), title=f"{n} {long_title}"))) for n in range(30)]
    digest = compose(many, OK_RUN, now=NOW, tz=HCM)
    assert len(digest.messages) > 1
    assert all(telegram_length(m) <= 4096 for m in digest.messages)
    lines = [line for message in digest.messages for line in message.splitlines()]
    numbered = [line for line in lines if line[:3].strip(". ").isdigit()]
    assert len(numbered) == 30  # every posting complete, none cut
    for message in digest.messages[1:]:
        assert message.split(". ", 1)[0].isdigit()  # continuations start at a posting


def test_telegram_length_counts_utf16() -> None:
    assert telegram_length("abc") == 3
    assert telegram_length("Đà Nẵng") == 7
    assert telegram_length("🚀") == 2


@pytest.mark.parametrize(
    ("salary", "shown"),
    [
        ({"min": "15000000", "max": "25000000", "currency": "VND", "period": "month",
          "basis": "net"}, "15–25M VND/month (net)"),
        ({"min": "25500000", "currency": "VND", "period": "month", "basis": "gross"},
         "from 25.5M VND/month (gross)"),
        ({"max": "2000", "currency": "USD", "period": "month", "basis": "unknown"},
         "up to 2,000 USD/month"),
        ({"min": "72000", "max": "96000", "currency": "SGD", "period": "year", "basis": "gross"},
         "72,000–96,000 SGD/year (gross)"),
        ({"min": "45.5", "currency": "EUR", "period": "hour", "basis": "unknown"},
         "from 45.5 EUR/hour"),
        ({"min": "1000", "currency": "USD", "period": "unknown", "basis": "unknown"},
         "from 1,000 USD"),
    ],
)  # fmt: skip
def test_format_salary(salary: dict[str, Any], shown: str) -> None:
    assert format_salary(Salary.model_validate(salary)) == shown


def test_decimal_noise_is_trimmed() -> None:
    salary = Salary(min=Decimal("1500.00"), currency="USD", period="month", basis="net")
    assert format_salary(salary) == "from 1,500 USD/month (net)"


# Ranking (spec 07, M9)


def test_filtered_postings_are_counted_not_shown_but_marked() -> None:
    kept = ranked(posting(job(title="Platform Engineer")))
    fabrikam = posting(job(title="Sales Ops", company="Fabrikam"))
    dropped = ranked(fabrikam, filtered="excluded company")
    digest = compose([kept, dropped], OK_RUN, now=NOW, tz=HCM)
    full = "\n".join(digest.messages)
    assert full.startswith("<b>JobHunt</b> · 1 new job · Wed 21 Oct · 1 filtered out\n")
    assert "Fabrikam" not in full
    assert [p.representative.job.company for p in digest.postings] == ["Lumen Robotics", "Fabrikam"]


def test_only_filtered_postings() -> None:
    dropped = ranked(posting(job(company="Fabrikam")), filtered="excluded company")
    first = compose([dropped], OK_RUN, now=NOW, tz=HCM).messages[0].splitlines()[0]
    assert first == "<b>JobHunt</b> · no new jobs · Wed 21 Oct · 1 filtered out"


def test_flags_are_shown_on_the_reasons_line() -> None:
    flagged = ranked(posting(job()), flags=("excluded: sales", "below minimum salary"))
    reasons = "\n".join(compose([flagged], OK_RUN, now=NOW, tz=HCM).messages).splitlines()[4]
    assert reasons == "   80 · title ✓ · vietnam (1st) · (excluded: sales) · (below minimum salary)"


def test_order_is_kept_as_ranked() -> None:
    first, second = posting(job(title="B Job")), posting(job(title="A Job", external_id="2"))
    full = "\n".join(compose([ranked(first), ranked(second)], OK_RUN, now=NOW, tz=HCM).messages)
    assert full.index("B Job") < full.index("A Job")


def test_profile_warning_line() -> None:
    digest = compose([], OK_RUN, now=NOW, tz=HCM, warnings=["master_cv.yaml"])
    assert digest.messages[0].splitlines()[2] == (
        "⚠ Profile invalid (master_cv.yaml): ranked without it; run jobhunt profile check"
    )
