import asyncio
import os
from unittest.mock import MagicMock

import pytest

from constants import API_CONCURRENCY_LIMIT
from config import validate_credentials
from services.central_service import get_conn


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: live API tests requiring credentials (.env or MCP env block)",
    )


@pytest.fixture(scope="session")
def live_ctx():
    # Same credential path as the deployed v0.1.8 server: OS env vars or a
    # root .env file, resolved by config.load_dotenv (see config.py).
    try:
        validate_credentials()
    except ValueError as exc:
        # In the per-release verification gate (make verify-live) missing
        # credentials must FAIL the gate, not silently skip — a skipped live
        # suite is not a passing gate. Outside the gate, skip as before so
        # `uv run pytest tests/` stays green without credentials.
        if os.getenv("CENTRAL_LIVE_REQUIRED"):
            pytest.fail(
                f"CENTRAL_LIVE_REQUIRED set but credentials are missing: {exc}. "
                "The release gate requires live Central credentials in the "
                "environment or a root .env file."
            )
        pytest.skip("No credentials found (.env / env block) — skipping live tests")
    conn = get_conn()
    ctx = MagicMock()
    ctx.lifespan_context = {
        "conn": conn,
        "api_semaphore": asyncio.Semaphore(API_CONCURRENCY_LIMIT),
    }
    return ctx
