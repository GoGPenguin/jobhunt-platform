import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jobhunt.domain.dead_letter import BuildResult, DeadLetter, build_jobs
from jobhunt.domain.job import ParserInfo

FIXTURES = Path(__file__).parent.parent / "fixtures" / "jobs"
PARSER = ParserInfo(name="greenhouse", version="1.2.0")
RAW_REF = "raw/greenhouse/2026-10-20/batch-7.json"
NOW = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)


def record(name: str = "greenhouse_style", **changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    for key in ("source", "raw_ref", "parser"):  # supplied per batch, not per record
        del data[key]
    return {**data, **changes}


def build(records: list[Any], **kwargs: Any) -> BuildResult:
    return build_jobs(
        records,
        source="greenhouse:lumen-robotics",
        parser=PARSER,
        raw_ref=RAW_REF,
        now=lambda: NOW,
        **kwargs,
    )


# S6: one bad record doesn't stop the batch


def test_invalid_record_becomes_dead_letter_others_build() -> None:
    bad = record(external_id="2")
    bad["salary"]["currency"] = "XYZ"
    result = build([record(external_id="1"), bad, record(external_id="3")])

    assert [job.external_id for job in result.jobs] == ["1", "3"]
    assert len(result.dead_letters) == 1
    letter = result.dead_letters[0]
    assert (letter.source, letter.raw_ref, letter.parser) == (
        "greenhouse:lumen-robotics",
        RAW_REF,
        PARSER,
    )
    assert [(e.loc, e.type) for e in letter.errors] == [("salary.currency", "value_error")]
    assert "XYZ" in letter.errors[0].message
    assert letter.record == bad
    assert letter.failed_at == NOW


def test_batch_fields_fill_every_job() -> None:
    job = build([record()]).jobs[0]
    assert (job.source, job.raw_ref, job.parser) == ("greenhouse:lumen-robotics", RAW_REF, PARSER)


def test_batch_fields_override_record() -> None:
    job = build([record(raw_ref="something-else", source="other")]).jobs[0]
    assert (job.source, job.raw_ref) == ("greenhouse:lumen-robotics", RAW_REF)


def test_non_mapping_record_becomes_dead_letter() -> None:
    result = build([["not", "a", "dict"], record()])
    assert len(result.jobs) == 1
    letter = result.dead_letters[0]
    assert [(e.loc, e.type) for e in letter.errors] == [("", "not_a_mapping")]
    assert letter.record == {"value": "['not', 'a', 'dict']"}


def test_does_not_mutate_records() -> None:
    records = [record(), record(title="")]
    before = copy.deepcopy(records)
    build(records)
    assert records == before


def test_empty_batch() -> None:
    assert build([]) == BuildResult(jobs=(), dead_letters=(), dropped_languages={})


def test_http_allowance_passed_through() -> None:
    plain = record(url="http://jobs.example.com/1")
    assert build([plain]).dead_letters
    assert build([plain], allow_http=True).jobs


def test_dead_letter_serializes_to_json() -> None:
    odd = record(posted_at=datetime(2026, 10, 18, 3, 15, tzinfo=timezone(timedelta(hours=7))))
    odd["title"] = ""
    letter = build([odd]).dead_letters[0]
    restored = DeadLetter.model_validate_json(letter.model_dump_json())
    assert restored.errors == letter.errors
    assert restored.record["posted_at"] == "2026-10-18T03:15:00+07:00"


# S7: posting-language filter


def test_drops_unaccepted_languages_and_counts_them() -> None:
    records = [
        record(external_id="en", language="en"),
        record(external_id="vi", language="vi"),
        record(external_id="ja-1", language="ja"),
        record(external_id="ja-2", language="ja"),
        record(external_id="de", language="de"),
        record(external_id="unknown", language="unknown"),
    ]
    result = build(records, accepted_languages={"vi", "en"})
    assert [job.external_id for job in result.jobs] == ["en", "vi", "unknown"]
    assert result.dropped_languages == {"ja": 2, "de": 1}
    assert result.dead_letters == ()


def test_no_language_filter_keeps_all() -> None:
    result = build([record(language="ja"), record(language="vi")])
    assert len(result.jobs) == 2
    assert result.dropped_languages == {}
