from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from jobhunt.sources.parsers.linkedin_email import parse, parse_location
from jobhunt.sources.raw import RawPayload

FETCHED = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
SEP = "---------------------------------------------------------"


def view(job_id: int) -> str:
    return f"View job: https://www.linkedin.com/comm/jobs/view/{job_id}/?trk=eml-view_job"


def email_payload(text: str | None, html: str = "<p>html</p>") -> RawPayload:
    msg = EmailMessage()
    msg["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    msg["Message-ID"] = "<unit@example.com>"
    msg["Subject"] = "Jobs for you"
    if text is None:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(text, cte="quoted-printable")
        msg.add_alternative(html, subtype="html")
    return RawPayload.from_email(msg.as_bytes(), fetched_at=FETCHED)


def records(text: str | None) -> list[dict[str, Any]]:
    return parse(email_payload(text))


def test_block_becomes_record() -> None:
    text = f"Platform Engineer\nLumen Robotics\nĐà Nang\n{view(1000000001)}\n\n{SEP}\n"
    [record] = records(text)
    assert record["external_id"] == "1000000001"
    assert record["url"] == "https://www.linkedin.com/jobs/view/1000000001/"
    assert (record["title"], record["company"]) == ("Platform Engineer", "Lumen Robotics")
    assert record["locations"] == [{"city": "Đà Nang"}]
    assert record["location_raw"] == "Đà Nang"
    assert record["description"] == ""
    assert record["collected_at"] == "2026-10-20T01:00:00+00:00"
    assert record["workplace"] == "unknown"


def test_header_line_and_footer_are_not_jobs() -> None:
    text = (
        "Jobs similar to Platform Engineer at Lumen Robotics "
        "https://www.linkedin.com/comm/jobs/view/1000000009?trk=x\n\n      \n"
        f"Cloud Engineer\nNorthwind Cloud\nVietnam\n{view(1000000002)}\n\n{SEP}\n\n"
        "See all jobs https://www.linkedin.com/comm/jobs/search\n\n"
        "This email was intended for Alex Example (Example University)\n"
    )
    assert [r["external_id"] for r in records(text)] == ["1000000002"]


def test_badges_and_duplicates() -> None:
    text = (
        "Remote jobs\nhttps://www.linkedin.com/comm/jobs/search-results/?keywords=devops\n\n"
        f"SRE\nContoso Labs\nHanoi\nApply with resume & profile\n{view(1000000003)}\n\n{SEP}\n\n"
        "View all jobs: https://www.linkedin.com/comm/jobs/search\n\nAWS jobs\n"
        "https://www.linkedin.com/comm/jobs/search\n\n"
        f"SRE\nContoso Labs\nHanoi\n{view(1000000003)}\n\n{SEP}\n"
    )
    [record] = records(text)
    assert record["extra"]["badges"] == ["Apply with resume & profile"]


def test_badge_without_location_is_not_read_as_location() -> None:
    text = f"SRE\nContoso Labs\nActively recruiting\n{view(1000000004)}\n"
    [record] = records(text)
    assert record["locations"] == []
    assert record["location_raw"] is None
    assert record["extra"]["badges"] == ["Actively recruiting"]


def test_vietnamese_title_detected_short_english_unknown() -> None:
    text = (
        f"Kỹ sư DevOps (Junior)\nSông Hàn Software\nĐà Nang\n{view(1000000005)}\n\n{SEP}\n\n"
        f"DevOps Engineer\nNorthwind Cloud\nHanoi\n{view(1000000006)}\n"
    )
    assert [r["language"] for r in records(text)] == ["vi", "unknown"]


def test_email_kind_from_footer() -> None:
    text = (
        f"SRE\nContoso Labs\nHanoi\n{view(1000000007)}\n\n{SEP}\n\n"
        "You are receiving Jobs You Might Be Interested In emails.\n"
    )
    assert records(text)[0]["extra"]["email_kind"] == "Jobs You Might Be Interested In"


def test_no_plain_text_part_gives_no_records() -> None:
    assert records(None) == []


def test_block_missing_company_still_emitted_for_validation() -> None:
    [record] = records(f"Lonely Title\n{view(1000000008)}\n")
    assert record["title"] == "Lonely Title"
    assert "company" not in record  # build_jobs turns this into a dead letter


@pytest.mark.parametrize(
    ("text", "locations", "workplace"),
    [
        ("Đà Nang", [{"city": "Đà Nang"}], "unknown"),
        ("Vietnam", [{"country": "VN"}], "unknown"),
        ("Hanoi Capital Region", [{"region": "Hanoi Capital Region"}], "unknown"),
        ("Ho Chi Minh City (Hybrid)", [{"city": "Ho Chi Minh City"}], "hybrid"),
        ("Singapore, Singapore", [{"city": "Singapore", "country": "SG"}], "unknown"),
        ("Tokyo, Tokyo, Japan (On-site)", [{"city": "Tokyo", "region": "Tokyo", "country": "JP"}],
         "onsite"),
        ("Vietnam (Remote)", [{"country": "VN"}], "remote"),
        ("Remote", [], "remote"),
    ],
)  # fmt: skip
def test_parse_location(text: str, locations: list[dict[str, str]], workplace: str) -> None:
    assert parse_location(text) == (locations, workplace)
