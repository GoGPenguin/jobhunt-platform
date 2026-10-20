import unicodedata

import pytest

from jobhunt.store.fingerprint import fingerprint, fold, normalize_company, normalize_title


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Đà Nẵng", "da nang"),
        ("Kỹ sư DevOps", "ky su devops"),
        ("Hồ Chí Minh", "ho chi minh"),
        ("Straße", "strasse"),
        ("  Senior   DevOps\tEngineer ", "senior devops engineer"),
        ("DevOps/SRE (Junior-Middle) [HN]", "devops sre junior middle hn"),
        ("C++ & Go", "c go"),
    ],
)
def test_fold(text: str, folded: str) -> None:
    assert fold(text) == folded


def test_fold_decomposed_input() -> None:
    assert fold(unicodedata.normalize("NFD", "Đà Nẵng")) == "da nang"


@pytest.mark.parametrize(
    ("company", "normalized"),
    [
        ("Lumen Robotics Pte. Ltd.", "lumen robotics"),
        ("Lumen Robotics", "lumen robotics"),
        ("CMC Global Company Limited.", "cmc global"),
        ("Công ty TNHH Phần mềm Sông Hàn", "phan mem song han"),
        ("Công ty Cổ phần Phần mềm Sông Hàn", "phan mem song han"),
        ("Sông Hàn Software JSC", "song han software"),
        ("Northwind Cloud, Inc.", "northwind cloud"),
        ("Contoso GmbH", "contoso"),
        ("Amaris Consulting  | Part of Mantu", "amaris consulting"),
        ("VSF Company", "vsf"),
        ("Company", "company"),  # never reduced to nothing
    ],
)
def test_normalize_company(company: str, normalized: str) -> None:
    assert normalize_company(company) == normalized


@pytest.mark.parametrize(
    ("title", "normalized"),
    [
        ("Senior DevOps Engineer", "senior devops engineer"),
        ("Senior DevOps Engineer!", "senior devops engineer"),
        ("[HN] Devops Cloud", "hn devops cloud"),
        ("Kỹ sư DevOps (Junior)", "ky su devops junior"),
    ],
)
def test_normalize_title(title: str, normalized: str) -> None:
    assert normalize_title(title) == normalized


def test_same_job_same_fingerprint() -> None:
    linkedin = fingerprint("Lumen Robotics Pte. Ltd.", "Senior DevOps Engineer")
    greenhouse = fingerprint("Lumen Robotics", "senior devops engineer")
    assert linkedin == greenhouse
    assert len(linkedin) == 64


def test_different_jobs_different_fingerprints() -> None:
    base = fingerprint("Lumen Robotics", "Senior DevOps Engineer")
    assert base != fingerprint("Lumen Robotics", "DevOps Engineer")
    assert base != fingerprint("Northwind Cloud", "Senior DevOps Engineer")
    # The separator keeps company and title apart.
    assert fingerprint("a b", "c") != fingerprint("a", "b c")
