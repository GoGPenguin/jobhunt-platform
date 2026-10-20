import json
from pathlib import Path

import pytest

from jobhunt.domain.job import Job
from jobhunt.tools.export_schema import main, render_schemas


def test_renders_job_and_dead_letter_schemas() -> None:
    assert set(render_schemas()) == {"job.v1.json", "dead_letter.v1.json"}


def test_job_schema_is_stored_shape() -> None:
    schema = json.loads(render_schemas()["job.v1.json"])
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "Job"
    # Stored shape: every field is always present, including ones with defaults.
    assert set(schema["required"]) == set(Job.model_fields)
    assert "description_truncated" in schema["required"]


def test_job_schema_lists_enum_values() -> None:
    schema = json.loads(render_schemas()["job.v1.json"])
    assert schema["$defs"]["Workplace"]["enum"] == ["onsite", "hybrid", "remote", "unknown"]


def test_job_schema_carries_formats_and_lengths() -> None:
    schema = json.loads(render_schemas()["job.v1.json"])
    props, defs = schema["properties"], schema["$defs"]
    assert (props["title"]["minLength"], props["title"]["maxLength"]) == (1, 300)
    assert props["company"]["maxLength"] == 200
    assert props["description"]["maxLength"] == 50_000
    assert props["language"]["pattern"] == "^([a-z]{2}|unknown)$"
    assert props["remote_regions"]["anyOf"][0]["items"]["pattern"] == "^[A-Z][A-Z0-9_]{1,31}$"
    assert defs["Location"]["properties"]["country"]["anyOf"][0]["pattern"] == "^[A-Z]{2}$"
    assert defs["Salary"]["properties"]["currency"]["pattern"] == "^[A-Z]{3}$"


def test_rendering_is_deterministic() -> None:
    assert render_schemas() == render_schemas()


def test_write_then_check_passes(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dead_letter.v1.json", "job.v1.json"]
    assert main(["--out", str(tmp_path), "--check"]) == 0


def test_check_fails_when_stale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--out", str(tmp_path)])
    (tmp_path / "job.v1.json").write_text("{}\n", encoding="utf-8")
    assert main(["--out", str(tmp_path), "--check"]) == 1
    err = capsys.readouterr().err
    assert "job.v1.json" in err
    assert "make schema" in err


def test_check_fails_when_missing(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path), "--check"]) == 1
