"""Skill aliases: alternative names for the same skill (spec 06; constitution guardrail 3).

An alias names the same skill only, never a broader or related one ("Fargate" is not "ECS
Fargate", "Docker" is not "Kubernetes"). Matching is case-insensitive. The table ships inside the
package (skill_aliases.yaml) so installed copies and images have it.
"""

from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Self

from pydantic import Field, RootModel

from jobhunt.config_files import ConfigError, read_yaml_mapping

AliasList = list[str]


class SkillAliasesFile(RootModel[dict[str, AliasList]]):
    """skill_aliases.yaml: skill name -> its alternative names. Only for the JSON Schema."""

    root: dict[str, AliasList] = Field(
        description="Skill name to alternative names of the same skill (never broader ones)"
    )


class SkillAliases:
    def __init__(self, canonical_by_key: Mapping[str, str]) -> None:
        self._canonical = dict(canonical_by_key)  # casefolded name or alias -> skill name

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Sequence[str]], *, source: str) -> Self:
        names = {name.casefold(): name for name in mapping}
        canonical: dict[str, str] = {}
        for name, alias_list in mapping.items():
            if not name.strip():
                raise ConfigError(f"{source}: empty skill name")
            canonical[name.casefold()] = name
            seen: set[str] = set()
            for alias in alias_list:
                key = alias.casefold()
                if not alias.strip():
                    raise ConfigError(f"{source}: {name}: empty alias")
                if key == name.casefold():
                    raise ConfigError(f"{source}: {name}: alias of itself")
                if key in seen:
                    raise ConfigError(f"{source}: {name}: alias {alias!r} listed twice")
                if key in names:
                    raise ConfigError(f"{source}: {alias!r} is both a skill and an alias")
                if key in canonical:  # claimed by a skill listed earlier
                    owner = canonical[key]
                    raise ConfigError(f"{source}: {alias!r} is an alias of both {owner} and {name}")
                seen.add(key)
                canonical[key] = name
        return cls(canonical)

    @classmethod
    def load(cls, path: Path) -> Self:
        data = read_yaml_mapping(path)
        bad = [k for k, v in data.items() if not isinstance(v, list | type(None))]
        if bad:
            raise ConfigError(f"{path}: aliases must be lists, e.g. Kubernetes: [K8s]: {bad}")
        mapping = {str(k): [str(a) for a in v or []] for k, v in data.items()}
        return cls.from_mapping(mapping, source=str(path))

    def canonical(self, name: str) -> str | None:
        """The skill a name or alias refers to; None if the table doesn't know it."""
        return self._canonical.get(name.strip().casefold())

    def names_of(self, skill: str) -> list[str]:
        """The skill's name and every alias of it (aliases in lower case), for searching text."""
        target = self._resolve(skill)
        aliases = [key for key, name in self._canonical.items() if name.casefold() == target]
        return [skill, *sorted(set(aliases) - {skill.casefold()})]

    def same_skill(self, a: str, b: str) -> bool:
        return self._resolve(a) == self._resolve(b)

    def _resolve(self, name: str) -> str:
        return (self.canonical(name) or name.strip()).casefold()


def bundled_aliases() -> SkillAliases:
    path = Path(str(resources.files("jobhunt.profile") / "skill_aliases.yaml"))
    return SkillAliases.load(path)
