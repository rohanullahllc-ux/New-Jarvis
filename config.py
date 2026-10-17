"""Central configuration: project paths and API keys (loaded from .env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "DataBase"
LOGS_DIR = BASE_DIR / "Logs"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def path(*parts):
    """Build an absolute path inside the project, e.g. path('DataBase', 'Tasks')."""
    return str(BASE_DIR.joinpath(*parts))


def key(name, default=""):
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = key("ANTHROPIC_API_KEY")
CLAUDE_MODEL = key("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = key("CLAUDE_EFFORT", "low")  # low = quickest replies; medium/high think more
WOLFRAM_APP_ID = key("WOLFRAM_APP_ID")
NASA_API_KEY = key("NASA_API_KEY", "DEMO_KEY")  # DEMO_KEY works with low rate limits
DEFAULT_CITY = key("DEFAULT_CITY", "Peshawar")
INPUT_MODE = key("INPUT_MODE", "voice").lower()  # "voice" or "text"
EMAIL_ADDRESS = key("EMAIL_ADDRESS")
EMAIL_PASSWORD = key("EMAIL_PASSWORD")  # Gmail app password
RAPIDAPI_KEY = key("RAPIDAPI_KEY")  # business names, free games, corona stats
