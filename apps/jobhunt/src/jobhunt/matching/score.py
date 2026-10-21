"""Rule-based fit score, filters and ranking (spec 07). Computed at digest time from a stored
posting and the current profile; never stored. Pure functions over the profile.

score = 100 * Σ(weight * component) / Σ weights, each component between 0 and 1. Unknown
information is neutral (0.5 or 0.6), never 0.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from jobhunt.domain.job import Job, Salary
from jobhunt.matching.infer import seniority_levels, skills_found, years_required
from jobhunt.matching.places import Regions, location_countries
from jobhunt.profile.load import Profile
from jobhunt.store.fingerprint import fold, normalize_company
from jobhunt.store.port import Posting

LEVEL_WEIGHT = {"core": 1.0, "working": 0.7, "familiar": 0.4}
SKILLS_FOR_FULL_SCORE = 4.0
SENIORITY_ORDER = ("intern", "junior", "mid", "senior", "lead", "staff_plus")
PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}
UNKNOWN_HALF, UNKNOWN_SENIORITY = 0.5, 0.6

Component = tuple[float, str | None]  # value, reason shown in the digest (None: nothing to say)


@dataclass(frozen=True)
class Ranked:
    posting: Posting
    score: int  # 0-100
    reasons: tuple[str, ...]
    flags: tuple[str, ...]  # rank last: excluded keyword, below minimum salary
    filtered: str | None  # left out of the digest: excluded company, ineligible remote


class Matcher:
    def __init__(self, profile: Profile) -> None:
        self.prefs = profile.preferences
        self.cv = profile.master_cv
        self.aliases = profile.aliases
        self.regions = Regions.bundled().with_overrides(self.prefs.regions)
        self.weights = self.prefs.matching.weights.model_dump()
        location = self.prefs.candidate.location
        self.home = location.country if location else None

    def score(self, posting: Posting) -> Ranked:
        job = posting.representative.job
        countries = set().union(*(location_countries(j.job.locations) for j in posting.jobs))
        parts = {
            "title": self._title(job),
            "market": self._market(job, countries),
            "seniority": self._seniority(job),
            "experience": self._experience(job),
            "skills": self._skills(job),
        }
        total = sum(self.weights[name] * value for name, (value, _) in parts.items())
        score = round(100 * total / sum(self.weights.values()))
        reasons = tuple(reason for _, reason in parts.values() if reason)
        return Ranked(posting, score, reasons, self._flags(job), self._filtered(job))

    # Components

    def _title(self, job: Job) -> Component:
        roles, keywords = self.prefs.targets.roles, self.prefs.targets.role_keywords
        if not roles and not keywords:
            return UNKNOWN_HALF, None
        title = f" {fold(job.title)} "
        if any(f" {fold(role)} " in title for role in roles):
            return 1.0, "title ✓"
        hit = next((k for k in keywords if f" {fold(k)} " in title), None)
        return (0.6, f"title ~{hit}") if hit else (0.0, None)

    def _market(self, job: Job, countries: set[str]) -> Component:
        markets = self.prefs.markets
        if not markets:
            return UNKNOWN_HALF, None
        remote = job.workplace == "remote"
        for index, market in enumerate(markets):
            allowed = market.workplace
            if allowed and job.workplace != "unknown" and job.workplace not in allowed:
                continue
            covered = set(market.countries).union(*(self._countries(r) for r in market.regions))
            if countries & covered or (remote and self._remote_fits(job, covered, allowed)):
                return 1 - index / len(markets), f"{market.name} ({_ordinal(index + 1)})"
        return (UNKNOWN_HALF, None) if not countries and not remote else (0.0, None)

    def _remote_fits(self, job: Job, covered: set[str], workplace: Iterable[str]) -> bool:
        if workplace and "remote" not in workplace:
            return False
        stated = set().union(*(self._countries(r) for r in job.remote_regions or ()))
        return not stated or bool(stated & covered)  # not stated: open to anyone

    def _seniority(self, job: Job) -> Component:
        targets = set(self.prefs.targets.seniority)
        levels = {str(job.seniority)} if job.seniority != "unknown" else seniority_levels(job.title)
        if not targets or not levels:
            return UNKNOWN_SENIORITY, None
        if levels & targets:
            return 1.0, f"{sorted(levels & targets)[0]} ✓"
        index = SENIORITY_ORDER.index
        level = sorted(levels)[0]
        if any(abs(index(lv) - index(t)) == 1 for lv in levels for t in targets):
            return 0.5, f"{level} ~"
        return 0.0, f"{level} ✗"

    def _experience(self, job: Job) -> Component:
        years = job.years_experience_min
        if years is None:
            years = years_required(job.description)
        most = self.prefs.targets.years_experience_max
        if years is None or most is None:
            return UNKNOWN_SENIORITY, None
        if years <= most:
            return 1.0, f"{years}y ✓"
        return (0.5, f"{years}y ~") if years == most + 1 else (0.0, f"{years}y ✗")

    def _skills(self, job: Job) -> Component:
        if self.cv is None:
            return UNKNOWN_HALF, None
        text = " ".join([job.title, job.description, *job.tags])
        found = skills_found(text, self.cv.skills, self.aliases)
        if not found:
            return (UNKNOWN_HALF, None) if not job.description else (0.0, None)
        weight = sum(LEVEL_WEIGHT[level] for level in found.values())
        value = min(1.0, weight / SKILLS_FOR_FULL_SCORE)
        best = sorted(found, key=lambda name: (-LEVEL_WEIGHT[found[name]], name))[:3]
        return value, ", ".join(best)

    # Filters

    def _filtered(self, job: Job) -> str | None:
        company = normalize_company(job.company)
        if any(normalize_company(c) == company for c in self.prefs.filters.excluded_companies):
            return "excluded company"
        if self.prefs.filters.drop_remote_outside_eligibility and job.workplace == "remote":
            known = [r for r in job.remote_regions or () if self.regions.countries(r) is not None]
            if self.home and known and not any(self.regions.covers(r, self.home) for r in known):
                return f"remote not open to {self.home}"
        return None

    def _flags(self, job: Job) -> tuple[str, ...]:
        text = f" {fold(job.title + ' ' + job.description)} "
        keywords = self.prefs.filters.excluded_keywords
        flags = [f"excluded: {k}" for k in keywords if f" {fold(k)} " in text]
        if job.salary and self._below_minimum(job.salary):
            flags.append("below minimum salary")
        return tuple(flags)

    def _below_minimum(self, salary: Salary) -> bool:
        if salary.period not in PER_YEAR:
            return False
        upper = salary.max if salary.max is not None else salary.min
        if upper is None:
            return False
        yearly = upper * PER_YEAR[salary.period]
        return any(
            yearly < floor.amount * PER_YEAR[floor.period]
            for floor in self.prefs.filters.minimum_salary
            if floor.currency == salary.currency
        )

    def _countries(self, label: str) -> frozenset[str]:
        return self.regions.countries(label) or frozenset()


def rank(postings: Iterable[Posting], profile: Profile) -> list[Ranked]:
    """Every posting scored, unflagged first, then by score, then newest first. Filtered-out
    postings are included (callers leave them out of the digest but mark them as sent)."""
    matcher = Matcher(profile)
    scored = [matcher.score(posting) for posting in postings]

    def order(r: Ranked) -> tuple[bool, bool, int, float]:
        newest = -r.posting.first_seen_at.timestamp()
        return (r.filtered is not None, bool(r.flags), -r.score, newest)

    return sorted(scored, key=order)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
