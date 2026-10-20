"""master_cv.yaml version 1 (spec 06: P2, P3, P4). Each test changes one thing in the sample."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from jobhunt.config_files import ConfigError
from jobhunt.profile.aliases import bundled_aliases
from jobhunt.profile.master_cv import MasterCV, contains_figure, fact_skill_issues, load_master_cv

REPO = Path(__file__).resolve().parents[4]
SAMPLE = REPO / "config" / "master_cv.sample.yaml"


def sample() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    return data


def first_fact(data: dict[str, Any]) -> dict[str, Any]:
    fact: dict[str, Any] = data["experience"][0]["projects"][0]["facts"][0]
    return fact


def load_changed(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> MasterCV:
    data = sample()
    change(data)
    path = tmp_path / "master_cv.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_master_cv(path)


def test_sample_is_valid() -> None:
    cv = load_master_cv(SAMPLE)
    ids = [f.id for f in cv.facts()]
    assert ids == ["summary-main", "contoso-eks-migration", "contoso-alerting"]
    assert cv.skill("Kubernetes").level == "core"
    assert cv.skill("python").level == "working"  # missing level counts as working


def test_warnings() -> None:
    cv = load_master_cv(SAMPLE)
    assert cv.warnings() == [
        "experience[0] (exp-contoso).projects[0].facts[1] (contoso-alerting).vi: not reviewed yet"
        " (vi_reviewed: false)"
    ]
    contact = cv.profile.model_copy(update={"linkedin": None})
    no_linkedin = cv.model_copy(update={"profile": contact})
    assert "profile.linkedin: empty" in no_linkedin.warnings()


# P2: skills of facts exist by name or alias


def test_fact_skills_by_name_or_alias() -> None:
    cv = load_master_cv(SAMPLE)  # contoso-eks-migration lists "EKS", an alias of "AWS EKS"
    assert fact_skill_issues(cv, bundled_aliases()) == []


def test_fact_skill_not_in_skills(tmp_path: Path) -> None:
    cv = load_changed(tmp_path, lambda d: first_fact(d)["skills"].append("Kafka"))
    assert fact_skill_issues(cv, bundled_aliases()) == [
        "experience[0] (exp-contoso).projects[0].facts[0] (contoso-eks-migration).skills:"
        " 'Kafka' is not in skills"
        " (by name or alias)"
    ]


# P3: numbers appear literally in the texts


def test_number_missing_in_english(tmp_path: Path) -> None:
    where = r"facts\[0\] \(contoso-eks-migration\)\.numbers"
    with pytest.raises(ConfigError, match=where + r".*'50%'.*en"):
        load_changed(tmp_path, lambda d: first_fact(d)["numbers"].append("50%"))


def test_number_missing_in_vietnamese(tmp_path: Path) -> None:
    def change(d: dict[str, Any]) -> None:
        first_fact(d)["vi"] = first_fact(d)["vi"].replace("40%", "bốn mươi phần trăm")

    with pytest.raises(ConfigError, match=r"'40%'.*vi"):
        load_changed(tmp_path, change)


def test_number_must_match_literally(tmp_path: Path) -> None:
    def change(d: dict[str, Any]) -> None:
        first_fact(d)["numbers"] = ["12", "40.0%"]

    with pytest.raises(ConfigError, match=r"'40\.0%'"):
        load_changed(tmp_path, change)


@pytest.mark.parametrize("number", ["3 years", "40 %", "about 12", "many"])
def test_numbers_are_figures_only(tmp_path: Path, number: str) -> None:
    with pytest.raises(ConfigError, match="figure only"):
        load_changed(tmp_path, lambda d: first_fact(d).update(numbers=[number]))


@pytest.mark.parametrize(
    ("text", "number", "found"),
    [
        ("Migrated 12 services", "2", False),  # inside 12
        ("since 2024", "2", False),  # inside 2024
        ("v2 of the platform", "2", False),  # part of a word
        ("Migrated 2 services.", "2", True),
        ("cut by 30–80%.", "30–80%", True),
        ("GPA 3.82/4.0", "3.82/4.0", True),
        ("a 3.5 rating", "3", False),  # part of 3.5
    ],
)
def test_whole_figure_match(text: str, number: str, found: bool) -> None:
    assert contains_figure(text, number) is found


# P4: ids, dates, keys, enums


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: first_fact(d).update(id="summary-main"), "duplicate fact id 'summary-main'"),
        (lambda d: first_fact(d).update(id="Bad Id"), r"facts\[0\].*id"),
        (
            lambda d: d["experience"][0].update(start="2023-13"),
            r"experience\[0\] \(exp-contoso\)\.start",
        ),
        (lambda d: d["education"][0].update(end="2018-01"), r"education\[0\].*end is before start"),
        (lambda d: d["skills"][0].update(level="expert"), r"skills\[0\]\.level"),
        (
            lambda d: d["skills"].append({"name": "kubernetes", "category": "x"}),
            "duplicate skill 'kubernetes'",
        ),
        (lambda d: first_fact(d).update(numbrs=[]), "numbrs"),
        (lambda d: d.update(schema_version=2), "schema_version"),
    ],
)
def test_invalid(tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_changed(tmp_path, change)


def test_errors_never_contain_fact_text(tmp_path: Path) -> None:
    def change(d: dict[str, Any]) -> None:
        first_fact(d)["en"] = "SECRET-SENTENCE about my work"
        first_fact(d)["skills"] = 5  # wrong type, would echo input in Pydantic's default output

    with pytest.raises(ConfigError) as exc:
        load_changed(tmp_path, change)
    assert "SECRET-SENTENCE" not in str(exc.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_master_cv(tmp_path / "master_cv.yaml")
