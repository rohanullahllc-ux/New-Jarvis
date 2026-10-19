"""Central configuration: project paths and settings (loaded from .env).

Everything that varies per machine or per user lives in `.env` (see `.env.example`).
Every other module imports its settings from here - nothing reads os.environ directly.
"""
import os
import re
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


def number(name, default):
    """Read a whole-number setting; anything that isn't one falls back to the default."""
    try:
        return int(key(name))
    except ValueError:
        return default


def local_address(url):
    """"localhost" written as 127.0.0.1. On this kind of Windows PC a connection to "localhost" first tries IPv6, waits about
    two seconds for it to fail, and only then uses IPv4, where Ollama is listening: two seconds lost on every request to it
    (a chat answer makes several), against 30 milliseconds for 127.0.0.1."""
    return re.sub(r"//localhost(?=[:/]|$)", "//127.0.0.1", url, flags=re.I)


def decimal(name, default):
    """Read a setting that may have a fractional part; anything that isn't a number falls back to the default."""
    try:
        return float(key(name))
    except ValueError:
        return default


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
JARVIS_PASSWORD_HASH = key("JARVIS_PASSWORD_HASH")  # preferred: salted hash made by  python gate.py --set-password
FACE_CHECK = flag("FACE_CHECK", True)               # glance at the webcam after the password (never blocks entry)

# ---- Voice in / out ------------------------------------------------------
INPUT_MODE = key("INPUT_MODE", "voice").lower()     # "voice" or "text"
MIC_BACKEND = key("MIC_BACKEND", "auto").lower()    # auto | sounddevice | winmm
MIC_DEVICE = key("MIC_DEVICE")                      # blank = Windows default; or part of a device name, or an index
MIC_PAUSE = max(0.5, decimal("MIC_PAUSE", 1.3))     # seconds of silence that end what you are saying (longer = fewer cut-off sentences)
MIC_BEEP = flag("MIC_BEEP", True)                   # a short beep when the microphone has just been opened: "speak now"
SPEECH_LANGUAGE = key("SPEECH_LANGUAGE", "en-pk")   # what Google's speech recognition expects you to speak (en-pk, en-in, en-us, en-gb...)
SPEECH_LANGUAGE_FALLBACK = key("SPEECH_LANGUAGE_FALLBACK", "en-us")     # tried once when the first language understood nothing
TTS_ENABLED = flag("TTS_ENABLED", True)             # false = Jarvis answers in text only (much faster)
TTS_VOICE = key("TTS_VOICE")                        # part of a Windows voice name, e.g. Zira; blank = the Windows default voice
TTS_VOLUME = number("TTS_VOLUME", 100)              # 0 to 100
TTS_RATE = number("TTS_RATE", 0)                    # -10 (slower) to 10 (faster); 0 = normal
STARTUP_GREETING = key("STARTUP_GREETING", "short").lower()  # short | full | silent
GUI_ANIMATIONS = flag("GUI_ANIMATIONS", True)       # false = still pictures in the window (lighter on a slow PC)

# ---- AI brain (optional) --------------------------------------------------
ANTHROPIC_API_KEY = key("ANTHROPIC_API_KEY")
CLAUDE_MODEL = key("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = key("CLAUDE_EFFORT", "low")         # low = quickest replies; medium/high think more

# ---- Free AI model (optional): lets Jarvis answer questions no command pattern covers -------------
LLM_PROVIDER = key("LLM_PROVIDER", "auto").lower()  # auto | groq | gemini | openrouter | ollama | custom
LLM_API_KEY = key("LLM_API_KEY")                    # a FREE key from console.groq.com or aistudio.google.com
LLM_MODEL = key("LLM_MODEL")                        # blank = a sensible free model for the provider
LLM_BASE_URL = key("LLM_BASE_URL")                  # only for provider=custom (any OpenAI-compatible service)
OLLAMA_URL = local_address(key("OLLAMA_URL", "http://127.0.0.1:11434"))

# ---- Chat with a local AI model (Ollama): how Jarvis answers anything the commands don't cover ---------------
CHAT_ENGINE = key("CHAT_ENGINE", "auto").lower()    # auto | ollama | cloud (cloud = only the LLM_API_KEY service above)
OLLAMA_MODEL = key("OLLAMA_MODEL", "auto")          # auto = a quick installed model that fits in the free RAM
CHAT_AUTO_MAX_MB = number("CHAT_AUTO_MAX_MB", 1600) # "auto" never picks a model bigger than this: bigger ones answer slowly on a CPU
OLLAMA_KEEP_ALIVE = key("OLLAMA_KEEP_ALIVE", "10m") # how long the model stays in RAM after the last question
CHAT_MEMORY_TURNS = max(2, number("CHAT_MEMORY_TURNS", 8))    # most question-and-answer pairs kept in mind in one conversation
CHAT_WEB_SEARCH = flag("CHAT_WEB_SEARCH", True)     # look facts up on DuckDuckGo first (it sees the question)
CHAT_PRELOAD = flag("CHAT_PRELOAD", False)          # load the model at start-up (uses 1-2 GB RAM at once, answers sooner)
LANGUAGE_MODEL = flag("LANGUAGE_MODEL", True)       # use the model trained by training/train_nlu.py to understand loosely worded commands

# ---- A private record of conversations (Logs/conversations/), to look back at and improve Jarvis from -------------
LOG_CONVERSATIONS = flag("LOG_CONVERSATIONS", True)  # false = record nothing
CONVERSATION_LOG_DAYS = number("CONVERSATION_LOG_DAYS", 30)   # records older than this many days are deleted (0 = keep for ever)

# ---- Third-party services (all optional) --------------------------------
WOLFRAM_APP_ID = key("WOLFRAM_APP_ID")
NASA_API_KEY = key("NASA_API_KEY", "DEMO_KEY")      # DEMO_KEY works with low rate limits
EMAIL_ADDRESS = key("EMAIL_ADDRESS")
EMAIL_PASSWORD = key("EMAIL_PASSWORD")              # use an *app password*, never your real one
EMAIL_SMTP_HOST = key("EMAIL_SMTP_HOST")            # blank = worked out from the address (Gmail, Yahoo, Outlook, iCloud)
EMAIL_SMTP_PORT = number("EMAIL_SMTP_PORT", 587)
