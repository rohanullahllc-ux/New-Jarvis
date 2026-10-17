"""Central configuration: project paths and settings (loaded from .env).

Everything that varies per machine or per user lives in `.env` (see `.env.example`).
Every other module imports its settings from here - nothing reads os.environ directly.
"""
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


def key(name, default=""):
    return os.getenv(name, default).strip()


def flag(name, default=True):
    """Read a true/false setting ("1", "true", "yes", "on" mean true)."""
    value = key(name)
    return default if not value else value.lower() in {"1", "true", "yes", "on"}


# ---- Who and where ---------------------------------------------------------
USER_NAME = key("USER_NAME", "Mr Khan")            # how Jarvis addresses you
DEFAULT_CITY = key("DEFAULT_CITY", "Peshawar")      # used for weather when no city is named
HOME_CURRENCY = key("HOME_CURRENCY", "PKR").upper() # "dollar rate" converts to this

# ---- Access ---------------------------------------------------------------
JARVIS_PASSWORD = key("JARVIS_PASSWORD")                    # plain-text unlock password
JARVIS_PASSWORD_SHA256 = key("JARVIS_PASSWORD_SHA256").lower()  # preferred: sha256 hex of the password (python gate.py --set-password)

# ---- Voice in / out ------------------------------------------------------
INPUT_MODE = key("INPUT_MODE", "voice").lower()     # "voice" or "text"
MIC_BACKEND = key("MIC_BACKEND", "auto").lower()    # auto | sounddevice | winmm
MIC_DEVICE = key("MIC_DEVICE")                      # blank = Windows default; or part of a device name, or an index
TTS_ENABLED = flag("TTS_ENABLED", True)             # false = Jarvis answers in text only (much faster)
STARTUP_GREETING = key("STARTUP_GREETING", "short").lower()  # short | full | silent

# ---- AI brain (optional) --------------------------------------------------
ANTHROPIC_API_KEY = key("ANTHROPIC_API_KEY")
CLAUDE_MODEL = key("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = key("CLAUDE_EFFORT", "low")         # low = quickest replies; medium/high think more

# ---- Third-party services (all optional) --------------------------------
WOLFRAM_APP_ID = key("WOLFRAM_APP_ID")
NASA_API_KEY = key("NASA_API_KEY", "DEMO_KEY")      # DEMO_KEY works with low rate limits
RAPIDAPI_KEY = key("RAPIDAPI_KEY")
EMAIL_ADDRESS = key("EMAIL_ADDRESS")
EMAIL_PASSWORD = key("EMAIL_PASSWORD")              # use a Gmail *app password*
