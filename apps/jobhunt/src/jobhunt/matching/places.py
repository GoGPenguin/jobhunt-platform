"""Places for the matcher (spec 07): a city's country and the countries of a region label.

Inference the canonical schema leaves out on purpose (spec 01): parsers report a city as
written; the matcher looks up its country here. A country stated in the job always wins.
Data: GeoNames (https://www.geonames.org), CC BY 4.0; see scripts/gen_places.py.
"""

import gzip
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from importlib import resources
from typing import Self

import yaml

from jobhunt.domain.codes import COUNTRY_CODES
from jobhunt.domain.job import Location
from jobhunt.store.fingerprint import fold

_PREFIXES = ("greater ",)
_SUFFIXES = (" capital region", " metropolitan area", " area", " region")
_NOT_PLACES = frozenset({"remote", "hybrid", "on site", "onsite", "anywhere", "worldwide"})


@cache
def _cities() -> dict[str, str]:
    path = resources.files("jobhunt.matching") / "data" / "cities.tsv.gz"
    table: dict[str, str] = {}
    with gzip.open(str(path), "rt", encoding="utf-8") as rows:
        for row in rows:
            if row.startswith("#"):
                continue
            name, country = row.rstrip("\n").split("\t")
            table[name] = country
    for name, country in list(table.items()):  # "Ha Noi" finds "Hanoi"
        table.setdefault(name.replace(" ", ""), country)
    return table


def country_of_city(name: str) -> str | None:
    key = fold(name)
    if not key or key in _NOT_PLACES:
        return None
    candidates = [key]
    for prefix in _PREFIXES:
        key = key.removeprefix(prefix)
    for suffix in _SUFFIXES:
        if key.endswith(suffix):
            key = key.removesuffix(suffix)
    candidates.append(key)
    table = _cities()
    for candidate in candidates:
        for form in (candidate, candidate.replace(" ", "")):
            if form in table:
                return table[form]
    return None


def location_countries(locations: Iterable[Location]) -> set[str]:
    """Countries of a job's locations: the stated country, else its city or region looked up."""
    countries: set[str] = set()
    for location in locations:
        if location.country:
            countries.add(location.country)
            continue
        for place in (location.city, location.region):
            found = country_of_city(place) if place else None
            if found:
                countries.add(found)
                break
    return countries


class Regions:
    """Region label -> countries. A country code stands for itself; unknown labels give None."""

    def __init__(self, table: Mapping[str, frozenset[str]]) -> None:
        self._table = dict(table)

    @classmethod
    def bundled(cls) -> Self:
        return cls(_bundled_regions())

    def with_overrides(self, overrides: Mapping[str, Sequence[str]]) -> Self:
        """preferences.yaml `regions:` adds labels or redefines bundled ones."""
        return type(self)(self._table | {k: frozenset(v) for k, v in overrides.items()})

    def countries(self, label: str) -> frozenset[str] | None:
        if label in self._table:
            return self._table[label]
        if label in COUNTRY_CODES:
            return frozenset({label})
        return None

    def covers(self, label: str, country: str) -> bool:
        countries = self.countries(label)
        return countries is not None and country in countries


@cache
def _bundled_regions() -> dict[str, frozenset[str]]:
    path = resources.files("jobhunt.matching") / "data" / "regions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(label): frozenset(codes) for label, codes in data.items()}
