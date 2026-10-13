"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio only.

    Returns:
        The name of the anyio backend.
    """
    return "asyncio"
