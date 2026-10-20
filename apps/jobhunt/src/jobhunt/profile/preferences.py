"""preferences.yaml version 1: what the candidate is looking for (spec 06).

Nothing about a profession is hardcoded anywhere else; targets, markets and filters come from
here (constitution guardrail 5). A missing file means defaults: no language filter, UTC, no
markets or filters. Errors name the entry, never the values.
"""

import logging
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from jobhunt.config_files import ConfigError, describe_location, read_yaml_mapping
from jobhunt.domain.codes import LANGUAGE_CODES
from jobhunt.domain.job import CountryCode, CurrencyCode, RegionCode, Seniority, Workplace

log = logging.getLogger(__name__)

Text = Annotated[str, Field(min_length=1)]


def _language(code: str) -> str:
    if code not in LANGUAGE_CODES:
        raise ValueError(f"not an ISO 639-1 language code: {code!r}")
    return code


def _timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"not a known IANA timezone: {name!r}") from None
    return name


LanguageCode = Annotated[str, AfterValidator(_language)]
TimezoneName = Annotated[str, AfterValidator(_timezone)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CandidateLocation(_Model):
    city: Text | None = None
    country: CountryCode


class Candidate(_Model):
    location: CandidateLocation | None = None
    timezone: TimezoneName = "UTC"


class Targets(_Model):
    roles: list[Text] = []
    role_keywords: list[Text] = []
    seniority: list[Seniority] = []
    years_experience_max: Annotated[int, Field(ge=0, le=30)] | None = None


class Market(_Model):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,49}$")]
    countries: list[CountryCode] = []
    regions: list[RegionCode] = []
    workplace: list[Workplace] = []
    prefer: Text | None = None


class MinimumSalary(_Model):
    amount: Annotated[Decimal, Field(gt=0)]
    currency: CurrencyCode
    period: Literal["year", "month", "week", "day", "hour"]


class Filters(_Model):
    drop_remote_outside_eligibility: bool = True
    excluded_companies: list[Text] = []  # compared after normalize_company
    excluded_keywords: list[Text] = []  # whole word, case-insensitive; rank last, never drop
    minimum_salary: list[MinimumSalary] = []


class Languages(_Model):
    postings: Annotated[list[LanguageCode], Field(min_length=1)] | None = None
    outputs: list[LanguageCode] = ["en"]


class Preferences(_Model):
    schema_version: Literal[1] = 1
    candidate: Candidate = Candidate()
    looking_for: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    targets: Targets = Targets()
    markets: list[Market] = []  # priority order: first = most preferred
    filters: Filters = Filters()
    languages: Languages = Languages()

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for name, count in Counter(m.name for m in self.markets).items():
            if count > 1:
                raise ValueError(f"duplicate market {name!r}")
        floors = Counter((s.currency, s.period) for s in self.filters.minimum_salary)
        for (currency, period), count in floors.items():
            if count > 1:
                raise ValueError(f"more than one minimum_salary for {currency}/{period}")
        return self

    @property
    def accepted_languages(self) -> frozenset[str] | None:
        """Posting languages to keep at collection, or None for no language filter."""
        postings = self.languages.postings
        return frozenset(postings) if postings else None

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.candidate.timezone)


def load_preferences(path: Path) -> Preferences:
    if not path.exists():
        log.warning("%s not found: using defaults (no language filter, UTC)", path)
        return Preferences()
    data = read_yaml_mapping(path)
    try:
        return Preferences.model_validate(data)
    except ValidationError as exc:
        lines = [f"{describe_location(data, e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"{path}:\n  " + "\n  ".join(lines)) from None
