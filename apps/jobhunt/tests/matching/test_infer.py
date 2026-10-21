"""Inference for the matcher (spec 07): seniority, years, skills. Pure functions."""

import pytest

from jobhunt.matching.infer import seniority_levels, skills_found, years_required
from jobhunt.profile.aliases import SkillAliases
from jobhunt.profile.master_cv import Skill

ALIASES = SkillAliases.from_mapping({"Kubernetes": ["K8s"], "AWS EKS": ["EKS"]}, source="test")
SKILLS = [
    Skill(name="Kubernetes", category="containers", level="core"),
    Skill(name="AWS EKS", category="cloud", level="working"),
    Skill(name="Terraform", category="iac", level="core"),
    Skill(name="CI/CD", category="practices", level="working"),
    Skill(name="Go", category="languages", level="familiar"),
    Skill(name="C", category="languages", level="familiar"),
]


@pytest.mark.parametrize(
    ("title", "levels"),
    [
        ("Senior DevOps Engineer", {"senior"}),
        ("Middle - Senior DevOps Engineer", {"mid", "senior"}),
        ("DevOps Engineer (Jr-Mid Level | Good English)", {"junior", "mid"}),
        ("Kỹ sư DevOps (Junior)", {"junior"}),
        ("Kỹ sư DevOps cao cấp", {"senior"}),
        ("Trưởng nhóm DevOps", {"lead"}),
        ("Staff Platform Engineer", {"staff_plus"}),
        ("Principal SRE", {"staff_plus"}),
        ("Tech Lead, Platform", {"lead"}),
        ("Platform Engineer", set()),
        ("Fresher Cloud Engineer", {"junior"}),
        ("Seniority-friendly team builder", set()),  # not a whole word
    ],
)
def test_seniority_levels(title: str, levels: set[str]) -> None:
    assert seniority_levels(title) == levels


@pytest.mark.parametrize(
    ("text", "years"),
    [
        ("We need 3+ years of experience with Kubernetes.", 3),
        ("At least 2 years in DevOps, 5 years preferred.", 2),
        ("2-4 years of experience", 2),
        ("2\u20134 years of experience", 2),  # en dash
        ("Tối thiểu 2 năm kinh nghiệm", 2),
        ("1 year of AWS", 1),
        ("Founded 15 years ago in 2011", 15),  # crude on purpose: the smallest figure counts
        ("No figure here", None),
        ("", None),
        ("100 years of history", None),  # implausible, ignored
    ],
)
def test_years_required(text: str, years: int | None) -> None:
    assert years_required(text) == years


def test_skills_found_by_name_or_alias_whole_words() -> None:
    text = "Run K8s (EKS) with Terraform; build CI/CD pipelines. Going global!"
    found = skills_found(text, SKILLS, ALIASES)
    assert found == {
        "Kubernetes": "core",
        "AWS EKS": "working",
        "Terraform": "core",
        "CI/CD": "working",
    }


def test_skills_found_ignores_one_letter_names_and_partial_words() -> None:
    assert skills_found("C and Golang and Terraformer", SKILLS, ALIASES) == {}


def test_skills_found_with_diacritics_and_case() -> None:
    assert skills_found("Kinh nghiệm KUBERNETES và terraform", SKILLS, ALIASES) == {
        "Kubernetes": "core",
        "Terraform": "core",
    }
