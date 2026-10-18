"""Productivity tools: notes, to-do list, reminders, time table, books, translation and quick helpers."""
import datetime
import difflib
import json
import re
import secrets
import string
import threading
from pathlib import Path

import requests
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import config
from . import _common
from ._common import copy_to_clipboard, folder, safe_filename

KNOWN_FOLDERS = ("desktop", "documents", "downloads", "pictures", "music", "videos")


# ---------------------------------------------------------------- notes

@beta_tool
def take_note(text: str, title: str = "") -> str:
    """Save a note as a text file in the Notes folder.

    Args:
        text: What the note says.
        title: Short title, used as the file name.
    """
    target = folder("Notes")
    now = datetime.datetime.now()
    name = safe_filename(title) or now.strftime("note-%Y%m%d-%H%M%S")
    (target / f"{name}.txt").write_text(f"{now:%A, %d %B %Y, %I:%M %p}\n\n{text}\n", encoding="utf-8")
    return f"Saved note '{name}'" if title.strip() else "Saved your note"


def _note_body(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    return raw.split("\n\n", 1)[1].strip() if "\n\n" in raw else raw.strip()


def _note_label(path):
    """A note's title, or for untitled notes (named by the time they were taken) the start of what it says."""
    if re.fullmatch(r"note-\d{8}-\d{6}", path.stem):
        words = _note_body(path).split()
        return " ".join(words[:6]) + (" and so on" if len(words) > 6 else "") or path.stem
    return path.stem


@beta_tool
def read_notes(title: str = "", latest: bool = False) -> str:
    """List the saved notes, or read one of them.

    Args:
        title: Part of the note's title or of what it says, or empty to list the most recent notes.
        latest: True to read the most recently saved note in full.
    """
    notes_dir = _common.DB / "Notes"
    notes = sorted(notes_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if notes_dir.exists() else []
    if not notes:
        return "There are no saved notes."
    if latest:
        return f"Your latest note: {_note_body(notes[0])[:2000]}"
    if not title:
        return "Recent notes: " + ", ".join(_note_label(p) for p in notes[:10])
    wanted = title.lower()
    match = next((p for p in notes if wanted in p.stem.lower() or wanted in _note_body(p).lower()), None)
    if match is None:
        raise ToolError(f"No note matching {title}. Notes: " + ", ".join(_note_label(p) for p in notes[:10]))
    return f"{_note_label(match)}: {match.read_text(encoding='utf-8', errors='replace')[:2000].strip()}"


# ---------------------------------------------------------------- to-do list

def _task_file(day):
    return _common.DB / "Tasks" / f"{day.isoformat()}-Task.txt"


def _parse_day(date):
    try:
        return datetime.date.fromisoformat(date) if date else datetime.date.today()
    except ValueError:
        raise ToolError("Dates must look like YYYY-MM-DD.") from None


def _read_tasks(day):
    path = _task_file(day)
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


@beta_tool
def add_task(task: str, date: str = "") -> str:
    """Add an item to the to-do list.

    Args:
        task: What needs doing.
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    path = _task_file(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(task.strip() + "\n")
    return f"Added to the list for {day:%A %d %B}: {task}"


@beta_tool
def list_tasks(date: str = "") -> str:
    """Read the to-do list.

    Args:
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    tasks = _read_tasks(day)
    if not tasks:
        return f"The to-do list for {day:%A %d %B} is empty."
    return f"To-do list for {day:%A %d %B}: " + "; ".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))


