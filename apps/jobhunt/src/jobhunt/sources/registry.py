"""Parser plugins, registered by name and semver version.

A parser turns one raw payload into records in the canonical job shape, without `source`,
`parser` and `raw_ref`, which `build_jobs` adds. Bump the version whenever the output changes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jobhunt.domain.job import ParserInfo
from jobhunt.sources.raw import RawPayload

ParseFn = Callable[[RawPayload], list[dict[str, Any]]]


@dataclass(frozen=True)
class ParserPlugin:
    info: ParserInfo
    parse: ParseFn


class ParserRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ParserPlugin] = {}

    def register(self, name: str, version: str) -> Callable[[ParseFn], ParseFn]:
        """Decorator: `@REGISTRY.register("linkedin-email", "1.0.0")`."""
        info = ParserInfo(name=name, version=version)  # validates name and semver
        if name in self._plugins:
            raise ValueError(f"parser {name!r} already registered")

        def decorator(parse: ParseFn) -> ParseFn:
            self._plugins[name] = ParserPlugin(info=info, parse=parse)
            return parse

        return decorator

    def get(self, name: str) -> ParserPlugin:
        try:
            return self._plugins[name]
        except KeyError:
            known = ", ".join(sorted(self._plugins)) or "none"
            raise KeyError(f"unknown parser {name!r}; known: {known}") from None

    def names(self) -> frozenset[str]:
        return frozenset(self._plugins)


REGISTRY = ParserRegistry()
