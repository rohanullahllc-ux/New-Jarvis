"""Productivity tools: notes, to-do list, reminders, time table, books, translation and quick helpers."""
import datetime
import difflib
import json
import os
import re
import secrets
import string
import threading
from pathlib import Path
from typing import Literal

import requests
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import config
from . import _common
from ._common import KNOWN_FOLDERS, copy_to_clipboard, folder, known_folder, safe_filename


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


def _note_full(path):
    """A note as it should be read out: untitled notes (named by the time they were taken) are just what they say."""
    body = _note_body(path)[:300]
    return body if re.fullmatch(r"note-\d{8}-\d{6}", path.stem) else f"{path.stem}: {body}"


@beta_tool
def open_notes(which: Literal["latest", "folder"] = "latest") -> str:
    """Open the newest note in Notepad, or the folder that holds all the notes.

    Args:
        which: "latest" for the most recent note, "folder" for the Notes folder.
    """
    notes_dir = _common.DB / "Notes"
    notes = sorted(notes_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if notes_dir.exists() else []
    if not notes:
        raise ToolError("There are no saved notes yet.")
    os.startfile(notes_dir if which == "folder" else notes[0])
    return "Opened the notes folder" if which == "folder" else f"Opened your latest note: {_note_body(notes[0])[:200]}"


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
        if len(notes) <= 3:                                     # a short list is read in full, not shortened to "and so on"
            return "Your notes: " + "; ".join(f"{i}. {_note_full(p)}" for i, p in enumerate(notes, 1))
        return "Recent notes: " + ", ".join(f"{i}. {_note_label(p)}" for i, p in enumerate(notes[:10], 1))
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


def _all_task_files():
    folder_ = _common.DB / "Tasks"
    return sorted(folder_.glob("*-Task.txt")) if folder_.is_dir() else []


def count_tasks(day=None):
    """How many to-do items there are on one day, or on every day (``day`` None)."""
    files = [_task_file(day)] if day else _all_task_files()
    return sum(len([line for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]) for f in files if f.exists())


def _find_task(text, day, tasks, search_other_days):
    """(day, that day's tasks, item number) for the one item whose words match ``text``."""
    wanted = " ".join(text.lower().split())

    def hits(items):
        exact = [i for i, t in enumerate(items, 1) if wanted in t.lower()]
        if exact:
            return exact
        size = len(wanted.split())

        def close(task):                                   # the closest stretch of the task's words, so one typo still matches
            words = task.lower().split()
            stretches = [" ".join(words[k:k + size]) for k in range(max(1, len(words) - size + 1))]
            return max(difflib.SequenceMatcher(None, wanted, stretch).ratio() for stretch in stretches) >= 0.8

        return [i for i, t in enumerate(items, 1) if close(t)]

    found = hits(tasks)
    if len(found) > 1:
        raise ToolError("Several items match: " + "; ".join(f"{i}. {tasks[i - 1]}" for i in found) + ". Which number do you mean?")
    if found:
        return day, tasks, found[0]
    if search_other_days:                                  # no day was named: the item may be on another day's list
        matches = []
        for path in _all_task_files():
            other = datetime.date.fromisoformat(path.name[:10])
            items = _read_tasks(other)
            matches += [(other, items, i) for i in hits(items)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ToolError("That matches items on several days: " + "; ".join(f"{d:%A %d %B}: {items[i - 1]}" for d, items, i in matches)
                            + ". Tell me the day.")
    raise ToolError(f"I can't find an item like '{text}' on the to-do list for {day:%A %d %B}.")


@beta_tool
def remove_task(number: int = 0, date: str = "", text: str = "") -> str:
    """Remove one finished or unwanted item from the to-do list, by its number (as read out by list_tasks) or by some of its words.

    Args:
        number: The item's number, as given by list_tasks. Leave out (0) when giving words instead.
        date: Day as YYYY-MM-DD, or empty for today (when only words are given, other days are searched too).
        text: Some words of the item, when its number is not known.
    """
    day = _parse_day(date)
    tasks = _read_tasks(day)
    if not number and text.strip():
        day, tasks, number = _find_task(text, day, tasks, search_other_days=not date)
    elif not number:
        raise ToolError("Tell me which item to remove: its number, or some of its words.")
    if not 1 <= number <= len(tasks):
        raise ToolError(f"There is no item {number}; the list has {len(tasks)} items.")
    removed = tasks.pop(number - 1)
    path = _task_file(day)
    if tasks:
        path.write_text("".join(t + "\n" for t in tasks), encoding="utf-8")
    else:
        path.unlink()
    return f"Removed: {removed}"


@beta_tool
def clear_tasks(date: str = "", every_day: bool = False, confirmed: bool = False) -> str:
    """Delete every item from the to-do list of one day, or of every day. Permanent: tell the user how many items will go, and call this with confirmed=true only after they clearly agree.

    Args:
        date: Day as YYYY-MM-DD, or empty for today. Ignored when every_day is true.
        every_day: True to clear the lists of all days.
        confirmed: True only after the user has agreed to this deletion.
    """
    days = [None] if every_day else [_parse_day(date)]
    count = count_tasks(days[0])
    if not count:
        return "There were no to-do items to clear."
    if not confirmed:
        raise ToolError(f"This would permanently delete {count} to-do item{'' if count == 1 else 's'}. Ask the user first, "
                        "then call again with confirmed set to true.")
    for path in (_all_task_files() if every_day else [_task_file(days[0])]):
        if path.exists():
            path.unlink()
    return f"Cleared {count} to-do item{'' if count == 1 else 's'}."


def pick_notes(which="all", title=""):
    """The note files a request means: every note, the newest one, or the one whose name or words contain ``title``."""
    folder_ = _common.DB / "Notes"
    notes = sorted(folder_.glob("*.txt"), key=lambda p: p.stat().st_mtime) if folder_.is_dir() else []
    if title.strip():
        wanted = title.strip().lower()
        matches = [n for n in notes if wanted in n.stem.lower() or wanted in n.read_text(encoding="utf-8", errors="replace").lower()]
        if not matches:
            raise ToolError(f"I can't find a note about '{title.strip()}'.")
        if len(matches) > 1:
            raise ToolError("Several notes match: " + ", ".join(n.stem for n in matches[:6]) + ". Tell me more of the name.")
        return matches
    return notes[-1:] if which == "latest" else notes


@beta_tool
def delete_notes(which: Literal["all", "latest"] = "all", title: str = "", confirmed: bool = False) -> str:
    """Permanently delete notes: all of them, the newest one, or the one whose name or words contain a title. Tell the user how many will go, and call this with confirmed=true only after they clearly agree.

    Args:
        which: all for every note, or latest for the newest one. Ignored when title is given.
        title: Some of the note's name or words, to delete just that note.
        confirmed: True only after the user has agreed to this deletion.
    """
    chosen = pick_notes(which, title)
    if not chosen:
        return "There are no saved notes to delete."
    if not confirmed:
        raise ToolError(f"This would permanently delete {len(chosen)} note{'' if len(chosen) == 1 else 's'}. Ask the user first, "
                        "then call again with confirmed set to true.")
    for note in chosen:
        note.unlink()
    return f"Deleted {len(chosen)} note{'' if len(chosen) == 1 else 's'}."


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


LANGUAGE_NAMES = {}
for _name, _code in LANGUAGES.items():
    LANGUAGE_NAMES.setdefault(_code, _name.title())


def _google_free_address(text, code):
    """Google Translate through the free address browser extensions use. It is quicker, and refused less often, than the web
    page the deep_translator package reads (which answers "too many requests" to this PC)."""
    response = requests.get("https://translate.googleapis.com/translate_a/single", timeout=12, headers={"User-Agent": "Mozilla/5.0"},
                            params={"client": "gtx", "sl": "auto", "tl": code, "dt": "t", "q": text})
    response.raise_for_status()
    return "".join(part[0] for part in response.json()[0] if part and part[0]).strip()


MODEL_TRANSLATES = {"en", "fr", "es", "de", "it", "pt", "ru", "tr", "ar", "zh-CN", "ja", "ko"}   # the small model gets these right


def _by_the_local_model(text, code):
    """The AI model on this PC as a translator: slower than Google but never refused. It is only trusted for the languages it
    knows well, in and out: its Urdu, Hindi, Pashto, Punjabi and Persian are nonsense, and nonsense is worse than an honest
    "I can't". Anything that looks like chatter instead of a translation is thrown away."""
    from JarvisAdvancedBot import ChatBrain
    if code not in MODEL_TRANSLATES or _guess_source(text) != "en-GB":
        return ""
    language = LANGUAGE_NAMES.get(code, code)
    answer = ChatBrain.complete(f"You are a translator. Translate the user's text into {language}. Reply with the translation only: "
                                "no notes, no quotes, no explanation.", text)
    if not answer:
        return ""
    answer = answer.strip("\"'“”«» ")
    return answer if len(answer) <= 4 * len(text) + 40 else ""


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
    # In order of quality. Google's free services sometimes refuse a PC for a while ("too many requests"); then the model on this
    # PC translates (the languages it knows); MyMemory, a crowd-sourced memory that has answered "how are you" with "I'm called
    # Jay", is the last resort.
    ways = (lambda: _google_free_address(text, code),
            lambda: GoogleTranslator(source="auto", target=code).translate(text),
            lambda: _by_the_local_model(text, code),
            lambda: MyMemoryTranslator(source=_guess_source(text), target=MYMEMORY_CODES.get(code, code)).translate(text))
    for way in ways:
        try:
            result = way()
        except Exception:                                           # noqa: BLE001 - each service fails in its own way
            continue
        if result and result.strip():
            return result.strip()
    raise ToolError("The translation services aren't answering right now.")


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
    base = known_folder(place) if place.lower() in KNOWN_FOLDERS else Path(place).expanduser()
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


TOOLS = [take_note, read_notes, open_notes, add_task, list_tasks, remove_task, clear_tasks, delete_notes, set_reminder, get_timetable_block,
         add_timetable_block, read_book_page, translate_text, make_acronym, create_folder, ask_wolfram_alpha,
         generate_password]