@beta_tool
def remove_task(number: int, date: str = "") -> str:
    """Remove a finished item from the to-do list.

    Args:
        number: The item's number, as given by list_tasks.
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    tasks = _read_tasks(day)
    if not 1 <= number <= len(tasks):
        raise ToolError(f"There is no item {number}; the list has {len(tasks)} items.")
    removed = tasks.pop(number - 1)
    _task_file(day).write_text("".join(t + "\n" for t in tasks), encoding="utf-8")
    return f"Removed: {removed}"


# ---------------------------------------------------------------- reminders

def _ring(message):
    """A reminder is due: show a notification, play the alarm, then say what it is for."""
    try:
        from plyer import notification
        notification.notify(title="Jarvis reminder", message=message, timeout=15)
    except Exception:
        pass
    try:
        from sound_player import playsound
        playsound(config.BASE_DIR / "DataBase" / "Sounds" / "1.mp3")
    except Exception:
        pass
    from speech import Speak                                  # also prints it, and shows it in the window's conversation
    Speak(message if message.lower().startswith(("your ", "wake up", "reminder")) else f"Reminder: {message}")


@beta_tool
def set_reminder(message: str, minutes_from_now: float = 0, at_time: str = "") -> str:
    """Set a timer, alarm or reminder that plays a sound and shows a notification. Give minutes_from_now or at_time.

    Args:
        message: What the reminder is for.
        minutes_from_now: Minutes until it goes off, e.g. 10 for a ten-minute timer.
        at_time: Clock time in 24-hour HH:MM, e.g. "07:30" or "18:45". If that time has passed today, it goes off tomorrow.
    """
    now = datetime.datetime.now()
    if at_time:
        try:
            hour, minute = map(int, at_time.split(":"))
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            raise ToolError("Times must look like HH:MM in 24-hour format.") from None
        if when <= now:
            when += datetime.timedelta(days=1)
    elif minutes_from_now > 0:
        when = now + datetime.timedelta(minutes=minutes_from_now)
    else:
        raise ToolError("Say how many minutes from now, or what time.")
    timer = threading.Timer((when - now).total_seconds(), _ring, args=[message])
    timer.daemon = True
    timer.start()
    days_ahead = (when.date() - now.date()).days
    day = "today" if days_ahead == 0 else "tomorrow" if days_ahead == 1 else f"on {when:%A}"
    clock = when.strftime("%I:%M %p").lstrip("0")
    return f"Reminder set for {clock} {day}: {message}. It only goes off while Jarvis is running."


# ---------------------------------------------------------------- time table

TIMETABLE_HELP = ("Add your own routine as blocks with 24-hour HH:MM times, for example "
                  '{"start": "06:00", "end": "09:00", "activity": "Study"}. Blocks that cross midnight '
                  "(22:00 to 06:00) work too. You can also just say: add study from 6 to 9 in the morning to my time table.")


def _timetable_path():
    return _common.DB / "TimeTable" / "timetable.json"


def _load_timetable():
    path = _timetable_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"_help": TIMETABLE_HELP, "blocks": []}, indent=2), encoding="utf-8")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("blocks", [])
        return data
    except (ValueError, AttributeError):
        raise ToolError("The time table file isn't valid JSON. Open DataBase/TimeTable/timetable.json and fix it.") from None


def _to_minutes(text):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text))
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ToolError(f"{text!r} is not a time. Use 24-hour HH:MM, like 06:30 or 18:45.")
    return int(match.group(1)) * 60 + int(match.group(2))


def _clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@beta_tool
def get_timetable_block(at_time: str = "") -> str:
    """Say what is scheduled in the user's own time table right now (or at a given time), and what comes next.

    Args:
        at_time: Time as 24-hour HH:MM, or empty for right now.
    """
    blocks = _load_timetable()["blocks"]
    if not blocks:
        return "Your time table is empty. " + TIMETABLE_HELP
    now = _to_minutes(at_time) if at_time else datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
    parsed = sorted((_to_minutes(b["start"]), _to_minutes(b["end"]), b["activity"]) for b in blocks)
    current = next((i for i, (s, e, _) in enumerate(parsed) if (s <= now < e) or (s > e and (now >= s or now < e))), None)
    upcoming = min((b for i, b in enumerate(parsed) if i != current), key=lambda b: (b[0] - now) % 1440, default=None)
    parts = []
    if current is not None:
        parts.append(f"Right now: {parsed[current][2]} until {_clock(parsed[current][1])}.")
    else:
        parts.append("Nothing is scheduled right now.")
    if upcoming:
        parts.append(f"Next: {upcoming[2]} at {_clock(upcoming[0])}.")
    return " ".join(parts)


@beta_tool
def add_timetable_block(start: str, end: str, activity: str) -> str:
    """Add a block to the user's time table.

    Args:
        start: Start time as 24-hour HH:MM, e.g. "06:00".
        end: End time as 24-hour HH:MM, e.g. "09:00". It may be earlier than start for blocks that cross midnight.
        activity: What to do in that block, e.g. "Study".
    """
    activity = activity.strip()
    if not activity:
        raise ToolError("Tell me what the block is for.")
    start_minutes, end_minutes = _to_minutes(start), _to_minutes(end)
    if start_minutes == end_minutes:
        raise ToolError("A block needs different start and end times.")
    data = _load_timetable()
    data["blocks"].append({"start": _clock(start_minutes), "end": _clock(end_minutes), "activity": activity})
    data["blocks"].sort(key=lambda b: _to_minutes(b["start"]))
    _timetable_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f"Added {activity} from {_clock(start_minutes)} to {_clock(end_minutes)} to your time table."


# ---------------------------------------------------------------- books

@beta_tool
def read_book_page(title: str = "", page: int = 1) -> str:
    """Read one page of a PDF book from the Books folder.

    Args:
        title: Part of the book's name; may be empty if there is only one book.
        page: Page number, starting at 1.
    """
    books = sorted(folder("Books").glob("*.pdf"))
    if not books:
        raise ToolError("There are no books yet. Put PDF files in the DataBase/Books folder.")
    names = {p.stem.lower(): p for p in books}
    if title:
        key = next((n for n in names if title.lower() in n), None) or \
              next(iter(difflib.get_close_matches(title.lower(), names, n=1, cutoff=0.4)), None)
        if key is None:
            raise ToolError("I couldn't find that book. Available: " + ", ".join(p.stem for p in books))
        book = names[key]
    elif len(books) == 1:
        book = books[0]
    else:
        return "Which book? Available: " + ", ".join(p.stem for p in books)
    try:
        from pypdf import PdfReader
        reader = PdfReader(book)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ToolError(f"{book.stem} is password protected.")
        total = len(reader.pages)
        if not 1 <= page <= total:
            raise ToolError(f"{book.stem} has {total} pages. Pick a page from 1 to {total}.")
        text = reader.pages[page - 1].extract_text() or ""
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"I couldn't open {book.stem} ({type(e).__name__}).") from None
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ToolError(f"Page {page} of {book.stem} has no readable text; it may be a scanned picture.")
    return f"{book.stem}, page {page} of {total}: {text[:1500]}"


# ---------------------------------------------------------------- language and quick helpers

LANGUAGES = {
    "urdu": "ur", "english": "en", "arabic": "ar", "hindi": "hi", "pashto": "ps", "punjabi": "pa", "persian": "fa",
    "farsi": "fa", "french": "fr", "spanish": "es", "german": "de", "chinese": "zh-CN", "turkish": "tr",
    "japanese": "ja", "korean": "ko", "russian": "ru", "italian": "it", "portuguese": "pt",
}
MYMEMORY_CODES = {
    "ur": "ur-PK", "en": "en-GB", "ar": "ar-SA", "hi": "hi-IN", "ps": "ps-AF", "pa": "pa-IN", "fa": "fa-IR",
    "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "tr": "tr-TR", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU",
    "it": "it-IT", "pt": "pt-PT", "zh-CN": "zh-CN",
}


def _language_code(language):
    text = language.strip().lower()
    if text in LANGUAGES:
        return LANGUAGES[text]
    for code in LANGUAGES.values():
        if text == code.lower():
            return code
    raise ToolError(f"I don't know the language {language}. I can translate into: " + ", ".join(sorted(LANGUAGES)))


def _guess_source(text):
    if re.search(r"[؀-ۿ]", text):
        return "ur-PK"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi-IN"
    return "en-GB"


@beta_tool
def translate_text(text: str, target_language: str) -> str:
    """Translate text into another language. The language of the text is detected automatically.

    Args:
        text: The words to translate.
        target_language: Language to translate into, e.g. "Urdu", "French" or "es".
    """
    code = _language_code(target_language)
    from deep_translator import GoogleTranslator, MyMemoryTranslator
    try:
        result = GoogleTranslator(source="auto", target=code).translate(text)
    except Exception:           # Google's free endpoint sometimes rate-limits; MyMemory is a free backup
        try:
            result = MyMemoryTranslator(source=_guess_source(text), target=MYMEMORY_CODES.get(code, code)).translate(text)
        except Exception:
            raise ToolError("The translation services aren't answering right now.") from None
    if not result:
        raise ToolError("I couldn't translate that.")
    return result


STOP_WORDS = {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "at", "by", "with"}


@beta_tool
def make_acronym(phrase: str) -> str:
    """Turn a phrase into an acronym from the first letters of its important words.

    Args:
        phrase: The phrase, e.g. "portable network graphics".
    """
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", phrase)
    if not words:
        raise ToolError("Give me a phrase to turn into an acronym.")
    important = [w for w in words if w.lower() not in STOP_WORDS] or words
    acronym = "".join(w[0].upper() for w in important)
    return f"{acronym} ({', '.join(acronym)}) stands for {phrase.strip()}."


@beta_tool
def create_folder(name: str, location: str = "documents") -> str:
    """Create a new folder.

    Args:
        name: Name of the new folder.
        location: Where to create it: desktop, documents, downloads, pictures, music, videos, or a full path.
    """
    name = name.strip()
    if not re.fullmatch(r'[^\\/:*?"<>|]{1,80}', name) or name in {".", ".."}:
        raise ToolError("A folder name can't contain \\ / : * ? \" < > |")
    place = location.strip().strip('"')
    base = Path.home() / place.title() if place.lower() in KNOWN_FOLDERS else Path(place).expanduser()
    if not base.is_dir():
        raise ToolError(f"I can't find the place {location} to put it in.")
    target = base / name
    try:
        target.mkdir()
    except FileExistsError:
        raise ToolError(f"There is already a folder called {name} in {base}.") from None
    except OSError as e:
        raise ToolError(f"Windows wouldn't create that folder ({e.strerror}).") from None
    return f"Created the folder {target}"


@beta_tool
def ask_wolfram_alpha(question: str) -> str:
    """Ask Wolfram Alpha a factual or mathematical question, such as unit conversions, calculus or scientific data.

    Args:
        question: The question in plain English, e.g. "integral of x squared" or "distance from Earth to Mars".
    """
    if not config.WOLFRAM_APP_ID:
        raise ToolError("Wolfram Alpha isn't set up. Add WOLFRAM_APP_ID to the .env file (it is free at developer.wolframalpha.com).")
    try:
        response = requests.get("https://api.wolframalpha.com/v1/result", timeout=15,
                                params={"appid": config.WOLFRAM_APP_ID, "i": question})
    except requests.RequestException:
        raise ToolError("I couldn't reach Wolfram Alpha.") from None     # never echo the URL: it contains the App ID
    if response.status_code == 501:
        raise ToolError("Wolfram Alpha couldn't answer that question.")
    if response.status_code in (400, 401, 403):
        raise ToolError("Wolfram Alpha rejected my App ID. Check WOLFRAM_APP_ID in the .env file.")
    if not response.ok:
        raise ToolError(f"Wolfram Alpha had a problem (error {response.status_code}).")
    return response.text.strip()


@beta_tool
def generate_password(length: int = 16) -> str:
    """Generate a strong random password and copy it to the clipboard. The password is never shown to you.

    Args:
        length: Number of characters, from 8 to 64.
    """
    length = max(8, min(length, 64))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    copy_to_clipboard("".join(secrets.choice(alphabet) for _ in range(length)))
    return f"Generated a {length}-character password and copied it to the clipboard."


TOOLS = [take_note, read_notes, add_task, list_tasks, remove_task, set_reminder, get_timetable_block,
         add_timetable_block, read_book_page, translate_text, make_acronym, create_folder, ask_wolfram_alpha,
         generate_password]
