"""What the matcher reads out of a job's text (spec 07). The canonical schema leaves these to
the matcher on purpose (spec 01): seniority from title words, required years from the
description, and the candidate's skills mentioned anywhere in the job. Pure functions.
"""

import re
from collections.abc import Iterable

from jobhunt.profile.aliases import SkillAliases
from jobhunt.profile.master_cv import Skill
from jobhunt.store.fingerprint import fold

# Generic title vocabulary (folded), English and Vietnamese; not profession-specific.
_LEVEL_PHRASES = {
    "intern": "intern", "internship": "intern",
    "junior": "junior", "jr": "junior", "fresher": "junior", "entry level": "junior",
    "mid": "mid", "middle": "mid", "intermediate": "mid",
    "senior": "senior", "sr": "senior", "cao cap": "senior",
    "lead": "lead", "truong nhom": "lead",
    "staff": "staff_plus", "principal": "staff_plus",
}  # fmt: skip
_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:\+|(?:-|\u2013|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?|năm)\b",
    re.IGNORECASE,
)
MAX_PLAUSIBLE_YEARS = 30


def seniority_levels(title: str) -> set[str]:
    """Seniority values (job schema enum) named by whole words in a title."""
    text = f" {fold(title)} "
    return {level for phrase, level in _LEVEL_PHRASES.items() if f" {phrase} " in text}


def years_required(text: str) -> int | None:
    """Smallest plausible "N years" figure in the text ("3+ years", "2-4 years", "2 năm")."""
    figures = [int(m.group(1)) for m in _YEARS.finditer(text)]
    plausible = [n for n in figures if n <= MAX_PLAUSIBLE_YEARS]
    return min(plausible) if plausible else None


def skills_found(text: str, skills: Iterable[Skill], aliases: SkillAliases) -> dict[str, str]:
    """Skill name -> level, for CV skills named in the text by name or alias, as whole words.
    Names that fold to a single character ("C", "C++") are skipped: too many false matches."""
    folded = f" {fold(text)} "
    found: dict[str, str] = {}
    for skill in skills:
        for name in aliases.names_of(skill.name):
            key = fold(name)
            if len(key.replace(" ", "")) > 1 and f" {key} " in folded:
                found[skill.name] = skill.level
                break
    return found
