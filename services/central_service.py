import threading
from pycentral import NewCentralBase
from config import (
    CENTRAL_BASE_URL,
    CENTRAL_CLIENT_ID,
    CENTRAL_CLIENT_SECRET,
    validate_credentials,
)


def get_central_connection() -> NewCentralBase:
    """
    Get a Central connection instance.
    This function can be used as a dependency in FastAPI routes.
    Validates that credentials are configured before creating connection.
    """
    # Validate credentials are set
    validate_credentials()

    return NewCentralBase(
        token_info={
            "new_central": {
                "base_url": CENTRAL_BASE_URL,
                "client_id": CENTRAL_CLIENT_ID,
                "client_secret": CENTRAL_CLIENT_SECRET,
            }
        },
    )


# Create a singleton instance for reuse
# Note: This will be created when first imported, so credentials must be set before any tools are used
central_conn = None
_conn_lock = threading.Lock()


def get_conn():
    """
    Get or create the central connection singleton.
    This lazy initialization allows credentials to be set before connection is created.
    Thread-safe via double-checked locking.
    """
    global central_conn
    if central_conn is None:
        with _conn_lock:
            if central_conn is None:
                central_conn = get_central_connection()
    return central_conn


def verify_connection(conn) -> None:
    """
    Verify credentials are valid by making a lightweight GET to the Central API.
    Raises RuntimeError with a clear message if the connection fails.
    """
    try:
        conn.command(
            api_method="GET", api_path="network-monitoring/v1/sites-health", api_params={"limit": 1}
        )
    except Exception as exc:
        raise RuntimeError(
            f"Central API connectivity check failed: {exc}. "
            "Check CENTRAL_BASE_URL, CENTRAL_CLIENT_ID, and CENTRAL_CLIENT_SECRET in .env"
        ) from exc
