"""preferences.yaml version 1 and load_profile (spec 06: P4, P7)."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from jobhunt.config_files import ConfigError
from jobhunt.profile.load import load_profile, load_profile_lenient
from jobhunt.profile.preferences import Preferences, load_preferences

REPO = Path(__file__).resolve().parents[4]
SAMPLE = REPO / "config" / "preferences.sample.yaml"


def changed(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> Preferences:
    data: dict[str, Any] = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "preferences.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_preferences(path)


def floor(data: dict[str, Any]) -> dict[str, Any]:
    salary: dict[str, Any] = data["filters"]["minimum_salary"][0]
    return salary


def test_sample_is_valid() -> None:
    prefs = load_preferences(SAMPLE)
    assert [m.name for m in prefs.markets] == ["vietnam", "asia", "global-remote"]
    assert prefs.filters.minimum_salary[0].amount == Decimal(20_000_000)
    assert prefs.accepted_languages == frozenset({"vi", "en"})
    assert str(prefs.timezone) == "Asia/Ho_Chi_Minh"
    assert prefs.looking_for is not None


def test_missing_file_means_defaults(tmp_path: Path) -> None:
    prefs = load_preferences(tmp_path / "preferences.yaml")
    assert prefs.accepted_languages is None  # no language filter
    assert str(prefs.timezone) == "UTC"
    assert prefs.markets == []
    assert prefs.filters.excluded_companies == []


def test_file_without_optional_sections(tmp_path: Path) -> None:
    path = tmp_path / "preferences.yaml"
    path.write_text("schema_version: 1\n")
    prefs = load_preferences(path)
    assert prefs.accepted_languages is None
    assert str(prefs.timezone) == "UTC"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["candidate"].update(timezone="Mars/Olympus"), r"candidate\.timezone"),
        (lambda d: d["candidate"]["location"].update(country="Vietnam"), r"location\.country"),
        (lambda d: d["languages"].update(postings=["vn"]), r"languages\.postings"),
        (lambda d: d["languages"].update(postings=[]), r"languages\.postings"),
        (lambda d: d["languages"].update(postings="vi"), r"languages\.postings"),
        (lambda d: d["targets"].update(seniority=["principal"]), r"targets\.seniority"),
        (lambda d: d["markets"][0].update(workplace=["office"]), r"markets\[0\]\.workplace"),
        (lambda d: d["markets"][1].update(regions=["Asia Pacific"]), r"markets\[1\]\.regions"),
        (lambda d: d["markets"][1].update(name="vietnam"), "duplicate market 'vietnam'"),
        (lambda d: floor(d).update(currency="XYZ"), r"minimum_salary\[0\]\.currency"),
        (lambda d: floor(d).update(amount=-1), r"minimum_salary\[0\]\.amount"),
        (lambda d: d.update(looking_for="x" * 1001), "looking_for"),
        (lambda d: d["markets"][0].update(remote_regions_ok=["APAC"]), "remote_regions_ok"),
    ],
)  # fmt: skip
def test_invalid(tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        changed(tmp_path, change)


def test_load_profile(tmp_path: Path) -> None:
    (tmp_path / "preferences.yaml").write_text(SAMPLE.read_text(encoding="utf-8"))
    (tmp_path / "master_cv.yaml").write_text(
        (REPO / "config" / "master_cv.sample.yaml").read_text(encoding="utf-8")
    )
    profile = load_profile(tmp_path)
    assert profile.master_cv is not None
    assert profile.preferences.accepted_languages == frozenset({"vi", "en"})
    assert profile.aliases.canonical("K8s") == "Kubernetes"
    assert profile.issues() == []  # fact skills all resolve


def test_load_profile_without_files(tmp_path: Path) -> None:
    profile = load_profile(tmp_path)
    assert profile.master_cv is None
    assert profile.preferences.accepted_languages is None


# Spec 07 additions: regions and matching weights


def test_regions_and_weights_from_sample() -> None:
    prefs = load_preferences(SAMPLE)
    assert prefs.regions == {"SEA_HUBS": ["SG", "VN", "TH"]}
    weights = prefs.matching.weights
    assert (weights.title, weights.market, weights.skills) == (35, 25, 20)  # title overridden
    assert (weights.seniority, weights.experience) == (15, 10)  # defaults kept


def test_defaults_without_matching_section(tmp_path: Path) -> None:
    path = tmp_path / "preferences.yaml"
    path.write_text("schema_version: 1\n")
    weights = load_preferences(path).matching.weights
    assert weights.model_dump() == {
        "title": 30, "market": 25, "skills": 20, "seniority": 15, "experience": 10,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["matching"]["weights"].update(title=-1), r"matching\.weights\.title"),
        (lambda d: d["matching"]["weights"].update(salary=5), r"matching\.weights\.salary"),
        (lambda d: d["matching"].update(weights={k: 0 for k in
            ("title", "market", "skills", "seniority", "experience")}), "at least one weight"),
        (lambda d: d["regions"].update(SEA_HUBS=["Singapore"]), r"regions\.SEA_HUBS"),
        (lambda d: d["regions"].update(SEA_HUBS=[]), r"regions\.SEA_HUBS"),
        (lambda d: d["regions"].update({"sea": ["SG"]}), r"regions"),
    ],
)  # fmt: skip
def test_invalid_additions(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        changed(tmp_path, change)


def test_load_profile_lenient_reports_broken_files(tmp_path: Path) -> None:
    (tmp_path / "master_cv.yaml").write_text("schema_version: 1\nprofile: [broken]\n")
    (tmp_path / "preferences.yaml").write_text("schema_version: 1\nmarkets: nope\n")
    profile, problems = load_profile_lenient(tmp_path)
    assert problems == ["master_cv.yaml", "preferences.yaml"]
    assert profile.master_cv is None
    assert profile.preferences == Preferences()  # defaults


def test_load_profile_lenient_without_problems(tmp_path: Path) -> None:
    (tmp_path / "preferences.yaml").write_text(SAMPLE.read_text(encoding="utf-8"))
    profile, problems = load_profile_lenient(tmp_path)
    assert problems == []
    assert profile.preferences.accepted_languages == frozenset({"vi", "en"})
