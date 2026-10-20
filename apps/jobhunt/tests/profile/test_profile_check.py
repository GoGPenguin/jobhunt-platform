"""`jobhunt profile check` (spec 06: P6 for the samples). Output names entries, never values."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from jobhunt.cli import main

REPO = Path(__file__).resolve().parents[4]
Capture = pytest.CaptureFixture[str]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    for name in ("master_cv", "preferences"):
        shutil.copy(REPO / "config" / f"{name}.sample.yaml", tmp_path / f"{name}.yaml")
    return tmp_path


def check(config_dir: Path, capsys: Capture) -> tuple[int, dict[str, Any], str]:
    code = main(["profile", "check", "--config-dir", str(config_dir)], env={})
    out, err = capsys.readouterr()
    return code, json.loads(out.splitlines()[-1]), err


def test_valid_sample_with_warning(config_dir: Path, capsys: Capture) -> None:
    code, summary, err = check(config_dir, capsys)
    assert code == 0
    assert summary == {"type": "summary", "errors": 0, "warnings": 1}
    assert "contoso-alerting).vi: not reviewed yet" in err


def test_fact_skill_error(config_dir: Path, capsys: Capture) -> None:
    cv = config_dir / "master_cv.yaml"
    cv.write_text(cv.read_text().replace("skills: [Prometheus]", "skills: [Prometheus, Kafka]"))
    code, summary, err = check(config_dir, capsys)
    assert code == 2
    assert summary["errors"] == 1
    assert "(contoso-alerting).skills: 'Kafka' is not in skills" in err


def test_invalid_file_is_one_error_naming_the_entry(config_dir: Path, capsys: Capture) -> None:
    cv = config_dir / "master_cv.yaml"
    cv.write_text(cv.read_text().replace('numbers: ["12", "40%"]', 'numbers: ["12", "45%"]'))
    code, summary, err = check(config_dir, capsys)
    assert code == 2
    assert summary["errors"] == 1
    assert "(contoso-eks-migration).numbers" in err


def test_output_never_contains_cv_text(config_dir: Path, capsys: Capture) -> None:
    cv = config_dir / "master_cv.yaml"
    cv.write_text(cv.read_text().replace('numbers: ["12", "40%"]', 'numbers: ["99"]'))
    _, _, err = check(config_dir, capsys)
    assert "Migrated 12 services" not in err
    assert "alex@example.com" not in err


def test_missing_master_cv(config_dir: Path, capsys: Capture) -> None:
    (config_dir / "master_cv.yaml").unlink()
    code, summary, err = check(config_dir, capsys)
    assert code == 2
    assert summary["errors"] == 1
    assert "master_cv.yaml: not found" in err
