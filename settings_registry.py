"""The list of every setting Jarvis has: one place that says what each one is called, what it means, what it may be set to
and what it is set to when you say nothing.

Three things are made from this list, so that they can never disagree with each other:
  * the setup wizard asks its questions from it and checks the answers against it,
  * the admin panel draws its pages from it (one control per setting, the right kind of control for each),
  * .env.example and the settings table in MANUAL.md are written from it:

    python settings_registry.py --write-example     rewrite .env.example
    python settings_registry.py --write-manual      rewrite the settings table inside MANUAL.md
    python settings_registry.py --check             say whether those two files are up to date and whether config.py agrees

config.py is what the program really reads, and it keeps its own defaults; tests/test_settings_registry.py compares the two, so a
setting added to one and forgotten in the other is caught. To add a setting: add it to config.py, add a Setting below, run the two
--write commands. (Standard library only: the setup wizard runs before anything is installed.)
"""
import re
import sys
import textwrap
from collections import namedtuple
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

Group = namedtuple("Group", "id title blurb")
Result = namedtuple("Result", "ok value message")


class Setting:
    """One setting. ``kind`` is text | int | float | bool | choice | secret."""

    def __init__(self, key, label, group, kind, default, help, choices=(), strict=True, minimum=None, maximum=None,
                 unit="", advanced=False, hidden=False, options_from="", commented_in_example=False, zero_allowed=False,
                 pattern=None, pattern_message=""):
        self.key, self.label, self.group, self.kind, self.default, self.help = key, label, group, kind, str(default), help
        self.choices = tuple(choices)                  # ((value, what it means), ...)
        self.strict = strict                           # a choice must be one of the choices (False: anything may be typed, the list suggests)
        self.minimum, self.maximum, self.unit = minimum, maximum, unit
        self.advanced = advanced                       # shown only when "advanced settings" is ticked
        self.hidden = hidden                           # has its own button instead of a box (the password)
        self.options_from = options_from               # the choices are made on this PC: piper_voices | mic_devices | ollama_models | windows_voices
        self.commented_in_example = commented_in_example   # written as "# KEY=value" in .env.example: only set it when you need it
        self.zero_allowed = zero_allowed               # 0 is allowed besides minimum..maximum (it means "automatic" or "off")
        self.pattern, self.pattern_message = pattern, pattern_message

    @property
    def secret(self):
        return self.kind == "secret"

    def choice_values(self):
        return [value for value, _ in self.choices]

    def __repr__(self):
        return f"Setting({self.key})"


GROUPS = (
    Group("you", "About you", "Who you are and where you are, so that greetings, weather and money fit you."),
    Group("speaking", "How Jarvis speaks", "His voice, its volume and speed, and what he says when he starts."),
    Group("hearing", "How Jarvis hears you", "The microphone, the speech recognition, and how long a pause ends your sentence."),
    Group("waking", "Waking and security", "How he is woken, whose voice he answers, and the password in front of everything."),
    Group("brain", "Thinking and chatting", "The AI model that answers questions the built-in commands do not cover."),
    Group("services", "Accounts and online services", "Email and the optional online services. Every one of them is optional."),
    Group("privacy", "Privacy and records", "What is written down, for how long, and what is sent out of this PC."),
    Group("window", "The window", "How the window looks and behaves."),
)

YES_NO = (("true", "On"), ("false", "Off"))
_CITY = r"[^\n\r]{1,60}"

