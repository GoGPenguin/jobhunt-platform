"""Canonical Job model, schema version 1.

Every source's parser produces this shape. See docs/spec/01-canonical-job-schema.md.

Two ways in:
- `Job.from_parser(data)` for new parser output: strict. Unknown fields and enum values are
  errors, so parser bugs end up as dead letters.
- `Job.from_storage(data)` for jobs read back from storage: lenient. Unknown fields are ignored
  and unknown enum values become `unknown`, so older code can read data from newer code.
"""

import hashlib
import re
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
    model_validator,
)

from jobhunt.domain.codes import COUNTRY_CODES, CURRENCY_CODES, LANGUAGE_CODES
from jobhunt.domain.normalize import clean_line, clean_text, normalize_url, to_utc

DESCRIPTION_MAX_CHARS = 50_000
POSTED_AFTER_COLLECTED_TOLERANCE = timedelta(days=1)

_SLUG = r"^[a-z0-9][a-z0-9:_-]{0,99}$"
_REGION_PATTERN = r"^[A-Z][A-Z0-9_]{1,31}$"
_REGION = re.compile(_REGION_PATTERN)
_SEMVER = r"^\d+\.\d+\.\d+$"


class Workplace(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    STAFF_PLUS = "staff_plus"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    YEAR = "year"
    MONTH = "month"
    WEEK = "week"
    DAY = "day"
    HOUR = "hour"
    UNKNOWN = "unknown"


class SalaryBasis(StrEnum):
    GROSS = "gross"
    NET = "net"
    UNKNOWN = "unknown"


def _line(max_chars: int) -> AfterValidator:
    def check(value: str) -> str:
        cleaned = clean_line(value)
        if not cleaned:
            raise ValueError("must not be blank")
        if len(cleaned) > max_chars:
            raise ValueError(f"must be at most {max_chars} characters")
        return cleaned

    return AfterValidator(check)


def _member_of(codes: frozenset[str], kind: str) -> AfterValidator:
    def check(value: str) -> str:
        if value not in codes:
            raise ValueError(f"not an {kind} code: {value!r}")
        return value

    return AfterValidator(check)


def _region(value: str) -> str:
    if not _REGION.fullmatch(value):
        raise ValueError(f"not a country code or region label (e.g. VN, APAC): {value!r}")
    return value


def _schema(**rules: JsonValue) -> Any:
    """JSON Schema rules mirroring a custom validator (documentation only, not enforced here)."""
    return Field(json_schema_extra=rules)


Title = Annotated[str, _line(300), _schema(minLength=1, maxLength=300)]
CompanyName = Annotated[str, _line(200), _schema(minLength=1, maxLength=200)]
PlaceName = Annotated[str, _line(200), _schema(minLength=1, maxLength=200)]
AttributionText = Annotated[str, _line(300), _schema(minLength=1, maxLength=300)]
LocationText = Annotated[str, _line(500), _schema(minLength=1, maxLength=500)]
CountryCode = Annotated[
    str, _member_of(COUNTRY_CODES, "ISO 3166-1 alpha-2 country"), _schema(pattern="^[A-Z]{2}$")
]
CurrencyCode = Annotated[
    str, _member_of(CURRENCY_CODES, "ISO 4217 currency"), _schema(pattern="^[A-Z]{3}$")
]
RegionCode = Annotated[str, AfterValidator(_region), _schema(pattern=_REGION_PATTERN)]
LanguageCode = Annotated[str, _schema(pattern="^([a-z]{2}|unknown)$")]
Description = Annotated[str, _schema(maxLength=DESCRIPTION_MAX_CHARS)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(to_utc)]
Amount = Annotated[Decimal, Field(ge=0)]
Years = Annotated[int, Field(ge=0, le=30)]
Slug = Annotated[str, Field(pattern=_SLUG)]
WebUrl = Annotated[str, Field(json_schema_extra={"format": "uri"})]


def _context(info: ValidationInfo) -> Mapping[str, Any]:
    return info.context if isinstance(info.context, Mapping) else {}


def _check_url(value: str, info: ValidationInfo) -> str:
    ctx = _context(info)
    return normalize_url(value, allow_http=bool(ctx.get("allow_http") or ctx.get("stored")))


class _Model(BaseModel):
    """Frozen, strict about unknown fields, lenient when reading stored data."""

    # Stored JSON always has every field, so the exported schema marks them all required.
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )

    @model_validator(mode="before")
    @classmethod
    def _lenient_when_stored(cls, data: Any, info: ValidationInfo) -> Any:
        if not (_context(info).get("stored") and isinstance(data, Mapping)):
            return data
        kept = {k: v for k, v in data.items() if k in cls.model_fields}
        for name, field in cls.model_fields.items():
            enum = field.annotation
            if (
                isinstance(enum, type)
                and issubclass(enum, StrEnum)
                and "unknown" in enum
                and name in kept
                and kept[name] not in enum
            ):
                kept[name] = "unknown"
        return kept


