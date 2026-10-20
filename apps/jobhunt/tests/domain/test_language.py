import unicodedata

import pytest

from jobhunt.domain.codes import LANGUAGE_CODES
from jobhunt.domain.language import detect_language

SAMPLES = {
    "en": (
        "We are looking for a platform engineer to join our team. You will work with "
        "Kubernetes and Terraform and help us improve the reliability of our systems."
    ),
    "vi": (
        "Chúng tôi đang tìm kiếm kỹ sư DevOps có kinh nghiệm làm việc với Kubernetes và AWS. "
        "Ứng viên sẽ tham gia vận hành hệ thống cho khách hàng."
    ),
    "de": (
        "Wir suchen eine erfahrene Person für unser Plattform-Team. Du arbeitest mit Kubernetes "
        "und Terraform und bist für den Betrieb unserer Systeme verantwortlich."
    ),
    "nl": (
        "Wij zoeken een ervaren engineer voor ons platformteam. Je werkt met Kubernetes en "
        "Terraform en bent verantwoordelijk voor de stabiliteit van onze systemen."
    ),
    "fr": (
        "Nous recherchons un ingénieur pour rejoindre notre équipe plateforme. Vous travaillerez "
        "avec Kubernetes et Terraform et serez responsable de la fiabilité de nos systèmes."
    ),
    "es": (
        "Buscamos una persona con experiencia en Kubernetes y Terraform para unirse a nuestro "
        "equipo. Serás responsable de la estabilidad de los sistemas de la empresa."
    ),
    "ja": "東京本社でKubernetes基盤の運用を担当していただきます。",
    "zh": "运维工程师 负责 Kubernetes 集群的日常运维和监控",
    "ko": "데브옵스 엔지니어 채용 (Kubernetes 경험자 우대)",
}


@pytest.mark.parametrize(("expected", "text"), SAMPLES.items())
def test_detects_supported_languages(expected: str, text: str) -> None:
    assert detect_language(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kỹ sư DevOps (Junior)", "vi"),
        ("インフラエンジニア (Kubernetes)", "ja"),
        ("DevOps エンジニア", "ja"),
        ("Senior DevOps Engineer", "unknown"),
        ("DevOps Engineer - Đà Nẵng", "unknown"),
    ],
)
def test_short_titles(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_english_mentioning_vietnamese_place_stays_english() -> None:
    text = (
        "We are hiring a cloud engineer for our office in Đà Nẵng. You will work with "
        "the platform team on AWS infrastructure."
    )
    assert detect_language(text) == "en"


def test_decomposed_vietnamese() -> None:
    assert detect_language(unicodedata.normalize("NFD", SAMPLES["vi"])) == "vi"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "2026 - 15,000,000 VND / 3+",
        "Kubernetes Terraform AWS GCP",
        "รับสมัครวิศวกร DevOps ประจำกรุงเทพ",  # Thai: not in the supported list
    ],
)
def test_unknown_when_no_clear_signal(text: str) -> None:
    assert detect_language(text) == "unknown"


def test_results_are_valid_codes() -> None:
    for text in SAMPLES.values():
        result = detect_language(text)
        assert result == "unknown" or result in LANGUAGE_CODES
