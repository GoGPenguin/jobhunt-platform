"""Reading the YAML files people edit: sources.yaml, preferences.yaml, master_cv.yaml."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """A config file is missing, unreadable or invalid. The message names the file and entry."""


_BOOL = "tag:yaml.org,2002:bool"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys instead of silently keeping the last one, and
    follows YAML 1.2 booleans: only true/false. YAML 1.1 also reads yes/no/on/off as booleans,
    which turns the country code NO (Norway) into false."""


_StrictLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != _BOOL]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver(
    _BOOL, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML file whose top level must be a mapping."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path}: not found") from None
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def describe_location(data: Mapping[str, Any], loc: tuple[int | str, ...]) -> str:
    """Readable location of a validation error, naming list entries by their id when they
    have one, e.g. `email.sources[1] (itviec-email).parser`. Never includes the values."""
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
