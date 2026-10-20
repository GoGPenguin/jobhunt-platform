"""Skill aliases: alternative names for the same skill only (spec 06, P5; constitution 3)."""

import pytest

from jobhunt.config_files import ConfigError
from jobhunt.profile.aliases import SkillAliases, bundled_aliases


def aliases(mapping: dict[str, list[str]]) -> SkillAliases:
    return SkillAliases.from_mapping(mapping, source="test")


def test_canonical_by_name_or_alias_case_insensitive() -> None:
    table = aliases({"Kubernetes": ["K8s"], "AWS EKS": ["EKS", "Amazon EKS"]})
    assert table.canonical("Kubernetes") == "Kubernetes"
    assert table.canonical("kubernetes") == "Kubernetes"
    assert table.canonical("K8S") == "Kubernetes"
    assert table.canonical("amazon eks") == "AWS EKS"
    assert table.canonical("Terraform") is None  # not in the table: callers keep the name


def test_same_skill_check() -> None:
    table = aliases({"Kubernetes": ["K8s"]})
    assert table.same_skill("k8s", "Kubernetes")
    assert table.same_skill("Terraform", "terraform")
    assert not table.same_skill("Docker", "Kubernetes")


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ({"Kubernetes": ["K8s"], "Kube": ["k8s"]}, "'k8s' is an alias of both"),
        ({"AWS EKS": ["EKS"], "EKS": []}, "'EKS' is both a skill and an alias"),
        ({"Kubernetes": ["Kubernetes"]}, "alias of itself"),
        ({"Kubernetes": ["K8s", "k8s"]}, "listed twice"),
        ({"Kubernetes": [""]}, "empty"),
        ({"": ["K8s"]}, "empty"),
    ],
)
def test_invalid_tables(mapping: dict[str, list[str]], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        aliases(mapping)


def test_bundled_table_is_valid_and_has_true_synonyms_only() -> None:
    table = bundled_aliases()
    assert table.canonical("K8s") == "Kubernetes"
    assert table.canonical("IaC") == "Infrastructure as Code"
    # Broader or different names must not be aliases (constitution guardrail 3).
    assert table.canonical("Fargate") is None
    assert not table.same_skill("Docker", "Kubernetes")
    assert not table.same_skill("AWS", "AWS EKS")
