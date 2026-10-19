"""Understands a request about the to-do list and the notes by its parts, not by its exact words.

"can you remove the third task i am done from the to do", "delete the last tas", "remove not number 2" (speech recognition
heard "note" as "not") and "get rid of the dentist item" are all the same kind of request: an ACTION (remove) on a THING (task or
note) with a PLACE in the list (last, third, all) or some WORDS of the item. This module finds those parts, whatever order and
filler words surround them, and LocalBrain does the rest. It also repairs typos and speech-recognition slips in command words
("passowrds", "networds", "holder") for a second look at a sentence no pattern understood.
"""
import difflib
import re
from typing import NamedTuple, Optional

REMOVE = {"remove", "delete", "erase", "clear", "wipe", "cancel", "drop", "scrap", "discard", "kill", "empty", "uncheck",
          "complete", "completed", "finish", "finished"}
ADD = {"add", "added", "adding", "create", "make", "put", "insert", "write", "append", "new"}
TASK = {"task", "tasks", "todo", "todos", "item", "items", "errand", "errands", "chore", "chores", "assignment", "assignments"}
TASK_SLIPS = {"tas", "tusk", "tusks", "test", "tests", "text", "texts", "taste", "tasked"}     # how "task" is often heard
NOTE = {"note", "notes", "memo", "memos"}
NOTE_SLIPS = {"not", "nots", "knot", "knots", "node", "nodes", "nod", "noted"}                 # how "note" is often heard
LAST = {"last", "latest", "newest", "recent", "final"}
EVERY = {"all", "every", "everything", "whole", "entire"}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
            "tenth": 10, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8, "9th": 9, "10th": 10}
