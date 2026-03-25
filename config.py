import os
from dotenv import load_dotenv
from platformdirs import user_config_dir

# Load credentials in priority order (each call only sets vars not already set):
#   1. OS environment variables — highest priority (set by MCP client or shell)
#   2. .env.local — dev override when running the server directly
#   3. ~/.config/central-mcp-server/.env (platform-appropriate path) — user config file
load_dotenv(".env.local", override=False)
load_dotenv(os.path.join(user_config_dir("central-mcp-server"), ".env"), override=False)

# These can be overridden by MCP inputs or environment variables
CENTRAL_BASE_URL = os.getenv("CENTRAL_BASE_URL", "")
CENTRAL_CLIENT_ID = os.getenv("CENTRAL_CLIENT_ID", "")
CENTRAL_CLIENT_SECRET = os.getenv("CENTRAL_CLIENT_SECRET", "")


def set_credentials(
    base_url: str = None, client_id: str = None, client_secret: str = None
):
    """
    Update credentials dynamically from MCP inputs.
    This MUST be called before using any tools.
    """
    global CENTRAL_BASE_URL, CENTRAL_CLIENT_ID, CENTRAL_CLIENT_SECRET
    if base_url:
        CENTRAL_BASE_URL = base_url
    if client_id:
        CENTRAL_CLIENT_ID = client_id
    if client_secret:
        CENTRAL_CLIENT_SECRET = client_secret


def get_credentials():
    """
    Get current credentials (without exposing the secret)
    """
    return {
        "base_url": CENTRAL_BASE_URL,
        "client_id": CENTRAL_CLIENT_ID,
        "has_secret": bool(CENTRAL_CLIENT_SECRET),
    }


def validate_credentials():
    """
    Validate that all required credentials are set.
    Raises ValueError if any are missing.
    """
    if not CENTRAL_BASE_URL:
        raise ValueError(
            "CENTRAL_BASE_URL is not set. Please call 'setup_credentials' tool first to provide: base_url, client_id, and client_secret."
        )
    if not CENTRAL_CLIENT_ID:
        raise ValueError(
            "CENTRAL_CLIENT_ID is not set. Please call 'setup_credentials' tool first to provide: base_url, client_id, and client_secret."
        )
    if not CENTRAL_CLIENT_SECRET:
        raise ValueError(
            "CENTRAL_CLIENT_SECRET is not set. Please call 'setup_credentials' tool first to provide: base_url, client_id, and client_secret."
        )
    return True
