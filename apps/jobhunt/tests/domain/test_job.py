import copy
import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jobhunt.domain.job import (
    DESCRIPTION_MAX_CHARS,
    Job,
    SalaryPeriod,
    Workplace,
    external_id_from_url,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "jobs"
FIXTURE_NAMES = ["greenhouse_style", "remote_board", "vietnamese_email"]


def load(name: str = "greenhouse_style") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def error_locs(exc: ValidationError) -> set[tuple[int | str, ...]]:
    return {tuple(e["loc"]) for e in exc.errors()}


def assert_invalid(data: dict[str, Any], loc: tuple[int | str, ...]) -> None:
    with pytest.raises(ValidationError) as exc:
        Job.from_parser(data)
    assert loc in error_locs(exc.value), exc.value


# S1: valid fixtures build


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixtures_build(name: str) -> None:
    job = Job.from_parser(load(name))
    assert job.schema_version == 1
    assert job.collected_at.tzinfo is UTC


def test_vietnamese_email_fixture() -> None:
    job = Job.from_parser(load("vietnamese_email"))
    assert job.description == ""
    assert job.salary is not None
    assert job.salary.min == Decimal(15_000_000)
    assert job.salary.max == Decimal(25_000_000)
    assert job.salary.currency == "VND"
    assert job.locations[0].city == "Đà Nẵng"
    assert job.posted_at is None


# S2: every failing field reported at once


def test_reports_all_errors_together() -> None:
    data = load()
    del data["title"]
    data["salary"]["currency"] = "XYZ"
    data["locations"][0]["country"] = "Vietnam"
    data["posted_at"] = "2026-10-18T03:15:00"  # naive
    with pytest.raises(ValidationError) as exc:
        Job.from_parser(data)
    assert {
        ("title",),
        ("salary", "currency"),
        ("locations", 0, "country"),
        ("posted_at",),
    } <= error_locs(exc.value)


# S4: JSON round-trip and immutability


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_json_round_trip(name: str) -> None:
    job = Job.from_parser(load(name))
    assert Job.from_storage(job.model_dump_json()) == job


def test_frozen() -> None:
    job = Job.from_parser(load())
    with pytest.raises(ValidationError):
        job.title = "Changed"  # type: ignore[misc]
    assert isinstance(job.tags, tuple)
    assert isinstance(job.locations, tuple)


# Normalization applied by the model


def test_text_and_url_normalized() -> None:
    data = load()
    data["title"] = "  " + unicodedata.normalize("NFD", "Kỹ sư   Platform") + " "
    data["url"] = "HTTPS://Boards.Greenhouse.io/lumen/jobs/1?utm_source=x#apply"
    data["description"] = "line one   \n\n\n\nline two"
    data["tags"] = ["DevOps", " devops", "Kubernetes", ""]
    job = Job.from_parser(data)
    assert job.title == "Kỹ sư Platform"
    assert job.url == "https://boards.greenhouse.io/lumen/jobs/1"
    assert job.description == "line one\n\nline two"
    assert job.tags == ("devops", "kubernetes")


def test_datetimes_converted_to_utc() -> None:
    data = load()
    data["posted_at"] = "2026-10-18T10:15:00+07:00"
    assert Job.from_parser(data).posted_at == datetime(2026, 10, 18, 3, 15, tzinfo=UTC)


def test_description_truncated_at_limit() -> None:
    data = load()
    data["description"] = "x" * (DESCRIPTION_MAX_CHARS + 1)
    job = Job.from_parser(data)
    assert len(job.description) == DESCRIPTION_MAX_CHARS
    assert job.description_truncated

    data["description"] = "x" * DESCRIPTION_MAX_CHARS
    assert not Job.from_parser(data).description_truncated


def test_http_only_when_source_allows() -> None:
    data = load()
    data["url"] = "http://jobs.example.com/1"
    assert_invalid(data, ("url",))
    assert Job.from_parser(data, allow_http=True).url == "http://jobs.example.com/1"


def test_stored_http_url_reads_back() -> None:
    data = load()
    data["url"] = "http://jobs.example.com/1"
    job = Job.from_parser(data, allow_http=True)
    assert Job.from_storage(job.model_dump_json()) == job


def test_external_id_from_url() -> None:
    expected = hashlib.sha256(b"https://x.io/j?a=1").hexdigest()
    assert external_id_from_url("HTTPS://X.io/j?a=1&utm_source=mail#top") == expected


# Field rules


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 2),
        (("source",), "Remotive"),
        (("source",), "remotive jobs"),
        (("external_id",), ""),
        (("title",), "   "),
        (("title",), "x" * 301),
        (("company",), "x" * 201),
        (("language",), "vn"),
        (("workplace",), "flexible"),
        (("years_experience_min",), 31),
        (("years_experience_min",), -1),
        (("raw_ref",), ""),
        (("parser", "version"), "1.0"),
        (("salary", "min"), "-1"),
        (("salary", "period"), "fortnight"),
    ],
)
def test_rejects_invalid_field(path: tuple[str, ...], value: object) -> None:
    data = load()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert_invalid(data, path)


