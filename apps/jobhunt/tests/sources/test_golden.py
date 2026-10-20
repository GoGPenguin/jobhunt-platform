"""Golden tests: every tests/fixtures/sources/<parser>/<case>/ with an input.* file must parse to
exactly its expected.json. Adding a case needs no code. Regenerate with `make golden` and review
the diff."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import jobhunt.sources.parsers  # noqa: F401 - registers the parsers
from jobhunt.domain.dead_letter import build_jobs
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY

GOLDEN = Path(__file__).parent.parent / "fixtures" / "sources"
FETCHED = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
UPDATE = os.environ.get("JOBHUNT_UPDATE_GOLDEN") == "1"
CASES = sorted(p for p in GOLDEN.glob("*/*") if p.is_dir())


def load_payload(path: Path) -> RawPayload:
    if path.suffix == ".eml":
        return RawPayload.from_email(path.read_bytes(), fetched_at=FETCHED)
    raise ValueError(f"no loader for {path.suffix} fixtures yet")


def render(case: Path) -> str:
    [input_path] = case.glob("input.*")
    payload = load_payload(input_path)
    plugin = REGISTRY.get(case.parent.name)
    result = build_jobs(
        plugin.parse(payload),
        source=case.parent.name,
        parser=plugin.info,
        raw_ref=payload.raw_ref,
        now=lambda: FETCHED,
    )
    output = {
        "jobs": [job.model_dump(mode="json") for job in result.jobs],
        "dead_letters": [letter.model_dump(mode="json") for letter in result.dead_letters],
        "dropped_languages": result.dropped_languages,
    }
    return json.dumps(output, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_golden(case: Path) -> None:
    expected = case / "expected.json"
    actual = render(case)
    if UPDATE:
        expected.write_text(actual, encoding="utf-8")
    assert expected.exists(), f"{expected} missing: run make golden and review it"
    assert actual == expected.read_text(encoding="utf-8"), "output changed: run make golden"


def test_every_parser_has_a_golden_case() -> None:
    covered = {case.parent.name for case in CASES}
    assert REGISTRY.names() <= covered, f"no golden case for {REGISTRY.names() - covered}"