SETTINGS = (
    # ---- About you
    Setting("USER_NAME", "Your name", "you", "text", "Mr Khan",
            "How Jarvis greets you, for example \"Good morning Mr Khan\"."),
    Setting("ADDRESS_AS", "What Jarvis calls you", "you", "choice", "sir",
            "The short word Jarvis puts in his replies, such as \"Ok sir\". Whatever you choose replaces \"sir\" everywhere.",
            choices=(("sir", "sir"), ("ma'am", "ma'am"), ("boss", "boss"), ("chief", "chief"), ("captain", "captain")), strict=False),
    Setting("DEFAULT_CITY", "Your city", "you", "text", "Peshawar",
            "Used for the weather and for \"where am I\" when you do not name a city."),
    Setting("HOME_CURRENCY", "Your currency", "you", "choice", "PKR",
            "\"Dollar rate\" and \"100 dollars in rupees\" convert into this currency. Use its three-letter code.",
            choices=tuple((code, code) for code in ("PKR", "USD", "EUR", "GBP", "AED", "SAR", "INR", "CAD", "AUD")), strict=False,
            pattern=r"[A-Za-z]{3}", pattern_message="a currency code is three letters, such as PKR or USD"),

    # ---- How Jarvis speaks
    Setting("TTS_ENABLED", "Speak out loud", "speaking", "bool", "true",
            "Off means Jarvis answers in text only, which is much faster. The replies still appear in the window."),
    Setting("TTS_ENGINE", "Which voice", "speaking", "choice", "auto",
            "Automatic uses the natural voice (Piper, made on this PC) when one is installed and the Windows voice otherwise.",
            choices=(("auto", "Automatic"), ("piper", "The natural voice"), ("windows", "The Windows voice"))),
    Setting("PIPER_VOICE", "The natural voice", "speaking", "choice", "en_GB-alan-medium",
            "Which natural voice speaks. python tts_piper.py --demo plays every installed voice, and the setup wizard can add more.",
            choices=(("en_GB-alan-medium", "Alan (British man)"), ("en_US-ryan-medium", "Ryan (American man)"),
                     ("en_GB-northern_english_male-medium", "Northern English man"), ("en_US-lessac-medium", "Lessac (American woman)")),
            strict=False, options_from="piper_voices"),
    Setting("TTS_VOICE", "The Windows voice", "speaking", "choice", "",
            "Only used when the natural voice is not. Part of a Windows voice name, for example Zira or David. Blank = the Windows default.",
            strict=False, options_from="windows_voices", advanced=True),
    Setting("TTS_VOLUME", "Speaking volume", "speaking", "int", 100, "How loud Jarvis speaks, 0 to 100.",
            minimum=0, maximum=100, unit="percent"),
    Setting("TTS_RATE", "Speaking speed", "speaking", "int", 0,
            "-10 is slower, 10 is faster, 0 is normal. Run python speech.py to hear the result.", minimum=-10, maximum=10),
    Setting("STARTUP_GREETING", "What he says when he starts", "speaking", "choice", "short",
            "One short greeting, or the full report (weather, today's time table, your to-do list and a low-battery warning), or nothing.",
            choices=(("short", "One short greeting"), ("full", "The full report"), ("silent", "Nothing"))),

    # ---- How Jarvis hears you
    Setting("INPUT_MODE", "Talk or type", "hearing", "choice", "voice",
            "Voice means you talk to Jarvis. Text means you type your commands instead and the microphone is never touched.",
            choices=(("voice", "Talk to him"), ("text", "Type to him"))),
    Setting("STT_ENGINE", "Speech recognition", "hearing", "choice", "auto",
            "Automatic uses Whisper on this PC and asks Google only when Whisper heard nothing. Whisper never uses the internet. "
            "Google is the old way and needs the internet.",
            choices=(("auto", "Automatic"), ("whisper", "Whisper only (offline)"), ("google", "Google only (online)"))),
    Setting("STT_MODEL", "Whisper model", "hearing", "choice", "base.en",
            "tiny.en is the quickest, base.en is the balance, small.en is the most accurate and the slowest. A bigger one needs a stronger PC.",
            choices=(("tiny.en", "tiny.en (quickest)"), ("base.en", "base.en (balanced)"), ("small.en", "small.en (most accurate)"))),
    Setting("SPEECH_LANGUAGE", "Your accent (for Google)", "hearing", "choice", "en-pk",
            "The accent Google's speech recognition expects: en-pk is Pakistani English. If a different one hears you better, use that.",
            choices=(("en-pk", "Pakistani English"), ("en-in", "Indian English"), ("en-us", "American English"),
                     ("en-gb", "British English"), ("en-au", "Australian English"), ("en-ca", "Canadian English")), strict=False,
            pattern=r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", pattern_message="a language code looks like en-pk or en-us"),
    Setting("SPEECH_LANGUAGE_FALLBACK", "Second accent to try", "hearing", "choice", "en-us",
            "Tried once when the first accent understood nothing.",
            choices=(("en-us", "American English"), ("en-gb", "British English"), ("en-in", "Indian English"), ("en-pk", "Pakistani English")),
            strict=False, advanced=True, pattern=r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", pattern_message="a language code looks like en-pk or en-us"),
    Setting("MIC_DEVICE", "Microphone", "hearing", "choice", "",
            "Blank = the Windows default microphone. Otherwise part of its name (for example Realtek or Headset) or its number: "
            "python microphone.py --list shows them.", strict=False, options_from="mic_devices"),
    Setting("MIC_BACKEND", "Microphone method", "hearing", "choice", "auto",
            "Automatic tries sounddevice first and falls back to Windows' own winmm. Force one only if the other misbehaves.",
            choices=(("auto", "Automatic"), ("sounddevice", "sounddevice"), ("winmm", "winmm (built into Windows)")), advanced=True),
    Setting("MIC_PAUSE", "Pause that ends a sentence", "hearing", "float", 1.3,
            "Seconds of silence that end what you are saying. Raise it if Jarvis cuts you off while you think; lower it for quicker answers.",
            minimum=0.5, maximum=5.0, unit="seconds"),
    Setting("MIC_BEEP", "Beep when he starts listening", "hearing", "bool", "true",
            "A short beep when the microphone has just been opened. It means \"speak now\"."),
    Setting("MIC_VOLUME", "Windows microphone volume", "hearing", "int", 80,
            "A microphone that is muted, or turned down under 50 percent in Windows, is the commonest reason Jarvis misses words. When he "
            "finds it like that at start-up he sets it to this many percent (he never turns a louder one down). 0 = never touch Windows' setting.",
            minimum=0, maximum=100, unit="percent"),

    # ---- Waking and security
    Setting("WAKE_WORD", "Wake with \"hey Jarvis\"", "waking", "bool", "true",
            "While the window is open and he is asleep, saying \"hey Jarvis\" wakes him (he then asks for the password as usual). "
            "It is recognised on this PC; no sound is sent anywhere."),
    Setting("WAKE_SENSITIVITY", "Wake word sensitivity", "waking", "float", 0.5,
            "Higher hears \"hey Jarvis\" more easily but wakes by mistake more often. Lower it if he wakes when nobody called him.",
            minimum=0.05, maximum=0.95),
    Setting("CLAP_WAKE", "Wake by clapping", "waking", "bool", "true", "Clapping wakes him (he then asks for the password as usual)."),
    Setting("CLAP_COUNT", "Number of claps", "waking", "int", 2, "How many claps in a row wake him.", minimum=1, maximum=4),
    Setting("CLAP_SENSITIVITY", "Clap sensitivity", "waking", "float", 1.0,
            "Higher counts softer claps. Raise it if your claps are missed, lower it if typing or talking wakes him.",
            minimum=0.25, maximum=4.0),
    Setting("VOICE_LOCK", "Only answer my voice", "waking", "choice", "auto",
            "Automatic switches it on once you have taught him your voice (python enroll_voice.py). Always means he answers only you. "
            "Off means he answers any voice. The typed box and the buttons always work.",
            choices=(("auto", "Automatic"), ("owner", "Always"), ("off", "Off"))),
    Setting("VOICE_MATCH", "How alike a voice must be", "waking", "float", 0,
            "How alike a voice must be to yours to be accepted (0.2 to 0.9). 0 = the level chosen when you taught him your voice.",
            minimum=0.2, maximum=0.9, zero_allowed=True, advanced=True),
    Setting("FACE_CHECK", "Look at the camera after the password", "waking", "bool", "true",
            "After the password Jarvis glances at the webcam for extra confirmation. It never blocks you: the password is what lets you in."),
    Setting("JARVIS_PASSWORD", "Password (plain text)", "waking", "secret", "",
            "The unlock password written as plain text. It works, but anyone who can read the .env file can read it. Use the "
            "\"Change password\" button instead, which stores only a scrambled form.", hidden=True),
    Setting("JARVIS_PASSWORD_HASH", "Password (scrambled)", "waking", "secret", "",
            "The unlock password stored as a salted hash. Made for you by the setup wizard, the admin panel or python gate.py --set-password.",
            hidden=True),

    # ---- Thinking and chatting
    Setting("CHAT_ENGINE", "Where answers come from", "brain", "choice", "auto",
            "Automatic uses Ollama (the AI model on this PC) when it is running, with a free online key as the backup. "
            "Ollama means only the model on this PC. Cloud means only the online key.",
            choices=(("auto", "Automatic"), ("ollama", "The model on this PC"), ("cloud", "The online key only"))),
    Setting("OLLAMA_MODEL", "Chat model", "brain", "choice", "auto",
            "Automatic picks the biggest installed model that fits in the free memory, up to the size limit below. Or name one, for example "
            "qwen2.5:1.5b (quicker) or llama3.2:3b (writes a little better).",
            choices=(("auto", "Automatic"), ("qwen2.5:1.5b", "qwen2.5:1.5b (quicker)"), ("llama3.2:3b", "llama3.2:3b (better, slower)")),
            strict=False, options_from="ollama_models"),
    Setting("CHAT_AUTO_MAX_MB", "Biggest model Automatic may pick", "brain", "int", 1600,
            "\"Automatic\" never picks a model bigger than this many MB: a 3B model starts speaking 6 to 10 seconds after you ask on a CPU, "
            "a 1.5B one 3 to 5 seconds.", minimum=300, maximum=64000, unit="MB", advanced=True),
    Setting("OLLAMA_KEEP_ALIVE", "How long the model stays loaded", "brain", "text", "10m",
            "How long the model stays in memory after your last question: 10m is ten minutes, 0 unloads it at once.",
            advanced=True, pattern=r"-1|\d+[smh]?", pattern_message="a time such as 10m, 30s, 1h, 0 or -1"),
    Setting("CHAT_MEMORY_TURNS", "How much of the conversation he keeps in mind", "brain", "int", 8,
            "The most question-and-answer pairs kept in mind in one conversation. When the limit is reached the oldest half is forgotten "
            "at once, which keeps answers quick.", minimum=2, maximum=50),
    Setting("CHAT_PRELOAD", "Load the chat model at start-up", "brain", "bool", "false",
            "Answers sooner, but uses 1 to 2 GB of memory from the start. Leave it off on a PC with 8 GB or less."),
    Setting("LANGUAGE_MODEL", "Use his own trained language model", "brain", "bool", "true",
            "Jarvis's own model (made by python training/train_nlu.py) helps him understand loosely worded commands. It is only used when "
            "models/nlu.joblib exists, and never to shut down without asking."),
    Setting("OLLAMA_URL", "Where Ollama listens", "brain", "text", "http://127.0.0.1:11434",
            "Leave it out unless Ollama runs on another computer. (\"localhost\" is rewritten to 127.0.0.1 because on many Windows PCs "
            "\"localhost\" waits two seconds for IPv6 to fail first, on every request.)",
            advanced=True, commented_in_example=True, pattern=r"https?://\S+", pattern_message="an address that starts with http:// or https://"),
    Setting("LLM_API_KEY", "Free online AI key", "brain", "secret", "",
            "Optional. A free key (no card) from console.groq.com or aistudio.google.com. Jarvis works out which service it belongs to. "
            "It is the faster alternative to the model on this PC, or its backup."),
    Setting("LLM_PROVIDER", "Online AI service", "brain", "choice", "auto",
            "Normally leave this on automatic.",
            choices=tuple((v, v) for v in ("auto", "groq", "gemini", "openrouter", "ollama", "custom")), advanced=True),
    Setting("LLM_MODEL", "Online AI model", "brain", "text", "",
            "Blank = a good free model for that service.", advanced=True),
    Setting("LLM_BASE_URL", "Online AI address", "brain", "text", "",
            "Only for the \"custom\" service: any OpenAI-compatible address.", advanced=True, commented_in_example=True),
    Setting("ANTHROPIC_API_KEY", "Claude key", "brain", "secret", "",
            "Optional. With a key Jarvis understands natural speech and uses Claude; without one he uses his built-in free command "
            "understanding. https://console.anthropic.com"),
    Setting("CLAUDE_MODEL", "Claude model", "brain", "text", "claude-opus-5-5",
            "claude-opus-5-5 is the most capable; claude-sonnet-5-5 and claude-haiku-5-5 are cheaper.", advanced=True),
    Setting("CLAUDE_EFFORT", "How hard Claude thinks", "brain", "choice", "low",
            "Low gives the quickest replies; medium or high think more before answering.",
            choices=(("low", "Low (quickest)"), ("medium", "Medium"), ("high", "High")), advanced=True),

    # ---- Accounts and online services
    Setting("EMAIL_ADDRESS", "Your email address", "services", "text", "",
            "For sending email by voice. Gmail, Yahoo, Outlook and iCloud work.",
            pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", pattern_message="an email address looks like name@example.com"),
    Setting("EMAIL_PASSWORD", "Email app password", "services", "secret", "",
            "Use an app password (Gmail, Yahoo and iCloud all offer them), never your real password."),
    Setting("EMAIL_SMTP_HOST", "Mail server", "services", "text", "",
            "Leave blank and Jarvis works it out from the address (Gmail, Yahoo, Outlook, iCloud).", advanced=True),
    Setting("EMAIL_SMTP_PORT", "Mail server port", "services", "int", 587, "Almost always 587.", minimum=1, maximum=65535, advanced=True),
    Setting("WOLFRAM_APP_ID", "Wolfram Alpha key", "services", "secret", "",
            "Optional, for \"ask Wolfram ...\" questions. https://developer.wolframalpha.com"),
    Setting("NASA_API_KEY", "NASA key", "services", "secret", "DEMO_KEY",
            "A free personal key from api.nasa.gov removes the shared DEMO_KEY's hourly limit."),

    # ---- Privacy and records
    Setting("CHAT_WEB_SEARCH", "Look facts up on the internet first", "privacy", "bool", "true",
            "Before the chat model answers a factual question, Jarvis looks it up (Wikipedia; DuckDuckGo for news) so that a small model "
            "does not invent facts. The words of the question are sent there. Off keeps every question on this PC."),
    Setting("LOG_CONVERSATIONS", "Keep a record of conversations", "privacy", "bool", "true",
            "A private record of what you said and what Jarvis answered, one file a day in Logs/conversations. It never leaves this PC. "
            "Read it with python transcript.py. Off records nothing."),
    Setting("CONVERSATION_LOG_DAYS", "Keep the record for", "privacy", "int", 30,
            "Records older than this many days are deleted when a session starts. 0 = keep for ever.",
            minimum=0, maximum=3650, unit="days"),

    # ---- The window
    Setting("GUI_ANIMATIONS", "Moving pictures in the window", "window", "bool", "true",
            "Off shows still pictures, which is lighter on a slow PC."),
)

BY_KEY = {setting.key: setting for setting in SETTINGS}
assert len(BY_KEY) == len(SETTINGS), "a setting is listed twice"
GROUP_BY_ID = {group.id: group for group in GROUPS}
assert all(setting.group in GROUP_BY_ID for setting in SETTINGS)

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def settings_in(group_id, advanced=True, hidden=False):
    """The settings of one group, in order. ``advanced=False`` leaves out the ones for experts; hidden ones (the password) only if asked."""
    return [s for s in SETTINGS if s.group == group_id and (advanced or not s.advanced) and (hidden or not s.hidden)]


def default_of(key):
    return BY_KEY[key].default if key in BY_KEY else ""


def is_true(text):
    return str(text).strip().lower() in _TRUE


def validate(key, raw):
    """Check a value for a setting. Returns Result(ok, value, message): ``value`` is the text to write to .env (cleaned up), and
    ``message`` says in plain words what is wrong when ``ok`` is False. A key this list does not know is accepted as it is."""
    setting = BY_KEY.get(key)
    text = "" if raw is None else str(raw).strip()
    if "\n" in text or "\r" in text or "\x00" in text:
        return Result(False, text, "a setting must be on one line")
    if setting is None:
        return Result(True, text, "")
    kind = setting.kind
    if text == "":
        if kind in ("int", "float") and setting.default != "":
            return Result(False, text, f"a number is needed (the usual value is {setting.default})")
        if kind == "choice" and setting.strict:
            return Result(False, text, "choose one of: " + ", ".join(setting.choice_values()))
        return Result(True, "", "")
    if kind == "bool":
        if text.lower() in _TRUE:
            return Result(True, "true", "")
        if text.lower() in _FALSE:
            return Result(True, "false", "")
        return Result(False, text, "say yes or no (true or false)")
    if kind in ("int", "float"):
        try:
            number = int(text) if kind == "int" else float(text)
        except ValueError:
            return Result(False, text, "a whole number is needed" if kind == "int" else "a number is needed")
        low, high = setting.minimum, setting.maximum
        if setting.zero_allowed and number == 0:
            return Result(True, "0", "")
        if (low is not None and number < low) or (high is not None and number > high):
            return Result(False, text, f"must be between {_plain(low)} and {_plain(high)}" + (f" {setting.unit}" if setting.unit else ""))
        return Result(True, _plain(number), "")
    if kind == "choice" and setting.strict:
        wanted = {value.lower(): value for value in setting.choice_values()}
        if text.lower() in wanted:
            return Result(True, wanted[text.lower()], "")
        return Result(False, text, "choose one of: " + ", ".join(setting.choice_values()))
    if setting.pattern and not re.fullmatch(setting.pattern, text):
        return Result(False, text, setting.pattern_message or "that does not look right")
    if key == "HOME_CURRENCY":
        text = text.upper()
    return Result(True, text, "")


def _plain(number):
    if number is None:
        return "-"
    return str(int(number)) if float(number) == int(number) else str(number)


def effective(env_values):
    """{key: (value in use, True if it is just the default)} for every listed setting, given the values found in .env.
    A number, yes/no or choice that is left empty means "the usual value", as it does in config.py."""
    out = {}
    for setting in SETTINGS:
        raw = env_values.get(setting.key)
        if raw is None or (raw.strip() == "" and setting.kind in ("int", "float", "bool")):
            out[setting.key] = (setting.default, True)
        else:
            out[setting.key] = (raw.strip(), raw.strip() == setting.default)
    return out


def problems(env_values):
    """[(key, what is wrong)] for the settings in .env that Jarvis would not understand (for example STARTUP_GREETING=long)."""
    found = []
    for key, raw in env_values.items():
        setting = BY_KEY.get(key)
        if setting is None or setting.secret or setting.hidden:
            continue
        if str(raw).strip() == "" and not (setting.kind == "choice" and setting.strict):
            continue
        result = validate(key, raw)
        if not result.ok:
            found.append((key, result.message))
    return found


def unknown_keys(env_values):
    """The settings in .env that are not in this list (a key of your own, or one from an older Jarvis). They are kept as they are."""
    return [key for key in env_values if key not in BY_KEY]


# ---------------------------------------------------------------- the files made from this list

BANNER = [
    'Copy this file to ".env" and change what you need. Every setting is optional:',
    "a feature whose key is missing simply tells you so instead of crashing.",
    "(Put comments on their own line - not after a value.)",
    "",
    "This file is written by  python settings_registry.py --write-example  from settings_registry.py: change a setting there, not here.",
    "The easy way to change settings is the admin panel in the Jarvis window, or the setup wizard (Setup-Jarvis.bat).",
]


def _comment(text, indent=""):
    return [f"{indent}# {line}" for line in textwrap.wrap(text, width=118)] or [f"{indent}#"]


def render_env_example():
    lines = [f"# {line}".rstrip() for line in BANNER]
    for group in GROUPS:
        lines += ["", f"# ---- {group.title} " + "-" * max(4, 72 - len(group.title)), *_comment(group.blurb)]
        for setting in SETTINGS:
            if setting.group != group.id:
                continue
            lines += _comment(setting.help)
            if setting.choices and setting.strict:
                lines += _comment("Choices: " + ", ".join(setting.choice_values()))
            lines.append(("# " if setting.commented_in_example else "") + f"{setting.key}={setting.default}")
    return "\n".join(lines) + "\n"


MANUAL_START = "<!-- settings:start (written by python settings_registry.py --write-manual) -->"
MANUAL_END = "<!-- settings:end -->"


def render_manual_table():
    """The settings reference for MANUAL.md: one table per group."""
    out = []
    for group in GROUPS:
        out += ["", f"#### {group.title}", "", group.blurb, "", "| Setting | What it does | Usual value |", "|---|---|---|"]
        for setting in SETTINGS:
            if setting.group != group.id or setting.hidden:
                continue
            what = setting.help.replace("|", "/")
            if setting.choices and setting.strict:
                what += " Choices: " + ", ".join(f"`{v}`" for v in setting.choice_values()) + "."
            if setting.minimum is not None and setting.maximum is not None:
                what += f" From {_plain(setting.minimum)} to {_plain(setting.maximum)}" + (f" {setting.unit}" if setting.unit else "") + "."
            default = f"`{setting.default}`" if setting.default != "" else "(empty)"
            out.append(f"| **{setting.label}**<br>`{setting.key}` | {what} | {default} |")
    return "\n".join(out).strip("\n")


def manual_section():
    return f"{MANUAL_START}\n\n{render_manual_table()}\n\n{MANUAL_END}"


def write_example(path=None):
    path = Path(path) if path else BASE_DIR / ".env.example"
    path.write_text(render_env_example(), encoding="utf-8", newline="\n")
    return path


def write_manual(path=None):
    path = Path(path) if path else BASE_DIR / "MANUAL.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    start, end = text.find(MANUAL_START), text.find(MANUAL_END)
    if start < 0 or end < 0:
        return None
    path.write_text(text[:start] + manual_section() + text[end + len(MANUAL_END):], encoding="utf-8", newline="\n")
    return path


def check():
    """(problems found as sentences). Empty when .env.example and MANUAL.md are up to date."""
    found = []
    example = BASE_DIR / ".env.example"
    if not example.exists() or example.read_text(encoding="utf-8") != render_env_example():
        found.append(".env.example is out of date: run  python settings_registry.py --write-example")
    manual = BASE_DIR / "MANUAL.md"
    if manual.exists():
        text = manual.read_text(encoding="utf-8")
        start, end = text.find(MANUAL_START), text.find(MANUAL_END)
        if start < 0 or end < 0 or text[start:end + len(MANUAL_END)] != manual_section():
            found.append("the settings table in MANUAL.md is out of date: run  python settings_registry.py --write-manual")
    return found


if __name__ == "__main__":
    if "--write-example" in sys.argv:
        print("written:", write_example())
    if "--write-manual" in sys.argv:
        print("written:", write_manual() or "(MANUAL.md has no settings markers yet)")
    if "--check" in sys.argv:
        issues = check()
        print("\n".join(issues) if issues else "The example file and the manual are up to date.")
        sys.exit(1 if issues else 0)
    if len(sys.argv) == 1:
        print(f"{len(SETTINGS)} settings in {len(GROUPS)} groups. Options: --write-example  --write-manual  --check")
