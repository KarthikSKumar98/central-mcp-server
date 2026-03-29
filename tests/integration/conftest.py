import pytest
from unittest.mock import MagicMock
from config import validate_credentials
from services.central_service import get_conn


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: live API tests requiring credentials in .env.local"
    )


@pytest.fixture(scope="session")
def live_ctx():
    try:
        validate_credentials()
    except ValueError:
        pytest.skip("No credentials found in .env.local — skipping live tests")
    conn = get_conn()
    ctx = MagicMock()
    ctx.lifespan_context = {"conn": conn}
    return ctx
