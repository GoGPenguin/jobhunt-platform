import pytest

from jobhunt.domain.codes import COUNTRY_CODES, COUNTRY_NAMES, CURRENCY_CODES, LANGUAGE_CODES


@pytest.mark.parametrize("code", ["VN", "JP", "SG", "GB", "US", "DE", "NL", "AU"])
def test_country_codes_include(code: str) -> None:
    assert code in COUNTRY_CODES


@pytest.mark.parametrize("code", ["Vietnam", "vn", "UK", "XX", "VNM", ""])
def test_country_codes_exclude(code: str) -> None:
    assert code not in COUNTRY_CODES


@pytest.mark.parametrize("code", ["VND", "USD", "JPY", "EUR", "SGD", "AUD"])
def test_currency_codes_include(code: str) -> None:
    assert code in CURRENCY_CODES


@pytest.mark.parametrize("code", ["XYZ", "usd", "VN", "US$", ""])
def test_currency_codes_exclude(code: str) -> None:
    assert code not in CURRENCY_CODES


@pytest.mark.parametrize("code", ["vi", "en", "ja", "de", "nl", "fr", "es", "zh", "ko"])
def test_language_codes_include(code: str) -> None:
    assert code in LANGUAGE_CODES


@pytest.mark.parametrize("code", ["vn", "jp", "EN", "eng", "unknown", ""])
def test_language_codes_exclude(code: str) -> None:
    assert code not in LANGUAGE_CODES


def test_list_sizes_match_iso_codes_4_20_1() -> None:
    assert len(COUNTRY_CODES) == 249
    assert len(CURRENCY_CODES) == 178
    assert len(LANGUAGE_CODES) == 183


def test_code_formats() -> None:
    assert all(len(c) == 2 and c.isascii() and c.isupper() for c in COUNTRY_CODES)
    assert all(len(c) == 3 and c.isascii() and c.isupper() for c in CURRENCY_CODES)
    assert all(len(c) == 2 and c.isascii() and c.islower() for c in LANGUAGE_CODES)


@pytest.mark.parametrize(
    ("name", "code"),
    [("vietnam", "VN"), ("viet nam", "VN"), ("singapore", "SG"), ("south korea", "KR"),
     ("united states", "US"), ("netherlands", "NL"), ("socialist republic of viet nam", "VN")],
)  # fmt: skip
def test_country_names(name: str, code: str) -> None:
    assert COUNTRY_NAMES[name] == code


def test_country_names_are_lowercase_and_map_to_codes() -> None:
    assert all(name == name.lower() for name in COUNTRY_NAMES)
    assert set(COUNTRY_NAMES.values()) == COUNTRY_CODES
