"""Turn a batch of parser records into jobs, dead letters and dropped-language counts.

See docs/spec/01-canonical-job-schema.md, "Validation and invalid records".
"""

from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from jobhunt.domain.job import Job, ParserInfo, UtcDatetime
from jobhunt.domain.language import UNKNOWN


class FieldError(BaseModel):
    model_config = ConfigDict(frozen=True)

    loc: str  # dotted path, e.g. "salary.currency"; "" for the whole record
    message: str
    type: str


class DeadLetter(BaseModel):
    """A record that failed validation, kept with everything needed to debug it."""

    model_config = ConfigDict(frozen=True)

    source: str
    raw_ref: str
    parser: ParserInfo
    errors: tuple[FieldError, ...]
    record: dict[str, Any]  # what the parser produced
    failed_at: UtcDatetime


@dataclass(frozen=True)
class BuildResult:
    jobs: tuple[Job, ...]
    dead_letters: tuple[DeadLetter, ...]
    dropped_languages: dict[str, int]  # posting language -> jobs dropped by the language filter


def build_jobs(
    records: Iterable[object],
    *,
    source: str,
    parser: ParserInfo,
    raw_ref: str,
    accepted_languages: Collection[str] | None = None,
    allow_http: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BuildResult:
    """Validate every record from one raw payload. Never stops on a bad record.

    `source`, `parser` and `raw_ref` describe the whole batch and override any values in the
    records. With `accepted_languages` (from the profile), valid jobs in other languages are
    dropped and counted; jobs whose language is "unknown" are always kept.
    """
    jobs: list[Job] = []
    dead_letters: list[DeadLetter] = []
    dropped: Counter[str] = Counter()

    def dead_letter(errors: tuple[FieldError, ...], record: dict[str, Any]) -> DeadLetter:
        return DeadLetter(
            source=source, raw_ref=raw_ref, parser=parser, errors=errors, record=record,
            failed_at=now(),
        )  # fmt: skip

    for record in records:
        if not isinstance(record, Mapping):
            error = FieldError(loc="", message="record is not a mapping", type="not_a_mapping")
            dead_letters.append(dead_letter((error,), {"value": repr(record)}))
            continue
        batch_fields = {"source": source, "raw_ref": raw_ref, "parser": parser}
        try:
            job = Job.from_parser({**record, **batch_fields}, allow_http=allow_http)
        except ValidationError as exc:
            errors = tuple(
                FieldError(loc=".".join(str(p) for p in e["loc"]), message=e["msg"], type=e["type"])
                for e in exc.errors()
            )
            dead_letters.append(dead_letter(errors, dict(record)))
            continue
        if (
            accepted_languages is not None
            and job.language != UNKNOWN
            and job.language not in accepted_languages
        ):
            dropped[job.language] += 1
            continue
        jobs.append(job)

    return BuildResult(tuple(jobs), tuple(dead_letters), dict(dropped))
