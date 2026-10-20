"""master_cv.yaml version 1: the facts generated CVs may use (spec 06; constitution guardrail 2).

Rules checked here: unique fact ids, every number of a fact appears literally in its texts,
valid dates, no unknown keys. Fact skills are checked against `skills` and the alias table by
`fact_skill_issues` (it needs the aliases). Errors name the entry, never the CV text.
"""

import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from jobhunt.config_files import ConfigError, describe_location, read_yaml_mapping
from jobhunt.profile.aliases import SkillAliases

FactId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")]
Text = Annotated[str, Field(min_length=1)]
Level = Literal["core", "working", "familiar"]
# A figure: digits with separators, ranges, ratios, %, + or a k/M suffix; no words or spaces.
_FIGURE = re.compile(r"^[$€£₫]?\d[\d.,]*(?:[\u2013-]\d[\d.,]*)?(?:/\d[\d.,]*)?[%+kMx]?$")


def _figure(value: str) -> str:
    if not _FIGURE.match(value):
        raise ValueError(f"{value!r} is not a figure: list the figure only, e.g. '2' or '40%'")
    return value


Figure = Annotated[str, AfterValidator(_figure)]


def contains_figure(text: str, figure: str) -> bool:
    """`figure` appears in `text` as a whole figure: "2" is not found in "12", "2024" or "3.2"."""
    whole = rf"(?<![\w.,]){re.escape(figure)}(?![\w]|[.,]\d)"
    return re.search(whole, text) is not None


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fact(_Model):
    id: FactId
    en: Text
    vi: Text | None = None
    vi_reviewed: bool = False
    skills: list[Text] = []
    numbers: list[Figure] = []

    @field_validator("numbers")
    @classmethod
    def _numbers_in_texts(cls, numbers: list[str], info: ValidationInfo) -> list[str]:
        for text_field in ("en", "vi"):
            text = info.data.get(text_field)
            for number in numbers:
                if text and not contains_figure(text, number):
                    raise ValueError(f"{number!r} not found in {text_field} text")
        return numbers


class Language(_Model):
    name: Text
    level: Text
    vi: Text | None = None


class Contact(_Model):
    name: Text
    location: Text
    email: Text
    phone: Text | None = None
    linkedin: Annotated[str, Field(pattern=r"^https://")] | None = None
    languages: list[Language] = []


class Skill(_Model):
    name: Text
    category: Text
    level: Level = "working"  # the user's own rating; used for ranking only, never on a CV


class _Dated(_Model):
    start: YearMonth
    end: YearMonth | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end is not None and self.end < self.start:  # YYYY-MM sorts as text
            raise ValueError("end is before start")
        return self


class Project(_Model):
    name: Text
    description: Text
    description_vi: Text | None = None
    facts: list[Fact] = []


class Experience(_Dated):
    id: FactId
    company: Text
    title: Text
    title_vi: Text | None = None
    location: Text
    projects: list[Project] = []


class Certification(_Model):
    name: Text
    code: Text | None = None
    date: YearMonth


class Education(_Dated):
    institution: Text
    institution_vi: Text | None = None
    degree: Text
    degree_vi: Text | None = None
    location: Text
    gpa: Text | None = None


class MasterCV(_Model):
    schema_version: Literal[1]
    profile: Contact
    summary: list[Fact] = []
    skills: list[Skill] = []
    experience: list[Experience] = []
    certifications: list[Certification] = []
    education: list[Education] = []

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for fact_id, count in Counter(f.id for f in self.facts()).items():
            if count > 1:
                raise ValueError(f"duplicate fact id {fact_id!r}")
        for name, count in Counter(s.name.casefold() for s in self.skills).items():
            if count > 1:
                raise ValueError(f"duplicate skill {name!r}")
        return self

    def located_facts(self) -> list[tuple[str, Fact]]:
        """Every fact with its location, named like validation errors."""
        located = [(f"summary[{i}] ({f.id})", f) for i, f in enumerate(self.summary)]
        for e, exp in enumerate(self.experience):
            for p, project in enumerate(exp.projects):
                prefix = f"experience[{e}] ({exp.id}).projects[{p}]"
                for i, fact in enumerate(project.facts):
                    located.append((f"{prefix}.facts[{i}] ({fact.id})", fact))
        return located

    def facts(self) -> list[Fact]:
        return [fact for _, fact in self.located_facts()]

    def skill(self, name: str) -> Skill:
        return next(s for s in self.skills if s.name.casefold() == name.casefold())

    def warnings(self) -> list[str]:
        """Problems that don't make the file invalid, named by location only."""
        found = [
            f"{where}.vi: not reviewed yet (vi_reviewed: false)"
            for where, fact in self.located_facts()
            if fact.vi and not fact.vi_reviewed
        ]
        if not self.profile.linkedin:
            found.append("profile.linkedin: empty")
        return found


def fact_skill_issues(cv: MasterCV, aliases: SkillAliases) -> list[str]:
    """Fact skills that aren't in `skills`, by name or by an alias of a listed skill."""
    issues = []
    for where, fact in cv.located_facts():
        for name in fact.skills:
            if not any(aliases.same_skill(name, skill.name) for skill in cv.skills):
                issues.append(f"{where}.skills: {name!r} is not in skills (by name or alias)")
    return issues


def load_master_cv(path: Path) -> MasterCV:
    data = read_yaml_mapping(path)
    try:
        return MasterCV.model_validate(data)
    except ValidationError as exc:
        # Our own messages and locations only: Pydantic's default text would echo CV sentences.
        lines = [f"{describe_location(data, e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"{path}:\n  " + "\n  ".join(lines)) from None