class Location(_Model):
    city: PlaceName | None = None
    region: PlaceName | None = None
    country: CountryCode | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.city is None and self.region is None and self.country is None:
            raise ValueError("location needs a city, region or country")
        return self


class Salary(_Model):
    min: Amount | None = None
    max: Amount | None = None
    currency: CurrencyCode
    period: SalaryPeriod
    basis: SalaryBasis

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.min is None and self.max is None:
            raise ValueError("salary needs a min or max amount")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("salary min must not exceed max")
        return self


class Attribution(_Model):
    text: AttributionText
    url: WebUrl

    _url = field_validator("url")(_check_url)


class ParserInfo(_Model):
    name: Slug
    version: Annotated[str, Field(pattern=_SEMVER)]


class Job(_Model):
    schema_version: Literal[1] = 1
    source: Slug
    external_id: Annotated[str, Field(min_length=1, max_length=500)]
    url: WebUrl
    title: Title
    company: CompanyName
    description: Description
    description_truncated: bool = False
    language: LanguageCode
    locations: tuple[Location, ...] = ()
    location_raw: LocationText | None = None
    workplace: Workplace
    remote_regions: tuple[RegionCode, ...] | None = None
    employment_type: EmploymentType
    seniority: Seniority
    years_experience_min: Years | None = None
    years_experience_max: Years | None = None
    salary: Salary | None = None
    visa_sponsorship: bool | None = None
    relocation_support: bool | None = None
    tags: tuple[str, ...] = ()
    posted_at: UtcDatetime | None = None
    expires_at: UtcDatetime | None = None
    collected_at: UtcDatetime
    attribution: Attribution | None = None
    raw_ref: Annotated[str, Field(min_length=1, max_length=500)]
    parser: ParserInfo
    extra: dict[str, JsonValue] = Field(default_factory=dict)

    _url = field_validator("url")(_check_url)

    @classmethod
    def from_parser(cls, data: Mapping[str, Any], *, allow_http: bool = False) -> Self:
        """Build from new parser output. Strict; `allow_http` comes from the source config."""
        return cls.model_validate(data, context={"allow_http": allow_http})

    @classmethod
    def from_storage(cls, data: Mapping[str, Any] | str | bytes) -> Self:
        """Load a stored job (dict or JSON). Lenient about unknown fields and enum values."""
        if isinstance(data, str | bytes):
            return cls.model_validate_json(data, context={"stored": True})
        return cls.model_validate(data, context={"stored": True})

    @model_validator(mode="before")
    @classmethod
    def _clean_description(cls, data: Any) -> Any:
        if not (isinstance(data, Mapping) and isinstance(data.get("description"), str)):
            return data
        text = clean_text(data["description"])
        if len(text) <= DESCRIPTION_MAX_CHARS:
            return {**data, "description": text}
        return {**data, "description": text[:DESCRIPTION_MAX_CHARS], "description_truncated": True}

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        if value != "unknown" and value not in LANGUAGE_CODES:
            raise ValueError(f"not an ISO 639-1 language code or 'unknown': {value!r}")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = (clean_line(tag).lower() for tag in value)
        return tuple(dict.fromkeys(tag for tag in cleaned if tag))

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        lo, hi = self.years_experience_min, self.years_experience_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("years_experience_min must not exceed years_experience_max")
        if self.posted_at and self.posted_at > self.collected_at + POSTED_AFTER_COLLECTED_TOLERANCE:
            raise ValueError("posted_at is more than a day after collected_at")
        return self


def external_id_from_url(url: str) -> str:
    """Id for sources without their own job id: SHA-256 of the normalized URL."""
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()
