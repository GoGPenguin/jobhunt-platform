"""City -> country and region -> countries (spec 07: M2, M10)."""

import gzip
from importlib import resources

import pytest

from jobhunt.domain.codes import COUNTRY_CODES
from jobhunt.domain.job import Location
from jobhunt.matching.places import Regions, country_of_city, location_countries


@pytest.mark.parametrize(
    ("place", "country"),
    [
        ("Đà Nang", "VN"),  # LinkedIn's spelling
        ("Đà Nẵng", "VN"),
        ("Da Nang", "VN"),
        ("Ha Noi", "VN"),  # spaces differ from GeoNames' "Hanoi"
        ("Hanoi", "VN"),
        ("Hanoi Capital Region", "VN"),
        ("Ho Chi Minh City", "VN"),
        ("Singapore", "SG"),
        ("Tokyo", "JP"),
        ("Greater Tokyo Area", "JP"),
        ("Berlin Metropolitan Area", "DE"),
    ],
)
def test_country_of_city(place: str, country: str) -> None:
    assert country_of_city(place) == country


@pytest.mark.parametrize("place", ["", "Remote", "Hybrid", "Somewhere Nowhere"])
def test_unknown_places(place: str) -> None:
    assert country_of_city(place) is None


def test_stated_country_wins_over_city_lookup() -> None:
    # A "Singapore" city in another country must not override an explicit country.
    assert location_countries([Location(city="Singapore", country="VN")]) == {"VN"}


def test_location_countries_from_city_or_region() -> None:
    assert location_countries([Location(city="Đà Nang")]) == {"VN"}
    assert location_countries([Location(region="Hanoi Capital Region")]) == {"VN"}
    assert location_countries([Location(city="Tokyo"), Location(country="SG")]) == {"JP", "SG"}
    assert location_countries([Location(city="Atlantis Prime")]) == set()


def test_bundled_regions() -> None:
    regions = Regions.bundled()
    assert regions.countries("ASEAN") == frozenset(
        {"BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "TL", "VN"}
    )
    assert regions.covers("APAC", "VN")
    assert regions.covers("EU", "DE")
    assert regions.covers("EMEA", "TR")
    assert regions.covers("AMERICAS", "US")
    assert not regions.covers("LATAM", "US")
    assert regions.covers("WORLDWIDE", "VN")
    assert regions.covers("VN", "VN")  # a country code covers itself
    assert regions.countries("MARS") is None  # unknown label: not stated


def test_overrides_add_and_redefine() -> None:
    regions = Regions.bundled().with_overrides({"SEA": ["VN", "TH"], "APAC": ["VN"]})
    assert regions.covers("SEA", "TH")
    assert regions.countries("APAC") == frozenset({"VN"})
    assert regions.covers("EU", "FR")  # untouched labels stay


def test_bundled_data_is_valid_and_attributed() -> None:
    regions = Regions.bundled()
    for label in ("WORLDWIDE", "APAC", "ASEAN", "EU", "EMEA", "AMERICAS", "LATAM"):
        assert regions.countries(label) <= COUNTRY_CODES  # type: ignore[operator]
    data = resources.files("jobhunt.matching") / "data" / "cities.tsv.gz"
    with gzip.open(str(data), "rt", encoding="utf-8") as cities:
        header = cities.readline() + cities.readline()
        rows = [line.rstrip("\n").split("\t") for line in cities]
    assert "CC BY 4.0" in header
    assert all(country in COUNTRY_CODES for _, country in rows)
    assert len(rows) > 30_000
