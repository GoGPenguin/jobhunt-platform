"""The `store` fixture runs every contract test against each JobStore implementation."""

from collections.abc import Iterator

import pytest

from jobhunt.store.memory import MemoryJobStore
from jobhunt.store.port import JobStore


@pytest.fixture(params=["memory"])
def store(request: pytest.FixtureRequest) -> Iterator[JobStore]:
    if request.param == "memory":
        yield MemoryJobStore()
