"""Scoring, filters and ranking (spec 07: M1, M3, M4, M5, M6, M7, M8). Fictional sample profile:
roles Platform/SRE/DevOps Engineer; junior or mid; up to 4 years; markets vietnam (VN), asia
(SG, JP, APAC), global-remote; excluded company Fabrikam; excluded keywords sales, PHP; minimum
20M VND/month and 30,000 USD/year; title weight overridden to 35."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from jobhunt.domain.job import Job
from jobhunt.matching.score import Matcher, rank
from jobhunt.profile.load import Profile, load_profile
from jobhunt.store.fingerprint import fingerprint
from jobhunt.store.port import Posting, StoredJob

REPO = Path(__file__).resolve().parents[4]
FIXTURE = Path(__file__).parent.parent / "fixtures" / "jobs" / "greenhouse_style.json"
NOW = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)


@pytest.fixture
def profile(tmp_path: Path) -> Profile:
    for name in ("master_cv", "preferences"):
        shutil.copy(REPO / "config" / f"{name}.sample.yaml", tmp_path / f"{name}.yaml")
    return load_profile(tmp_path)


def job(**changes: Any) -> Job:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base = {"title": "Platform Engineer", "company": "Lumen Robotics", "salary": None,
            "seniority": "unknown", "years_experience_min": None, "visa_sponsorship": None,
            "description": "Run Kubernetes on AWS with Terraform.",
            "locations": [{"city": "Đà Nang"}], "workplace": "onsite"}  # fmt: skip
    return Job.from_parser(data | base | changes)


def posting(*jobs: Job, age_hours: int = 1) -> Posting:
    seen = NOW - timedelta(hours=age_hours)
    stored = tuple(StoredJob(j, fingerprint(j.company, j.title), seen, seen, seen) for j in jobs)
    return Posting(stored[0].fingerprint, frozenset(), stored)


def scored(profile: Profile, *jobs: Job) -> Any:
    return Matcher(profile).score(posting(*jobs))


# M1: a good fit beats a bad one, with reasons


def test_good_fit_outscores_bad_fit(profile: Profile) -> None:
    good = scored(profile, job(title="Senior Platform Engineer"))
    berlin = [{"city": "Berlin"}]
    bad = scored(
        profile,
        job(title="Sales Engineer", company="Contoso", locations=berlin, description="Sell it."),
    )
    assert good.score > bad.score
    assert good.reasons[:2] == ("title ✓", "vietnam (1st)")
    assert "Terraform" in good.reasons[-1]
    assert "AWS" in good.reasons[-1]


def test_market_priority_order(profile: Profile) -> None:
    vietnam = scored(profile, job(locations=[{"city": "Hanoi"}]))
    tokyo = scored(profile, job(locations=[{"city": "Tokyo"}]))
    berlin = scored(profile, job(locations=[{"city": "Berlin"}]))
    assert vietnam.score > tokyo.score > berlin.score
    assert "asia (2nd)" in tokyo.reasons


def test_remote_job_fits_remote_market(profile: Profile) -> None:
    # Open to APAC, so doable from VN: it fits the first market, which allows remote work.
    remote = scored(profile, job(locations=[], workplace="remote", remote_regions=["APAC"]))
    assert "vietnam (1st)" in remote.reasons


def test_unknown_location_is_neutral_not_zero(profile: Profile) -> None:
    unknown = scored(profile, job(locations=[], location_raw=None, workplace="unknown"))
    berlin = scored(profile, job(locations=[{"city": "Berlin"}]))
    assert unknown.score > berlin.score


# M3, M4: filtered out


def test_excluded_company_is_filtered(profile: Profile) -> None:
    assert scored(profile, job(company="Fabrikam Ltd.")).filtered == "excluded company"


def test_remote_not_open_to_candidate_is_filtered(profile: Profile) -> None:
    us_only = scored(profile, job(workplace="remote", locations=[], remote_regions=["US"]))
    assert us_only.filtered == "remote not open to VN"
    apac = scored(profile, job(workplace="remote", locations=[], remote_regions=["APAC"]))
    unknown_label = scored(profile, job(workplace="remote", locations=[], remote_regions=["MARS"]))
    assert apac.filtered is None
    assert unknown_label.filtered is None  # unknown label means "not stated"


# M5: excluded keyword ranks last


def test_excluded_keyword_flags_whole_words_only(profile: Profile) -> None:
    sales = scored(profile, job(title="Platform Engineer (Sales Tools)"))
    salesforce = scored(profile, job(title="Salesforce Platform Engineer"))
    assert sales.flags == ("excluded: sales",)
    assert salesforce.flags == ()


# M6: minimum salary


@pytest.mark.parametrize(
    ("salary", "flagged"),
    [
        ({"min": "15000000", "max": "18000000", "currency": "VND", "period": "month",
          "basis": "net"}, True),
        ({"min": "300000000", "currency": "VND", "period": "year", "basis": "gross"}, False),
        ({"max": "1000", "currency": "USD", "period": "month", "basis": "net"}, True),
        # no SGD floor in the sample profile, so not compared
        ({"min": "100", "currency": "SGD", "period": "month", "basis": "net"}, False),
        ({"min": "15000000", "currency": "VND", "period": "unknown", "basis": "net"}, False),
    ],
)  # fmt: skip
def test_minimum_salary(profile: Profile, salary: dict[str, Any], flagged: bool) -> None:
    result = scored(profile, job(salary=salary))
    assert ("below minimum salary" in result.flags) is flagged


# M7: weights


def test_weights_change_the_order(profile: Profile, tmp_path: Path) -> None:
    title_fit = job(title="Platform Engineer", locations=[{"city": "Berlin"}])
    market_fit = job(title="Backend Developer", locations=[{"city": "Hanoi"}])
    before = rank([posting(title_fit), posting(market_fit)], profile)
    assert before[0].posting.representative.job.title == "Platform Engineer"

    prefs = yaml.safe_load((tmp_path / "preferences.yaml").read_text(encoding="utf-8"))
    prefs["matching"]["weights"] = {"title": 5, "market": 80}
    (tmp_path / "preferences.yaml").write_text(yaml.safe_dump(prefs, allow_unicode=True))
    after = rank([posting(title_fit), posting(market_fit)], load_profile(tmp_path))
    assert after[0].posting.representative.job.title == "Backend Developer"


# M8: missing description is unknown, not bad


def test_no_description_scores_skills_neutral(profile: Profile) -> None:
    empty = scored(profile, job(description=""))
    unrelated = scored(profile, job(description="We write COBOL on mainframes."))
    assert empty.score > unrelated.score


# Seniority, experience, ordering


def test_seniority_and_experience(profile: Profile) -> None:
    mid = scored(profile, job(title="Middle Platform Engineer"))
    staff = scored(profile, job(title="Staff Platform Engineer"))
    assert mid.score > staff.score
    assert "mid ✓" in mid.reasons
    six_years = scored(profile, job(description="6+ years of Kubernetes on AWS with Terraform."))
    two_years = scored(profile, job(description="2+ years of Kubernetes on AWS with Terraform."))
    assert two_years.score > six_years.score


def test_rank_order_flags_last_then_score_then_newest(profile: Profile) -> None:
    flagged_best = posting(job(title="Platform Engineer, PHP"), age_hours=1)
    plain_ok = posting(job(title="DevOps Engineer", locations=[{"city": "Berlin"}]), age_hours=5)
    plain_good = posting(job(title="Platform Engineer", company="A"), age_hours=9)
    plain_good_newer = posting(job(title="Platform Engineer", company="B"), age_hours=2)
    ranked = rank([flagged_best, plain_ok, plain_good, plain_good_newer], profile)
    companies = [r.posting.representative.job.company for r in ranked]
    titles = [r.posting.representative.job.title for r in ranked]
    assert companies[:2] == ["B", "A"]  # equal score: newer first
    assert titles[2] == "DevOps Engineer"
    assert titles[-1] == "Platform Engineer, PHP"  # flagged last despite its score


def test_without_profile_files_everything_is_neutral(tmp_path: Path) -> None:
    result = Matcher(load_profile(tmp_path)).score(posting(job()))
    assert result.filtered is None
    assert 0 <= result.score <= 100
