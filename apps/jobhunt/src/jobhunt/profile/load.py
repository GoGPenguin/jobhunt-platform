"""The whole profile, loaded once: master CV, preferences and skill aliases (spec 06, P7)."""

import logging
from dataclasses import dataclass
from pathlib import Path

from jobhunt.config_files import ConfigError
from jobhunt.profile.aliases import SkillAliases, bundled_aliases
from jobhunt.profile.master_cv import MasterCV, fact_skill_issues, load_master_cv
from jobhunt.profile.preferences import Preferences, load_preferences

log = logging.getLogger(__name__)

MASTER_CV = "master_cv.yaml"
PREFERENCES = "preferences.yaml"


@dataclass(frozen=True)
class Profile:
    master_cv: MasterCV | None  # None when the file doesn't exist yet
    preferences: Preferences
    aliases: SkillAliases

    def issues(self) -> list[str]:
        """Errors that need both files and the aliases (fact skills by name or alias)."""
        return fact_skill_issues(self.master_cv, self.aliases) if self.master_cv else []

    def warnings(self) -> list[str]:
        return self.master_cv.warnings() if self.master_cv else []


def load_profile(config_dir: Path) -> Profile:
    cv_path = config_dir / MASTER_CV
    return Profile(
        master_cv=load_master_cv(cv_path) if cv_path.exists() else None,
        preferences=load_preferences(config_dir / PREFERENCES),
        aliases=bundled_aliases(),
    )


def load_profile_lenient(config_dir: Path) -> tuple[Profile, list[str]]:
    """For unattended runs (the daily digest): a file that fails to load is left out and named
    in the returned problems, so the digest still goes out with a warning (decision 0038)."""
    problems: list[str] = []
    cv_path = config_dir / MASTER_CV
    try:
        master_cv = load_master_cv(cv_path) if cv_path.exists() else None
    except ConfigError as exc:
        log.warning("%s", exc)
        master_cv, problems = None, [MASTER_CV]
    try:
        preferences = load_preferences(config_dir / PREFERENCES)
    except ConfigError as exc:
        log.warning("%s", exc)
        preferences = Preferences()
        problems.append(PREFERENCES)
    profile = Profile(master_cv=master_cv, preferences=preferences, aliases=bundled_aliases())
    if profile.issues() and MASTER_CV not in problems:
        log.warning("%s: %s", MASTER_CV, "; ".join(profile.issues()))
        problems.insert(0, MASTER_CV)
    return profile, problems
