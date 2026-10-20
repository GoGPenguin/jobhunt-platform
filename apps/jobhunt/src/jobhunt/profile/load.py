"""The whole profile, loaded once: master CV, preferences and skill aliases (spec 06, P7)."""

from dataclasses import dataclass
from pathlib import Path

from jobhunt.profile.aliases import SkillAliases, bundled_aliases
from jobhunt.profile.master_cv import MasterCV, fact_skill_issues, load_master_cv
from jobhunt.profile.preferences import Preferences, load_preferences

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