def test_rejects_unknown_field_on_parse() -> None:
    data = load()
    data["visa_sponsership"] = True
    assert_invalid(data, ("visa_sponsership",))


def test_rejects_years_min_above_max() -> None:
    data = load()
    data["years_experience_min"], data["years_experience_max"] = 5, 3
    with pytest.raises(ValidationError, match="years_experience_min"):
        Job.from_parser(data)


def test_rejects_salary_without_amounts_or_min_above_max() -> None:
    data = load()
    data["salary"]["min"], data["salary"]["max"] = None, None
    with pytest.raises(ValidationError, match="min or max"):
        Job.from_parser(data)
    data["salary"]["min"], data["salary"]["max"] = "2000", "1000"
    with pytest.raises(ValidationError, match="min"):
        Job.from_parser(data)


def test_accepts_new_salary_periods() -> None:
    data = load()
    for period in ("week", "day", "unknown"):
        data["salary"]["period"] = period
        assert Job.from_parser(data).salary is not None


def test_rejects_empty_location() -> None:
    data = load()
    data["locations"] = [{"city": None, "region": None, "country": None}]
    with pytest.raises(ValidationError, match="city, region or country"):
        Job.from_parser(data)


def test_language_unknown_allowed() -> None:
    data = load()
    data["language"] = "unknown"
    assert Job.from_parser(data).language == "unknown"


@pytest.mark.parametrize("regions", [["APAC"], ["LATAM", "EU"], ["VN", "SG"], ["WORLDWIDE"]])
def test_remote_regions_accepted(regions: list[str]) -> None:
    data = load("remote_board")
    data["remote_regions"] = regions
    assert Job.from_parser(data).remote_regions == tuple(regions)


@pytest.mark.parametrize("region", ["apac", "Asia Pacific", "A", ""])
def test_remote_regions_rejected(region: str) -> None:
    data = load("remote_board")
    data["remote_regions"] = [region]
    assert_invalid(data, ("remote_regions", 0))


def test_posted_at_after_collection_rejected() -> None:
    data = load()
    data["posted_at"] = "2026-10-21T01:00:01Z"  # collected_at + 1 day + 1 s
    with pytest.raises(ValidationError, match="posted_at"):
        Job.from_parser(data)
    data["posted_at"] = "2026-10-21T01:00:00Z"
    assert Job.from_parser(data).posted_at is not None


# Strict on parse, lenient on read


def test_storage_maps_unknown_enum_values_to_unknown() -> None:
    stored = Job.from_parser(load()).model_dump(mode="json")
    stored["workplace"] = "flexible"
    stored["salary"]["period"] = "fortnight"
    job = Job.from_storage(stored)
    assert job.workplace is Workplace.UNKNOWN
    assert job.salary is not None
    assert job.salary.period is SalaryPeriod.UNKNOWN


def test_storage_ignores_unknown_fields() -> None:
    stored = Job.from_parser(load()).model_dump(mode="json")
    stored["added_in_newer_version"] = "x"
    stored["salary"]["also_new"] = 1
    assert Job.from_storage(stored) == Job.from_parser(load())


def test_storage_does_not_mutate_input() -> None:
    stored = Job.from_parser(load()).model_dump(mode="json")
    stored["workplace"] = "flexible"
    before = copy.deepcopy(stored)
    Job.from_storage(stored)
    assert stored == before
