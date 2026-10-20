from datetime import UTC, datetime
from typing import Any

import pytest

from jobhunt.domain.job import ParserInfo
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import ParserRegistry


def noop(payload: RawPayload) -> list[dict[str, Any]]:
    return [{"title": payload.origin}]


def test_register_and_get() -> None:
    registry = ParserRegistry()
    registry.register("test-email", "1.2.0")(noop)
    plugin = registry.get("test-email")
    assert plugin.info == ParserInfo(name="test-email", version="1.2.0")
    payload = RawPayload(
        raw_ref="raw/x",
        origin="o",
        content_type="text/plain",
        content=b"",
        fetched_at=datetime.now(UTC),
    )
    assert plugin.parse(payload) == [{"title": "o"}]
    assert registry.names() == frozenset({"test-email"})


def test_duplicate_name_rejected() -> None:
    registry = ParserRegistry()
    registry.register("test-email", "1.0.0")(noop)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("test-email", "1.0.1")(noop)


@pytest.mark.parametrize(("name", "version"), [("Test Email", "1.0.0"), ("test-email", "1.0")])
def test_invalid_name_or_version(name: str, version: str) -> None:
    with pytest.raises(ValueError, match="should match pattern"):
        ParserRegistry().register(name, version)(noop)


def test_unknown_parser_lists_known() -> None:
    registry = ParserRegistry()
    registry.register("test-email", "1.0.0")(noop)
    with pytest.raises(KeyError, match="test-email"):
        registry.get("nope")
