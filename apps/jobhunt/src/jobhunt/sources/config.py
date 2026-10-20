"""sources.yaml: which sources exist and how they are fetched. See spec 02, phase A.

Phase A covers the `email` section only; company-board families arrive in phase B.
"""

from collections import Counter
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jobhunt.config_files import ConfigError, read_yaml_mapping
from jobhunt.domain.job import Slug

_SENDER = r"^@([a-z0-9-]+\.)+[a-z]{2,}$"
_CRON = r"^\S+( \S+){4}$"

Sender = Annotated[str, Field(pattern=_SENDER, description="Sender domain, e.g. @linkedin.com")]
Cron = Annotated[str, Field(pattern=_CRON, description="Cron expression with five fields")]


def is_linkedin(sender: str) -> bool:
    domain = sender.removeprefix("@")
    return domain == "linkedin.com" or domain.endswith(".linkedin.com")


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ImapSettings(_Config):
    host: str = "imap.gmail.com"
    port: int = 993
    label: Annotated[str, Field(min_length=1, description="Gmail label holding alert emails")]


class EmailSource(_Config):
    id: Slug
    parser: Slug
    senders: Annotated[tuple[Sender, ...], Field(alias="from", min_length=1)]
    page_fetch: Literal["allowed", "forbidden"]
    reason: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _page_fetch_rules(self) -> Self:
        if self.page_fetch == "forbidden" and not self.reason:
            raise ValueError("page_fetch: forbidden needs a reason")
        linkedin = self.parser.startswith("linkedin") or any(map(is_linkedin, self.senders))
        if linkedin and self.page_fetch != "forbidden":
            raise ValueError("LinkedIn sources must have page_fetch: forbidden (constitution)")
        return self


class EmailSection(_Config):
    imap: ImapSettings
    schedule: Cron = "*/30 * * * *"
    sources: tuple[EmailSource, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for source_id, count in Counter(s.id for s in self.sources).items():
            if count > 1:
                raise ValueError(f"duplicate source id {source_id!r}")
        for sender, count in Counter(x for s in self.sources for x in s.senders).items():
            if count > 1:
                raise ValueError(f"{sender!r} is routed to more than one source")
        return self


class SourcesConfig(_Config):
    schema_version: Literal[1]
    email: EmailSection | None = None


def load_sources(path: Path, *, known_parsers: Collection[str]) -> SourcesConfig:
    """Load and validate sources.yaml. Errors name the file and the entry, e.g.
    `email.sources[1] (itviec-email).page_fetch: ...`."""
    data = read_yaml_mapping(path)
    try:
        config = SourcesConfig.model_validate(data)
    except ValidationError as exc:
        lines = [f"{_where(data, e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"{path}:\n  " + "\n  ".join(lines)) from None
    if config.email:
        for index, source in enumerate(config.email.sources):
            if source.parser not in known_parsers:
                raise ConfigError(
                    f"{path}: email.sources[{index}] ({source.id}): unknown parser "
                    f"{source.parser!r}; known: {', '.join(sorted(known_parsers))}"
                )
    return config


def _where(data: Mapping[str, Any], loc: tuple[int | str, ...]) -> str:
    """Readable location, naming list entries by their id when they have one."""
    parts: list[str] = []
    node: Any = data
    for key in loc:
        node = _child(node, key)
        if isinstance(key, int) and parts:
            entry_id = node.get("id") if isinstance(node, Mapping) else None
            parts[-1] += f"[{key}]" + (f" ({entry_id})" if entry_id else "")
        else:
            parts.append(str(key))
    return ".".join(parts) or "(top level)"


def _child(node: Any, key: int | str) -> Any:
    if isinstance(node, Mapping):
        return node.get(key)
    if isinstance(node, list) and isinstance(key, int) and 0 <= key < len(node):
        return node[key]
    return None