CARDINALS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12}
DAYS = {"today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
LEAD = {"can", "you", "could", "would", "will", "please", "kindly", "ok", "okay", "hey", "i", "want", "to", "need", "like", "let",
        "me", "just", "now", "then", "so", "and", "also", "jarvis", "go", "ahead", "you'd", "i'd", "i'll", "should", "yes", "but",
        "well", "actually", "sorry", "again", "quickly"}
FILLER = {"the", "a", "an", "my", "me", "from", "off", "of", "on", "in", "to", "do", "list", "folder", "please", "can", "you",
          "could", "would", "will", "now", "just", "one", "i", "is", "it", "that", "this", "those", "these", "and", "also", "then",
          "for", "as", "with", "at", "so", "ok", "okay", "hey", "number", "no", "num", "another", "next", "more", "out", "away",
          "up", "there", "here", "jarvis", "recent", "only", "kindly", "should", "be", "are", "am", "was", "all", "same", "thing",
          "things", "stuff", "folder", "file", "files", "directory", "called", "named", "titled", "about", "saying", "regarding"}

_PHRASES = [(re.compile(p), r) for p, r in (
    (r"\b(?:cross|tick|scratch|rub|take|wipe|clear|delete|throw)(?: it| them| that| this)? (?:off|out|away)\b|\bcheck off\b", " remove "),
    (r"\bget rid of\b", " remove "),
    (r"\btake (.+?) (?:off|out of)\b", r" remove \1 "),
    (r"\bmark (.*?) (?:as )?(?:done|finished|complete|completed)\b", r" remove \1 "),
)]


class Frame(NamedTuple):
    action: str                       # "remove" or "add"
    nouns: frozenset                  # {"task"}, {"note"}, both, or none were named
    which: str                        # "all", "list", "last", "first", "number", "text", or "" when nothing says which
    number: int                       # 1-based, when which == "number"
    text: str                         # the words of the item, when which == "text" (or what to add)
    day: str                          # "today", "tomorrow", a weekday name, or ""
    count: int = 1                    # "the last TWO tasks": how many, when which is "last" or "first"


def _number(token, before):
    if token.startswith("#") and token[1:].isdigit():
        return int(token[1:])
    if token.isdigit():
        return int(token)
    if token in ORDINALS:
        return ORDINALS[token]
    if token in CARDINALS and before in {"number", "no", "num", "task", "tasks", "item", "items", "note", "notes", "memo"}:
        return CARDINALS[token]
    return 0


def _count(token):
    return int(token) if token.isdigit() and 0 < int(token) <= 50 else CARDINALS.get(token, 0)


PRONOUNS = re.compile(r"^(?:(?:and|also|then|next|add|ok|okay|um|uh|at|so|that|to do|todo)\s+)*"
                      r"(?:(?:i will|i'll|i am going to|i'm going to|i have to|i need to|i must|i should|i want to|i would like to|"
                      r"we will|we need to|let me|remind me to|to)\s+)?")


def tidy_task(text):
    """A task as it was said, without the speech around it: "at call ali" / "i will call ali" -> "call ali"."""
    cleaned = text.strip()
    for _ in range(3):
        cleaned = PRONOUNS.sub("", cleaned, count=1).strip()
    return cleaned or text.strip()


def parse(text) -> Optional[Frame]:
    """The parts of a request to add or remove something from the to-do list or the notes; None if it is not that kind of request."""
    spoken = text.lower()
    for pattern, replacement in _PHRASES:
        spoken = pattern.sub(replacement, spoken)
    words = re.findall(r"#\d+|[a-z0-9]+(?:'[a-z]+)?", spoken)
    if words and words[0] == "at":
        words[0] = "add"                                     # "add" is very often heard as "at"
    verb_at = next((i for i, w in enumerate(words) if w in REMOVE or w in ADD), None)
    if verb_at is None or verb_at > 7 or any(w not in LEAD for w in words[:verb_at]):
        return None                                          # it has to be said as an instruction, not mentioned in passing
    action = "remove" if words[verb_at] in REMOVE else "add"
    rest = words[verb_at + 1:]
    nouns, number, which, day, count, used = set(), 0, "", "", 1, set()
    weak = set()
    for i, w in enumerate(rest):
        before = rest[i - 1] if i else ""
        after = rest[i + 1] if i + 1 < len(rest) else ""
        if w in TASK or (w == "do" and before == "to"):
            nouns.add("task"); used.add(i)
        elif w in NOTE:
            nouns.add("note"); used.add(i)
        elif w in TASK_SLIPS:
            weak.add("task"); used.add(i)
        elif w in NOTE_SLIPS:
            weak.add("note"); used.add(i)
        elif w == "list" and action == "add":
            weak.add("task")
        if w in DAYS:
            day = w; used.add(i)
        elif w in EVERY:
            which = "all"; used.add(i)
        elif (w in LAST or w in ("first", "oldest")) and which != "all":
            which = "last" if w in LAST else "first"; used.add(i)
            if _count(after) and action == "remove":
                count = _count(after); used.add(i + 1)       # "the last two tasks"
            elif w == "first":
                number = 1
        elif i not in used and _number(w, before) and which not in ("all",):
            number, which = _number(w, before), "number"; used.add(i)
    if not nouns and which in ("number", "last", "first", "all"):
        nouns = weak                                         # "remove the last test": "test" can only be "task" here
    elif not nouns and action == "add":
        nouns = weak
    if not nouns and not which and action == "add":
        return None
    skip = FILLER | {"another", "new", "next", "add", "added", "adding"}
    if action == "add":                                      # what to add: everything between the first and last meaningful word
        meaningful = [i for i, w in enumerate(rest) if i not in used and w not in skip and w not in TASK_SLIPS and w not in NOTE_SLIPS]
        item = tidy_task(" ".join(rest[meaningful[0]:meaningful[-1] + 1])) if meaningful else ""
        if item and not (nouns & {"task"}) and "note" not in nouns:
            item = ""
    else:
        left = [w for i, w in enumerate(rest) if i not in used and w not in FILLER and w not in REMOVE and w not in ADD
                and w not in TASK_SLIPS and w not in NOTE_SLIPS]
        item = " ".join(left)
    if not which and item and action == "remove":
        which = "text"
    elif not which and action == "remove" and nouns:
        collection = {"tasks", "notes", "todos", "items", "memos", "errands", "chores", "list"} & set(rest) \
            or "todo" in rest or ("to" in rest and "do" in rest)
        which = ("list" if "task" in nouns else "all") if collection else "last"      # "clear my to do list" is that day's list
    if action == "remove" and not nouns and not which:
        return None
    if action == "add":
        which = "text" if item else ""
    return Frame(action, frozenset(nouns), which, number, item if which == "text" else "", day, count)


# ---------------------------------------------------------------- number words

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
MONEY = r"(?=(?:us |american |australian |canadian )?(?:dollars?|pounds?|euros?|rupees?|dirhams?|riyals?|yen|yuan|lira)\b)"


def _read_number(words, start):
    """(value, index after it) for the number words at ``start`` ("two hundred and fifty"), or (None, start)."""
    total = current = 0
    seen, j = False, start
    while j < len(words):
        w = words[j]
        if w in UNITS:
            current += UNITS[w]
        elif w in TENS:
            current += TENS[w]
        elif w == "hundred" and seen:
            current = max(current, 1) * 100
        elif w == "thousand" and seen:
            total, current = total + max(current, 1) * 1000, 0
        elif w == "and" and seen and j + 1 < len(words) and (words[j + 1] in UNITS or words[j + 1] in TENS):
            pass
        else:
            break
        seen, j = True, j + 1
    return (total + current, j) if seen else (None, start)


def numerals(text):
    """``text`` with number words as digits: "fifteen percent of two hundred" -> "15 percent of 200", "a dollar in rupees" ->
    "1 dollar in rupees"."""
    text = re.sub(r"\b(?:a|an)\b " + MONEY, "1 ", text)
    words, out, i = text.split(), [], 0
    lowered = [w.lower().strip(",.?!") for w in words]
    while i < len(words):
        value, end = _read_number(lowered, i) if lowered[i] in UNITS or lowered[i] in TENS else (None, i)
        if value is not None:
            out.append(str(value))
            i = end
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


# ---------------------------------------------------------------- repairing typos and slips in command words

SLIPS = {"holder": "folder", "foldr": "folder", "folda": "folder", "passowrd": "password", "passowrds": "passwords",
         "pasword": "password", "paswords": "passwords", "passward": "password", "passwards": "passwords", "networds": "networks",
         "netwrok": "network", "netwroks": "networks", "wifi": "wifi", "screnshot": "screenshot", "scrnshot": "screenshot",
         "calender": "calendar", "calandar": "calendar", "calcualtor": "calculator", "calclator": "calculator",
         "wether": "weather", "wheather": "weather", "tomorow": "tomorrow", "tommorow": "tomorrow", "remider": "reminder",
         "remind": "remind", "volumn": "volume", "bateri": "battery", "batery": "battery", "notepad": "notepad"}
WORDS = {"password", "passwords", "network", "networks", "folder", "folders", "screenshot", "screenshots", "calculator",
         "calendar", "weather", "battery", "volume", "notes", "reminder", "reminders", "remind", "tasks", "downloads",
         "documents", "pictures", "desktop", "music", "videos", "youtube", "google", "translate", "generate", "remove", "delete",
         "clear", "erase", "joke", "advice", "bored", "restart", "shutdown", "sleep", "lock", "mute", "unmute", "pause", "resume",
         "temperature", "forecast", "location", "internet", "connected", "available", "memory", "storage", "processor", "status",
         "tomorrow", "schedule", "timetable", "currency", "converter", "wikipedia", "email", "message", "download", "weather"}


def repair(text, extra=()):
    """``text`` with the command words in it put right ("show all available wifi networds" -> "... networks"), or None when
    nothing needed putting right. Only words that look like a mistake for a command word are touched; the caller should use
    the result only if a command understands it."""
    vocabulary = WORDS                                    # only the words commands are built from: never a guess at ordinary words
    changed = []
    for word in text.split():
        bare = re.sub(r"[^a-z]", "", word.lower())
        fixed = SLIPS.get(bare)
        if fixed is None and len(bare) >= 6 and bare not in vocabulary:
            close = difflib.get_close_matches(bare, vocabulary, n=1, cutoff=0.84)
            fixed = close[0] if close else None
        changed.append(fixed if fixed and fixed != bare else word)
    result = " ".join(changed)
    return result if result != text else None
