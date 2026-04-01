import os

from dotenv import load_dotenv
from platformdirs import user_config_dir

# Load credentials in priority order (each call only sets vars not already set):
#   1. OS environment variables — highest priority (set by MCP client env block)
#   2. .env in project root — dev credentials file (create for local dev, gitignored)
#   3. ~/.config/central-mcp-server/.env (platform-appropriate path) — user config file fallback
load_dotenv(".env", override=False)
load_dotenv(os.path.join(user_config_dir("central-mcp-server"), ".env"), override=False)

CENTRAL_BASE_URL = os.getenv("CENTRAL_BASE_URL", "")
CENTRAL_CLIENT_ID = os.getenv("CENTRAL_CLIENT_ID", "")
CENTRAL_CLIENT_SECRET = os.getenv("CENTRAL_CLIENT_SECRET", "")
DYNAMIC_TOOLS = os.getenv("DYNAMIC_TOOLS", "false").lower() == "true"

def validate_credentials():
    """Validate that all required credentials are set.

    Raises ValueError if any are missing.
    """
    if not CENTRAL_BASE_URL:
        raise ValueError(
            "CENTRAL_BASE_URL is not set. Add it to the env block in your MCP client config, or create a .env file in the project root for local development."
        )
    if not CENTRAL_CLIENT_ID:
        raise ValueError(
            "CENTRAL_CLIENT_ID is not set. Add it to the env block in your MCP client config, or create a .env file in the project root for local development."
        )
    if not CENTRAL_CLIENT_SECRET:
        raise ValueError(
            "CENTRAL_CLIENT_SECRET is not set. Add it to the env block in your MCP client config, or create a .env file in the project root for local development."
        )
    return True
