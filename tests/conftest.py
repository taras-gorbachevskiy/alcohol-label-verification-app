from collections.abc import Iterator

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def reset_verify_rate_limiter() -> Iterator[None]:
    """Keep process-local limiter state isolated across every test."""

    original = app.state.verify_limiter
    original.reset()
    try:
        yield
    finally:
        current = app.state.verify_limiter
        current.reset()
        app.state.verify_limiter = original
        original.reset()
