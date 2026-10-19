"""Jarvis's free brain: understands everyday commands without any AI service.

What you say is matched against the patterns below, in order. The first handler that understands it
runs one or more of the tools in JarvisAdvancedBot/tools and returns the sentence for Jarvis to speak.
LocalReply returns None when nothing matches, so the session can tell you it didn't understand.

ORDER MATTERS. A specific command must come before the broader one it would otherwise be mistaken
for ("open downloads" before "open <app>", "temperature of Mars" before "temperature" = weather), and
the Wikipedia catch-all stays last.
"""
import datetime
import difflib
import random
import re
import threading
import traceback

import psutil
from anthropic.lib.tools import ToolError

import calc
import config
import units
from config import DEFAULT_CITY, HOME_CURRENCY
from JarvisAdvancedBot import ChatBrain, FreeBrain, NLU
from JarvisAdvancedBot import tools as T
from JarvisAdvancedBot.tools._common import read_clipboard
from JarvisAdvancedBot.tools.productivity import LANGUAGES

INTENTS = []
_context = threading.local()


def intent(*patterns):
    """Register the decorated handler for commands matching any of the patterns.

    A handler gets the regex match and an ask(question) function for follow-up
    questions. It returns the reply, or None to let later intents try.
    """
    def register(handler):
        INTENTS.extend((re.compile(p), handler) for p in patterns)
        return handler
    return register


def normalize(text):
    text = text.lower().strip()
    text = re.sub(r"\bjarvis\b[,]?", " ", text)
    text = re.sub(r"[?!.]+$", "", text)
    text = re.sub(r"^(?:(?:hey|ok|okay)\s+)?assistant\b[,]?\s+(?=\w)", "", text.strip())             # "Jarvis" is often heard as "assistant"
    text = re.sub(r"^(?:(?:hey|ok|okay|um|uh|er|hmm|sorry|actually|i mean|no i mean|i told you|i said|as i said)[,.]?\s+)+(?=\w)",
                  "", text.strip())
    text = re.sub(r"^(?:(?:can|could|would|will) you\s+)?(?:please\s+)?", "", text.strip())
    text = re.sub(r"\s+please$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def original():
    """The command exactly as it was typed or heard (patterns see a lower-cased copy)."""
    return getattr(_context, "query", "")


def _as_typed(fragment):
    """``fragment`` (taken from the lower-cased command) with the capital letters it had originally."""
    found = re.search(re.escape(fragment), original(), flags=re.I) if fragment else None
    return found.group(0) if found else fragment


def _show(text):
    """Show text in the window without speaking it (the voice can't read Urdu, and a whole page is too long to listen to)."""
    from speech import Show
    Show(text)


def _heads_up(text):
    """Say something before a slow step, so the silence isn't mistaken for a crash."""
    from speech import Speak
    Speak(text)


YES = re.compile(r"\b(?:yes|yeah|yep|yup|sure|ok|okay|confirm|confirmed|go ahead|do it|send it|proceed|affirmative)\b")
NO = re.compile(r"\b(?:no|nope|nah|don't|do not|cancel|stop|never|negative|abort)\b")


def _confirmed(ask, question):
    """Ask a yes/no question. Silence or anything unclear counts as no."""
    answer = ask(question).lower()
    return bool(YES.search(answer)) and not NO.search(answer)


def _spoken_address(text):
    """"john dot smith at gmail dot com" -> "john.smith@gmail.com"; typed addresses pass through."""
    text = text.strip().lower()
    for spoken, symbol in ((" at ", "@"), (" dot ", "."), (" underscore ", "_"), (" dash ", "-"), (" hyphen ", "-")):
        text = text.replace(spoken, symbol)
    return text.replace(" ", "")


NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"


def _number(word):
    word = word.strip()
    return float(word) if re.fullmatch(r"\d+(?:\.\d+)?", word) else NUMBER_WORDS.get(word)


def _sentences(text, count=2):
    return " ".join(re.split(r"(?<=[.!?])\s+", text.strip())[:count])


# ---------------------------------------------------------------- small talk

@intent(r"^(?:hi|hello|hey|hello there|good (?:morning|afternoon|evening)|assalam ?o? ?alaikum|salam)$")
def greet(m, ask):
    return random.choice(["Hello sir, how can I help?", "At your service, sir.", "Hello sir. What can I do for you?"])


@intent(r"^how are you", r"^how(?:'s| is) it going")
def how_are_you(m, ask):
    return "All systems running smoothly, sir. How can I help?"


@intent(r"^(?:thanks|thank you|great|good job|well done|nice)\b",
        r"^(?:perfect|awesome|excellent|cool|brilliant|wonderful|alright|all right|got it|understood|that works)$")
def thanks(m, ask):
    return random.choice(["You're welcome, sir.", "Always a pleasure, sir.", "Happy to help."])


@intent(r"^(?:who are you|what(?:'s| is) your name|introduce yourself)")
def who_are_you(m, ask):
    return "I'm Jarvis, your personal assistant, back online and upgraded."


@intent(r"^(?:what(?:'s| is) my name|who am i|do you know (?:my name|who i am)|what do you call me)$")
def my_name(m, ask):
    return f"You're {config.USER_NAME}, sir."                       # a fact Jarvis already has; a small model gets it wrong


@intent(r"\bwhy\b.*(?:\bnot\b|n't|\bnever\b).*\b(?:speak|speaking|talk|talking|say anything)\b",
        r"^(?:can you |could you )?(?:speak|talk|say something)$",
        r"^(?:are you there|(?:can you )?hear me|test (?:your |the )?voice|voice test)$")      # "can you" is stripped first
def voice_check(m, ask):
    if not config.TTS_ENABLED:
        return "My voice is switched off in the dot env file, sir. Set T T S enabled to true to hear me."
    return ("I'm speaking now, sir. If you can't hear me, check the Windows volume and the output device, "
            "or run speech dot py in a terminal to test my voice.")


@intent(r"^(?:what can you do|help|what are your (?:features|skills|commands))")
def help_me(m, ask):
    return ("I can tell you the time and weather, do maths and conversions, keep notes, tasks and reminders, open apps and "
            "files, check your PC, follow space news, tell jokes, and chat about almost anything. Just ask, sir.")


# ---------------------------------------------------------------- time

@intent(r"\bwhat(?:'?s| is) the time\b", r"\bwhat time is it\b", r"\b(?:tell me the|current) time\b", r"^time$")
def time_now(m, ask):
    return "It's " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0") + "."


@intent(r"^is it (?:a\.?m\.?|p\.?m\.?|morning|afternoon|evening|night|day(?:time)?|noon|midnight)"
        r"(?: or (?:a\.?m\.?|p\.?m\.?|morning|afternoon|evening|night|day(?:time)?))?$",
        r"^(?:what )?(?:part of the day|time of (?:the )?day) is it$", r"^(?:a\.?m\.?|p\.?m\.?) (?:or|and|/) (?:a\.?m\.?|p\.?m\.?)$")
def part_of_the_day(m, ask):
    now = datetime.datetime.now()
    period = "morning" if 5 <= now.hour < 12 else "afternoon" if 12 <= now.hour < 17 else "evening" if 17 <= now.hour < 21 else "night"
    return f"It's {now.strftime('%I:%M %p').lstrip('0')}, so it's {period}, sir."


@intent(r"\bwhat(?:'?s| is) (?:the |today'?s )?date\b", r"\bwhat day is (?:it|today)\b", r"\btoday'?s date\b", r"^date$")
def date_today(m, ask):
    return "Today is " + datetime.datetime.now().strftime("%A, %d %B %Y") + "."


# ---------------------------------------------------------------- reminders and to-do list

def _duration_minutes(text):
    if re.search(r"\bhalf an? hour\b", text):
        return 30
    found = re.search(rf"\b(?:in|for|after) {NUM} ?(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", text)
    if not found:
        return None
    amount, unit = _number(found.group(1)), found.group(2)
    return amount / 60 if unit.startswith("s") else amount * 60 if unit.startswith("h") else amount


def _clock_time(text):
    """Find a clock time like "at 7:30 pm" and return it as 24-hour "HH:MM"."""
    found = re.search(r"\b(?:at|for)\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*o'?clock)?(?:\s*([ap])\.?\s?m\b\.?)?", text)
    if not found:
        return None
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), found.group(3)
    if hour > 23 or minute > 59:
        return None
    if half == "p" and hour < 12:
        hour += 12
    elif half == "a" and hour == 12:
        hour = 0
    elif not half and 1 <= hour <= 12:
        # No am/pm: pick whichever of morning or evening comes next.
        now = datetime.datetime.now()
        hour = min((hour % 12, hour % 12 + 12),
                   key=lambda h: (datetime.datetime.combine(now.date(), datetime.time(h, minute)) - now)
                   % datetime.timedelta(days=1))
    return f"{hour:02d}:{minute:02d}"


def _reminder_message(text):
    found = re.search(r"\bto (.+?)(?=\s+(?:in|at|after|for)\s+(?:\d|an?\b|half)|$)", text)
    if found and not found.group(1)[0].isdigit():
        return _as_typed(found.group(1))
    if "timer" in text:
        return "Your timer is done"
    if "alarm" in text or "wake me" in text:
        return "Wake up, sir"
    return "Reminder"


@intent(r"\b(?:remind me|reminder|alarm|timer|wake me up)\b")
def reminder(m, ask):
    text = m.string
    message = _reminder_message(text)
    minutes, clock = _duration_minutes(text), _clock_time(text)
    if not minutes and not clock:
        if text.startswith("remind me to"):
            return T.add_task(message) + ". I've put it on your to-do list."
        answer = ask("When should it go off? For example, in ten minutes, or at seven thirty p m.").lower()
        minutes, clock = _duration_minutes("in " + answer), _clock_time("at " + answer)
    if minutes:
        return T.set_reminder(message=message, minutes_from_now=minutes)
    if clock:
        return T.set_reminder(message=message, at_time=clock)
    return "Sorry sir, I didn't catch the time."


TODO = r"(?:to ?do|to-do|todo|task)s?(?: list)?"
FINISHED = re.compile(r"(?:done|finished|that'?s all|that is all|that'?s it|no more|nothing|nothing else|stop|no|nope|enough)")


@intent(rf"^(?:make|create|start|build|prepare|set up|write)(?: me)?(?: a| my)?(?: new)? (?:(?:to ?do|to-do|todo)(?: list)?|tasks? list)(?: this| just)?(?: for (?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?(?:\b.*)?$")
def make_todo_list(m, ask):
    """Take the tasks one at a time. A task said with a time ("call Ali at 5 pm") also gets a reminder at that time."""
    day = _day_from_word(m["day"] or "today")
    added = []
    question = "Okay sir. You can add a time, like: call Ali at 5 pm. Say done when you have finished. What is the first task?"
    while len(added) < 20:
        answer = ask(question).strip()
        spoken = normalize(answer)
        if not spoken or FINISHED.fullmatch(spoken):
            break
        clock = _clock_time(spoken)
        task = _as_typed(re.sub(r"\s+(?:at|for)\s+\d.*$", "", spoken).strip()) if clock else answer
        T.add_task(task, day)
        if clock:
            T.set_reminder(message=task, at_time=clock)
        added.append(f"{task} at {clock}" if clock else task)
        question = "Added. What is the next task, or are you done?"
    if not added:
        return "Okay, no tasks added."
    return f"Done sir. I added {len(added)} task{'' if len(added) == 1 else 's'}: " + "; ".join(added) + "."


@intent(rf"^(?:add|put|write) (?P<task>.+?) (?:to|on|in|into) (?:my |the )?{TODO}$",
        r"^(?:add|new|create|schedule|make|set up) (?:me )?(?:a |an )?(?:new )?task(?: to do)?[:,]?\s*(?P<task>.*)$")
def add_task(m, ask):
    task = _as_typed(m["task"].strip()) or ask("What's the task?")
    return T.add_task(task) + "." if task else "Okay, nothing added."


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _day_from_word(word):
    """"today", "tomorrow" or a weekday name (the next one) as YYYY-MM-DD; "" for anything else."""
    today = datetime.date.today()
    if word == "today":
        return today.isoformat()
    if word == "tomorrow":
        return (today + datetime.timedelta(days=1)).isoformat()
    if word in WEEKDAYS:
        ahead = (WEEKDAYS.index(word) - today.weekday()) % 7 or 7
        return (today + datetime.timedelta(days=ahead)).isoformat()
    return ""


@intent(r"^schedule (?P<task>.+?)(?: (?:for|by|on|until|before) (?P<day>today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday))?$")
def schedule_task(m, ask):
    return T.add_task(_as_typed(m["task"].strip()), _day_from_word(m["day"] or "")) + "."


@intent(rf"\b(?:what(?:'s| is)(?: on)?|show|read|list|tell me|check)\b.*\b{TODO}\b",
        rf"^(?:my )?{TODO}(?: for (?:today|tomorrow))?$", r"\bwhat do i have to do\b",
        r"\bwhat\b.*\b(?:tasks?|work)\b.*\b(?:scheduled|planned|due|pending)\b")
def list_tasks(m, ask):
    day = re.search(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", m.string)
    return T.list_tasks(_day_from_word(day.group(1))) if day else T.list_tasks()


@intent(r"\b(?:remove|delete|cross off|tick off|complete|completed|finish|finished|done with|mark)\b"
        r".*?\b(?:task|item|number)\s+(\S+)")
def remove_task(m, ask):
    number = _number(m.group(1))
    return T.remove_task(int(number)) if number else None


# ---------------------------------------------------------------- time table (the user's own routine)

def _to_24h(raw, period=""):
    """"6", "6:30 pm", "18:00" -> "HH:MM"; ``period`` is a spoken "in the evening" applied to bare hours."""
    found = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(?:([ap])\.?m\.?)?", raw.strip())
    if not found:
        return None
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), found.group(3)
    if hour > 23 or minute > 59:
        return None
    if half == "p" and hour < 12:
        hour += 12
    elif half == "a" and hour == 12:
        hour = 0
    elif not half and period in ("afternoon", "evening", "night") and 1 <= hour <= 11:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


CLOCK = r"\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?"


@intent(rf"^add (?P<activity>.+?) (?:from |at )?(?P<start>{CLOCK}) (?:to|until|till|-) (?P<end>{CLOCK})"
        rf"(?: (?:in the |at )(?P<period>morning|afternoon|evening|night))? (?:to|in|on|into) (?:my |the )?(?:time ?table|schedule|routine)$")
def add_to_timetable(m, ask):
    period = m["period"] or ""
    start, end = _to_24h(m["start"], period), _to_24h(m["end"], period)
    if not start or not end:
        return "Sorry sir, I didn't catch those times."
    return T.add_timetable_block(start, end, _as_typed(m["activity"]))


@intent(r"^(?:what(?:'s| is)(?: on)?|show|check|tell me|read|open|display)(?: me)?(?: (?:on|of))? (?:my |the |today'?s |tomorrow'?s )?"
        r"(?:time ?table|schedule|routine)(?: for (?:today|tomorrow|the day|now))?$",
        r"^(?:my )?(?:time ?table|schedule|routine)$", r"\bwhat (?:should|do) i (?:be )?(?:doing|do) (?:now|right now|next)\b")
def timetable(m, ask):
    return T.get_timetable_block()


# ---------------------------------------------------------------- what Jarvis remembers about you
# (facts for the chat brain, kept in DataBase/memory.json; notes are separate: "take a note that ...")

@intent(r"^remember (?:that )?(?!to\b)(?P<fact>.{3,})$")                       # "remember to call Ali" is a reminder, not a fact
def remember_fact(m, ask):
    fact, _, after = m["fact"].partition(" then ") if " then " in m["fact"] else (m["fact"], "", "")
    if re.search(r"\bpass(?:word|code|phrase)s?\b|\bpin\b|\bcvv\b|\bcard number\b", fact):
        return "I'd rather not keep passwords or card numbers, sir. They would sit in a plain text file."
    ChatBrain.remember(_as_typed(fact.strip().rstrip(",")))
    return "Okay sir, I'll remember that." + (" I didn't catch what you said after 'then', sir." if after.strip() else "")


@intent(r"^what (?:do you|have i told you to) (?:remember|know)(?: about me)?$", r"^what have i asked you to remember$",
        r"^(?:list|show|read)(?: me)?(?: all)? (?:my |the )?(?:facts|memories)$")
def recall_facts(m, ask):
    known = ChatBrain.facts()
    if not known:
        return "You haven't asked me to remember anything yet, sir. Say remember that, and then the fact."
    latest = known[-6:]
    more = f", and {len(known) - len(latest)} more" if len(known) > len(latest) else ""
    return "You asked me to remember: " + "; ".join(latest) + more + "."


@intent(r"^(?:forget|clear|delete|erase) (?:all )?(?:my |the )?(?:facts|memories)$",
        r"^forget everything you (?:know|remember)(?: about me)?$")
def forget_all_facts(m, ask):
    count = ChatBrain.forget_facts()
    return f"Done sir, I've forgotten {count} thing{'' if count == 1 else 's'}." if count else "I wasn't remembering anything, sir."


@intent(r"^forget (?:that |what i (?:told|said)(?: you)? about )?(?P<about>.{3,})$")
def forget_one_fact(m, ask):
    return "Forgotten, sir." if ChatBrain.forget_facts(m["about"]) else "I don't have anything like that to forget, sir."


# ---------------------------------------------------------------- notes, password, jokes, screenshot

@intent(r"^(?:start|begin|resume)(?: taking| writing| making)(?: some| a)? notes?$")
def start_notes(m, ask):
    text = ask("Okay sir. What should the note say?").strip()
    return T.take_note(text) + "." if text else "Okay, no note then."


@intent(r"^(?:clear|delete|erase|remove|wipe)(?: all)?(?: of)?(?: my| the)?(?: saved)? notes$")
def clear_notes(m, ask):
    from JarvisAdvancedBot.tools._common import folder
    files = sorted(folder("Notes").glob("*.txt"))
    if not files:
        return "There are no saved notes to clear, sir."
    count = f"{len(files)} note{'' if len(files) == 1 else 's'}"
    if not _confirmed(ask, f"This will permanently delete {count}. Say yes or no."):
        return "Okay, I've kept your notes."
    for note in files:
        note.unlink()
    return f"Deleted {count}, sir."


NOTE_START = r"^(?:(?:take|make|write|save|create)(?: a| me a)? note|note (?:that|down))"


@intent(NOTE_START)
def take_note(m, ask):
    text = re.sub(NOTE_START + r"(?: that| saying| of| about)?[:,]?\s*", "", m.string).strip()
    text = _as_typed(text) or ask("What should the note say?")
    return T.take_note(text) + "." if text else "Okay, no note then."


@intent(r"^open (?:the |my |last |latest |recent |saved )*notes?(?: file| folder| app| application)?$")
def open_the_notes(m, ask):
    """One note opens in Notepad (and is read out); "the notes", plural, open the folder that holds them all."""
    plural = re.search(r"\bnotes\b", m.string) and "file" not in m.string
    return T.open_notes("folder" if plural or "folder" in m.string else "latest") + ", sir."


@intent(r"\b(?:read|show|list|open|see|check|view|what are|what is in|what's in|do i have)(?: me)?(?: all)? (?:my |the |any )?(?:last |latest |recent |saved )?notes?\b",
        r"\bwhat notes\b", r"\b(?:last|latest|recent) note\b")
def read_notes(m, ask):
    if re.search(r"\b(?:last|latest|newest|recent) note\b", m.string):
        return T.read_notes("", True)
    title = re.sub(r".*?\bnotes?\b(?: (?:about|called|named|on))?\s*", "", m.string, count=1).strip()
    title = "" if re.fullmatch(r"(?:do i have|i have|do i|i)?(?: any)?", title) else title
    return _sentences(T.read_notes(title), 4)


@intent(r"\bpassword (?:for|of) (?!(?:jarvis|program|app|assistant|computer|pc|laptop|account|email|windows|login|screen|system|it)\b)(?:the |my )?(?P<name>[\w .-]+?)(?: wi-?fi| network)?$")
def wifi_password_by_name(m, ask):
    names = _saved_wifi_names()
    close = difflib.get_close_matches(m["name"].strip().lower(), [n.lower() for n in names], n=1, cutoff=0.6)
    if not close:
        return None                                       # not a saved network: the other password rules decide
    return T.get_saved_wifi_password(next(n for n in names if n.lower() == close[0]))


@intent(r"^(?!.*\b(?:generate|create|make|give me|new|random|strong|good|best|safe|secure|suggest|wi-?fi|e-?mail|gmail|facebook|"
        r"instagram|discord|account|site|website|network|router|bank)\b)"
        r"(?=.*\bpassword\b)"                                    # (the word "jarvis" is removed before patterns see the sentence)
        r"(?=.*\b(?:unlock|log ?in|program|current|actual|real|forgot|forgotten|reveal|remind|tell me the|what(?:'s| is) the|"
        r"what(?:'s| is) my|my)\b).*$")
def jarvis_password(m, ask):
    named = re.search(r"\bpassword (?:for|of) (?!(?:jarvis|program|app|assistant|computer|pc|laptop|account|email|windows|login|screen|system|it)\b)(?:the |my )?([\w .-]+?)(?: wi-?fi| network)?$", m.string)
    if named:
        try:
            return T.get_saved_wifi_password(named.group(1))
        except ToolError:
            pass                                          # not a saved network: it must be Jarvis's own
    return ("I don't keep your password in a form I can read out, sir, and I wouldn't say it aloud if I could. To choose a new "
            "one, open a terminal in the Jarvis folder and run: python gate.py --set-password")


@intent(r"^(?!.*\bwi-?fi\b)(?!.*\b(?:saved|current|connected)\b).*\b(?:generate|create|make|give me|new|random|strong)\b.*\bpassword\b")
def password(m, ask):
    length = re.search(r"(\d+)\s*(?:characters?|chars?|letters?|digits?|long)", m.string)
    return T.generate_password(int(length.group(1)) if length else 16)


@intent(r"\bjokes?\b", r"\bmake me laugh\b")
def joke(m, ask):
    return T.get_joke()


@intent(r"^(?:where|which folder|what folder)\b.*\bscreen ?shots?\b",
        r"^(?:open|show|see|view|display)(?: me)? (?:the |my |last |latest |recent |saved )*screen ?shots?(?: folder| file| picture| image)?$")
def find_screenshots(m, ask):
    wants_folder = bool(re.search(r"\bwhere\b|\bfolder\b|screen ?shots\b", m.string))
    T.open_screenshots("folder" if wants_folder else "latest")
    return ("Opening the screenshots folder, sir. That is where they are saved." if wants_folder
            else "Opening your latest screenshot, sir.")


@intent(r"^(?!.*\b(?:where|open|show|see|view|saved|folder|find)\b).*\b(?:screenshot|screen shot|capture (?:the |my )?screen)\b")
def screenshot(m, ask):
    return T.take_screenshot() + "."


# ---------------------------------------------------------------- power, folders and Jarvis's own windows

@intent(r"\b(?:cancel|stop|abort)\b.*\b(?:shut ?down|restart|reboot)\b")
def cancel_power(m, ask):
    return T.system_power_action("cancel")


def _power(action, label):
    def handler(m, ask):
        if not _confirmed(ask, f"Are you sure you want me to {label} the computer? Say yes or no."):
            return f"Okay, I won't {label} the computer."
        return T.system_power_action(action, confirmed=True)
    return handler


intent(r"^(?:shut ?down|power off)$", r"\b(?:shut ?down|power off|turn off)\b.*\b(?:computer|pc|laptop|system)\b")(
    _power("shutdown", "shut down"))
intent(r"^(?:restart|reboot)$", r"\b(?:restart|reboot)\b.*\b(?:computer|pc|laptop|system)\b")(_power("restart", "restart"))
intent(r"\b(?:computer|pc|laptop|system)\b.*\b(?:sleep|hibernate|suspend)\b",
       r"\b(?:sleep|hibernate|suspend)\b.*\b(?:computer|pc|laptop)\b")(_power("sleep", "put to sleep"))

PLACES = r"desktop|documents|downloads|pictures"


@intent(r"^(?:open|show|go to|browse)(?: the| my)? (?:tasks?|to ?do) (?:folder|holder|fol?der|directory)$")
def open_tasks_folder(m, ask):
    from JarvisAdvancedBot.tools._common import folder
    T.open_folder(str(folder("Tasks")))
    return "Opening your tasks folder, sir."


@intent(r"^(?:open|show|go to|browse)(?: this| the)?(?: folder| file)?[:,]? (?P<path>[a-z]:[\\/].+)$")
def open_a_path(m, ask):
    path = _as_typed(m["path"]).strip().strip('"')
    T.open_folder(path)
    return f"Opening {path}, sir."


@intent(r"^(?:open|show|go to|browse) (?:the |my )?(?:local )?(?:disk|drive) (?P<drive>[a-z])(?: drive)?$",
        r"^(?:open|show|go to|browse) (?:the |my )?(?P<drive>[a-z]) (?:drive|disk)$",
        rf"^(?:open|go to|browse) (?:the |my )?(?P<folder>{PLACES})(?: folder)?$",
        r"^show (?:the |my )?(?P<folder>documents|downloads|pictures)(?: folder)?$",          # "show desktop" minimises windows
        rf"^(?:open|show|go to|browse) (?:the |my )?(?P<folder>{PLACES}|music|videos) folder$")
def open_a_folder(m, ask):
    found = m.groupdict()
    where = found.get("drive") or found["folder"]
    T.open_folder(where)
    return f"Opening {'drive ' + where.upper() if len(where) == 1 else 'your ' + where + ' folder'}, sir."


@intent(r"^(?:(?:open|launch|start|run|show|use)(?: me)? )?(?:the |my |a )?(?:system|windows|default) (?P<name>calculator|calendar)(?: app| application| program)?$")
def open_the_windows_one(m, ask):
    T.open_app(m["name"])
    return f"Opening the Windows {m['name']}, sir."


UTILITY_ALIASES = {"calc": "calculator", "calculation": "calculator", "calender": "calendar", "currency": "currency converter",
                   "currency convertor": "currency converter", "exchange rate converter": "currency converter"}


@intent(r"^(?:(?:open|launch|start|run|show|use|bring up)(?: me)? )?(?:the |my |a |your )?"
        r"(?P<name>calculator|calc|calculation|calendar|calender|currency convert[eo]r|currency|exchange rate converter)"
        r"(?: app| application| program| window)?$")
def open_a_utility(m, ask):
    said = UTILITY_ALIASES.get(m["name"], m["name"])
    name = said.replace(" ", "_").replace("convertor", "converter")
    try:
        T.open_utility_app(name)
    except ToolError:                                    # Jarvis's own window isn't installed: use Windows' or the web
        if name == "calculator":
            T.open_app("calculator")
        elif name == "calendar":
            T.open_website("https://calendar.google.com")
        else:
            raise
    return f"Opening the {said}, sir."


# ---------------------------------------------------------------- searches (before weather, so "search for weather radar" searches)

@intent(r"^(?:search )?(?:on )?youtube (?:for )?(?P<q>.+)$", r"^search (?:for )?(?P<q>.+) on youtube$")
def youtube_search(m, ask):
    T.youtube(m["q"], play=False)
    return f"Here are the YouTube results for {m['q']}."


@intent(r"^(?:google|search(?: on)?(?: google)?(?: for)?|look up|search the web for) (?P<q>.+)$")
def google(m, ask):
    T.search_google(m["q"])
    return f"Here are the Google results for {m['q']}."


# ---------------------------------------------------------------- browser, Windows and media keys

KEY_COMMANDS = [
    ("browser_action", [
        (r"\bnew tab\b", "new_tab"), (r"\b(?:reopen|restore) (?:the )?(?:closed |last )?tab\b", "reopen_closed_tab"),
        (r"\bclose (?:this |the )?tab\b", "close_tab"), (r"\bnext tab\b", "next_tab"),
        (r"\bprevious tab\b", "previous_tab"), (r"\bincognito\b", "incognito_window"),
        (r"\bnew (?:browser )?window\b", "new_window"),
        (r"^(?:(?:open|show|see|view|go to|bring up|check)(?: me)? )?(?:my |the )?(?:browser |browsing |chrome )?history(?: page| tab)?$", "history"),
        (r"\b(?:browser|chrome|firefox|edge) downloads\b", "downloads"), (r"\bbookmark\b", "bookmark_page"),
        (r"^(?:refresh|reload)(?: the| this)?(?: page)?$", "refresh"), (r"\bzoom in\b", "zoom_in"),
        (r"\bzoom out\b", "zoom_out"), (r"\breset (?:the )?zoom\b", "reset_zoom"),
    ]),
    ("windows_action", [
        (r"\b(?:show (?:the )?desktop|home screen|minimi[sz]e (?:all|everything))\b", "show_desktop"),
        (r"\brestore (?:all )?windows\b", "restore_windows"),
        (r"\block (?:the |my )?(?:screen|pc|computer|laptop)\b", "lock_screen"),
        (r"^(?:open )?(?:windows |the |my )?settings$", "open_settings"),
        (r"^(?:(?:open|show|launch|start) )?(?:the |my )?(?:file explorer|explorer|files|this pc)$", "file_explorer"),
        (r"\b(?:task view|show all windows)\b", "task_view"), (r"\bswitch (?:the )?windows?\b", "switch_window"),
        (r"\b(?:snip|snipping|screen snip)\b", "snip_screen"),
        (r"\b(?:action center|notification center|notifications)\b", "action_center"),
        (r"\b(?:new|add a|add) (?:virtual )?desktop\b", "new_virtual_desktop"),
        (r"\bnext desktop\b", "next_virtual_desktop"), (r"\bprevious desktop\b", "previous_virtual_desktop"),
        (r"\bclose (?:this |the )?(?:virtual )?desktop\b", "close_virtual_desktop"),
        (r"\bstart menu\b", "start_menu"),
    ]),
    ("youtube_control", [
        (r"\bfull ?screen\b", "fullscreen"), (r"\btheat(?:er|re) mode\b", "theater_mode"),
        (r"\b(?:skip|forward|fast forward)(?: by)? (?:10|ten) seconds\b", "forward_10_seconds"),
        (r"\b(?:go back|rewind|back)(?: by)? (?:10|ten) seconds\b", "back_10_seconds"),
        (r"\b(?:captions|subtitles)\b", "captions"), (r"\b(?:speed up|play faster)\b", "faster"),
        (r"\b(?:slow down|play slower)\b", "slower"),
    ]),
]


def _press(tool_name, *args):
    getattr(T, tool_name)(*args)                     # looked up when used, so the tool can be swapped in tests
    return "Done, sir."


for tool_name, phrases in KEY_COMMANDS:
    for pattern, action in phrases:
        intent(pattern)(lambda m, ask, tool_name=tool_name, action=action: _press(tool_name, action))

@intent(r"^play (?:some |a |any )?(?:music|songs?|something)$")
def play_something(m, ask):
    _press("media_control", "play_pause", 1)
    return ("I pressed play, sir. If nothing started, no player had anything to resume. Tell me what to play, "
            "for example: play despacito, and I'll find it on YouTube.")


MEDIA_COMMANDS = [
    (r"^(?:pause|resume|play|stop|continue|unpause)(?: (?:the |this )?(?:music|song|video|it|playback|track))?$", "play_pause", 1),
    (r"^(?:next|skip)(?: (?:the |this )?(?:song|track|video|one))?$", "next_track", 1),
    (r"\b(?:play )?(?:the )?next (?:song|track|video)\b", "next_track", 1),
    (r"\b(?:previous|last) (?:song|track|video)\b", "previous_track", 1),
    (r"\b(?:volume up|increase (?:the )?volume|turn (?:the volume|it) up|louder|raise (?:the )?volume)\b", "volume_up", 5),
    (r"\b(?:volume down|decrease (?:the )?volume|turn (?:the volume|it) down|quieter|lower (?:the )?volume"
     r"|reduce (?:the )?volume)\b", "volume_down", 5),
    (r"^(?:mute|unmute)(?: (?:the )?(?:volume|sound|audio|pc|computer|it))?$", "mute", 1),
]

for pattern, action, times in MEDIA_COMMANDS:
    intent(pattern)(lambda m, ask, action=action, times=times: _press("media_control", action, times))


@intent(r"^play (?P<q>.+?)(?: on youtube)?$")
def youtube_play(m, ask):
    return T.youtube(m["q"]) + "."


# ---------------------------------------------------------------- maths

MATH_WORDS = [
    (r"(?<=\d),(?=\d{3})", ""), (r"(\d+(?:\.\d+)?)\s*(?:%|percent) of\b", r"(\1/100)*"),
    (r"(\d+(?:\.\d+)?)\s*(?:%|percent)", r"(\1/100)"), (r"\bsquare root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)"),
    (r"\bcube root of\s*(\d+(?:\.\d+)?)", r"(\1)**(1/3)"),
    (r"\bmultiplied by\b|\btimes\b|\binto\b|×|\bx\b", "*"), (r"\bdivided by\b|\bover\b|÷", "/"),
    (r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\bto the power of\b|\bpower\b|\^", "**"),
    (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"),
]


@intent(r"^(?:calculate|compute|solve|what(?:'?s| is)|how much is)\s+(?P<expr>(?:(?:square|cube) root of |-|\()?\d.*)$",
        r"^(?:what(?:'?s| is) )?(?:the )?(?P<expr>(?:square|cube) root of \d.*)$",
        r"^(?P<expr>[\d(][\d\s.,+\-*/x×÷()^%]*[\d)%])$")
def calculate(m, ask):
    expr = m["expr"]
    for pattern, replacement in MATH_WORDS:
        expr = re.sub(pattern, replacement, expr)
    try:
        value = calc.evaluate(expr)
    except ValueError:
        return None  # not a sum (e.g. "100 dollars in rupees"); let another intent try
    value = round(value, 6)
    return f"That's {int(value) if value == int(value) else value:,}."


# ---------------------------------------------------------------- money

COINS = (r"(?P<coin>bitcoin|btc|ethereum|ether|eth|dogecoin|doge|solana|bnb|xrp|ripple|cardano|litecoin|ltc|tron|"
         r"shiba inu|shib|polkadot|toncoin|tether|usdt|pepe)")

CURRENCIES = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "us dollar": "USD", "us dollars": "USD", "bucks": "USD",
    "pkr": "PKR", "rupee": "PKR", "rupees": "PKR", "pakistani rupee": "PKR", "pakistani rupees": "PKR",
    "inr": "INR", "indian rupee": "INR", "indian rupees": "INR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "british pound": "GBP", "british pounds": "GBP",
    "sar": "SAR", "riyal": "SAR", "riyals": "SAR", "saudi riyal": "SAR", "saudi riyals": "SAR",
    "aed": "AED", "dirham": "AED", "dirhams": "AED", "jpy": "JPY", "yen": "JPY", "cny": "CNY", "yuan": "CNY",
    "lira": "TRY", "cad": "CAD", "canadian dollar": "CAD", "canadian dollars": "CAD", "aud": "AUD",
    "australian dollar": "AUD", "australian dollars": "AUD", "afghani": "AFN", "afghanis": "AFN",
    "taka": "BDT", "ringgit": "MYR", "qar": "QAR", "kuwaiti dinar": "KWD",
}
CUR = "|".join(sorted(map(re.escape, CURRENCIES), key=len, reverse=True))


def _currency_in(text):
    found = re.search(rf"\b(?:in|to) ({CUR})\b", text)
    return CURRENCIES[found.group(1)] if found else None


@intent(rf"\b{COINS}\b.*\b(?:price|rate|worth|value|cost)\b", rf"\b(?:price|rate|value|worth) of (?:a |one )?{COINS}\b",
        rf"\bhow much is (?:a |one )?{COINS}\b")
def crypto(m, ask):
    return T.get_crypto_price(m["coin"], (_currency_in(m.string) or "usd").lower())


@intent(rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<src>{CUR})\b\s+(?:to|in|into)\s+(?P<dst>{CUR})\b",
        rf"\$\s?(?P<amount>\d[\d,]*(?:\.\d+)?)\s+(?:to|in|into)\s+(?P<dst>{CUR})\b",
        rf"\b(?P<src>{CUR}) (?:rate|exchange rate|price)\b", rf"\b(?:rate|value) of (?:the )?(?P<src>{CUR})\b")
def currency(m, ask):
    groups = m.groupdict()
    src = CURRENCIES[groups["src"]] if groups.get("src") else "USD"
    dst = CURRENCIES[groups["dst"]] if groups.get("dst") else (HOME_CURRENCY if src != HOME_CURRENCY else "USD")
    amount = float(groups["amount"].replace(",", "")) if groups.get("amount") else 1
    return T.convert_currency(amount, src, dst)


# ---------------------------------------------------------------- space (before weather, so "temperature of Mars" is about Mars)

@intent(r"\bpicture of the day\b", r"\b(?:nasa|astronomy|space) (?:picture|photo|image|pic)s?\b", r"\bapod\b")
def space_picture(m, ask):
    return T.nasa_picture_of_the_day()


PHOTO = r"(?:photos?|pictures?|images?|pics?)"


@intent(rf"\bmars\b.*\b{PHOTO}\b", rf"\b{PHOTO}\b.*\bmars\b", rf"\b(?:curiosity|perseverance)\b.*\b{PHOTO}\b",
        r"\b(?:curiosity|perseverance) rover\b")
def mars_photo(m, ask):
    rover = "perseverance" if "perseverance" in m.string else "curiosity"
    if rover == "perseverance":
        _heads_up("Fetching Perseverance's newest photo. NASA's server is slow, so this can take twenty seconds.")
    return T.nasa_mars_photos(rover)


BODY = r"(?P<body>sun|moon|mercury|venus|earth|mars|jupiter|saturn|uranus|neptune|pluto)"


SOLAR_ASPECTS = [
    (r"\bhow (?:far|distant)\b", "distance"), (r"\bhow (?:hot|cold|warm)\b|\btemperature\b", "temperature"),
    (r"\bhow (?:big|large)\b|\bsize\b|\bradius\b", "size"), (r"\bhow heavy\b|\bgravity\b", "gravity"),
    (r"\bmoons\b", "moons"), (r"\bday length\b|\bhow long is (?:a|one|the) day\b", "day"),
    (r"\byear length\b|\bhow long is (?:a|one|the) year\b", "year"),
]


@intent(rf"\b(?:facts?|info|information|details|stats|statistics) (?:about|on|of|for) (?:the |planet )?{BODY}\b",
        rf"^(?:tell me|what do you know) about (?:the |planet )?{BODY}$",
        rf"\bhow (?:big|hot|cold|far|heavy|large) is (?:the |planet )?{BODY}\b",
        rf"\b(?:gravity|temperature|radius|size|moons|day length|year length) (?:of|on) (?:the |planet )?{BODY}\b",
        rf"\bhow many moons (?:does|do) (?:the |planet )?{BODY} have\b",
        rf"\bhow long is (?:a|one|the) (?:day|year) (?:on|of) (?:the |planet )?{BODY}\b")
def solar_body(m, ask):
    aspect = next((name for pattern, name in SOLAR_ASPECTS if re.search(pattern, m.string)), "all")
    return T.nasa_solar_body_facts(m["body"], aspect)


@intent(r"\basteroids?\b", r"\bnear[- ]earth (?:objects?|asteroids?)\b")
def asteroids(m, ask):
    if "week" in m.string:
        today = datetime.date.today()
        return T.nasa_near_earth_objects(today.isoformat(), (today + datetime.timedelta(days=6)).isoformat())
    return T.nasa_near_earth_objects()


@intent(r"\b(?:iss|international space station|space station)\b", r"^where(?:'s| is) (?:the )?is$")      # "where is is": how ISS is heard
def space_station(m, ask):
    return T.get_iss_location()


@intent(r"\bstarlink\b")
def starlink(m, ask):
    _heads_up("Checking the Starlink satellite list, one moment.")
    return T.spacex_starlink_count()


@intent(r"\bnext\b.*\blaunch(?:es)?\b", r"\bupcoming\b.*\blaunch(?:es)?\b", r"\bspace ?x\b.*\b(?:next|upcoming)\b")
def next_launch(m, ask):
    return T.spacex_latest_launch("next")


@intent(r"\b(?:latest|last|recent|previous)\b.*\blaunch(?:es)?\b", r"\bspace ?x\b.*\b(?:latest|last|recent)\b")
def last_launch(m, ask):
    return T.spacex_latest_launch("latest")


@intent(r"\bspace ?x\b")
def spacex(m, ask):
    return T.spacex_company_info()


# ---------------------------------------------------------------- weather, location, PC

def _place(text):
    found = re.search(r"\b(?:in|at|for|of) ([a-z][a-z .'-]*?)(?: (?:today|tomorrow|tonight|right now|now|this week))?$", text)
    place = found.group(1).strip() if found else ""
    return "" if place in {"today", "tomorrow", "tonight", "now", "right now", "this week", "the week"} else place


@intent(r"\b(?:weather|forecast|how (?:hot|cold|warm) is it|is it (?:going to )?rain)",
        # "temperature" is the weather only when it is what is being asked for ("what's the temperature in London"), not when it
        # is a word in a general question ("at what temperature does water boil")
        r"^(?:(?:what(?:'s| is)|how(?:'s| is)|tell me|show me|give me|check)(?: me)? )?(?:the |today'?s |current |outside )*temperature"
        r"(?: (?:like|outside|today|tomorrow|now|right now|here|this week))*(?: (?:in|at|for) .+)?$")
def weather(m, ask):
    return T.weather_report(_place(m.string) or DEFAULT_CITY)


@intent(r"\bwhere am i\b", r"\b(?:my|current) location\b", r"\bwhich city am i in\b")
def location(m, ask):
    return T.get_my_location()


PC_TOPICS = [
    (r"\b(?:cpu|processor)\b", "cpu"),
    (r"\b(?:ram|memory)\b", "memory"),
    (r"\b(?:disk|storage|drives?|hard ?drive)\b", "disks"),
    (r"\b(?:ip address|network|internet connection|am i connected)\b", "network"),
    (r"\b(?:windows version|operating system|computer name|system info(?:rmation)?|system details|specs|specifications)\b", "system"),
]


@intent(r"\b(?:battery|cpu|processor|ram|memory usage|disk space|storage|drives|system (?:status|info|information|details)"
        r"|pc status|computer status|uptime|ip address|network status|internet connection|am i connected"
        r"|windows version|operating system|computer name|specs|specifications"
        r"|(?:status|health|state|condition) of (?:my |the )?(?:pc|computer|laptop|system)"
        r"|how(?:'s| is) (?:my |the )?(?:pc|computer|laptop)(?: doing| running)?)\b")
def pc_info(m, ask):
    battery = psutil.sensors_battery()
    if "battery" in m.string and battery:
        state = "charging" if battery.power_plugged else "not charging"
        return f"The battery is at {battery.percent:.0f} percent and {state}."
    topic = next((name for pattern, name in PC_TOPICS if re.search(pattern, m.string)), None)
    return T.get_system_details(topic) if topic else T.get_system_status() + "."


@intent(r"^(?:show|open|find|locate|display)(?: me)? (?P<place>.+?) (?:on|in) (?:the |google )?(?:google )?maps?$",
        r"^(?:map of|navigate to|directions to) (?P<place>.+)$", r"^how far (?:is|away is) (?P<place>.+)$",
        r"^distance (?:to|from here to) (?P<place>.+)$")
def map_place(m, ask):
    return T.show_on_map(_as_typed(m["place"]))


# ---------------------------------------------------------------- translation

LANG = "|".join(sorted(LANGUAGES, key=len, reverse=True))


@intent(rf"^translate (?P<text>.+?) (?:to|into|in) (?P<lang>{LANG})$", rf"^how do you say (?P<text>.+?) in (?P<lang>{LANG})$")
def translate(m, ask):
    result = T.translate_text(m["text"], m["lang"])
    language = m["lang"].title()
    if all(ord(c) < 0x0370 for c in result):  # Latin script, which the voice can read aloud
        return f"In {language}, that's: {result}"
    _heads_up(f"Here is the {language} translation, sir.")
    _show(result)                              # in the conversation, not just the log: the voice can't read this script
    return ""


# ---------------------------------------------------------------- books, acronyms, folders, Wolfram Alpha

@intent(r"\bread (?:me )?page (?P<page>\d+)(?: (?:of|from) (?:the )?(?:book |pdf )?(?P<title>.+))?$",
        r"\bread (?:me )?(?:the |a |my )?(?:book|pdf)(?: (?P<title>.+?))?(?: page (?P<page>\d+))?$")
def read_book(m, ask):
    found = m.groupdict()
    page = int(found.get("page") or 1)
    text = T.read_book_page((found.get("title") or "").strip(), page)
    spoken = _sentences(text, 4)
    if spoken == text:
        return spoken
    _show(text)                                # the whole page, in the conversation
    return spoken + " The rest of the page is on the screen."


@intent(r"\bacronym\b")
def acronym(m, ask):
    phrase = re.sub(r"^.*?\bacronym\b(?: (?:for|of|from))?\s*", "", m.string).strip() or ask("Which phrase?")
    return T.make_acronym(phrase) if phrase else "Okay, never mind."


@intent(r"^(?:create|make|new|add) (?:a |another )?(?:new )?folder(?: (?:named|called|with the name))?\s*"
        r"(?P<name>.*?)(?: (?:on|in|inside) (?:the |my )?(?P<where>desktop|documents|downloads|pictures|music|videos))?$")
def new_folder(m, ask):
    name = _as_typed(m["name"].strip()) or ask("What should the folder be called?")
    return T.create_folder(name, m["where"] or "documents") + "." if name else "Okay, no folder then."


UNIT = units.pattern()
AMOUNT = r"(?P<n>\d[\d,]*(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|ninety)"


@intent(rf"^(?:convert |what(?:'s| is) |how much is )?{AMOUNT} ?(?P<from>{UNIT}) (?:to|in|into|as|equals?) (?P<to>{UNIT})$",
        rf"^how many (?P<to>{UNIT}) (?:are |is )?(?:there )?in (?:{AMOUNT} ?)?(?:a |an |one )?(?P<from>{UNIT})$")
def unit_conversion(m, ask):
    found = m.groupdict()
    amount = 1.0
    if found.get("n"):
        text = found["n"].replace(",", "")
        amount = float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else float(NUMBER_WORDS.get(text, 1))
    try:
        return units.sentence(amount, found["from"], found["to"])
    except ValueError as problem:
        return str(problem)


@intent(r"^(?:ask )?wolfram(?: alpha)?[,:]? (?P<q>.+)$", r"^convert (?P<q>.+)$")
def wolfram(m, ask):
    return T.ask_wolfram_alpha(m["q"])


# ---------------------------------------------------------------- the wider world

def _country(text):
    filler = (r"\b(?:covid(?:-?19)?|corona ?virus|virus|cases?|stats?|statistics|numbers?|figures?|updates?|news|situation|"
              r"the|latest|current|currently|today|now|right|what|whats|what's|are|is|how|many|much|of|in|for|from|at|show|"
              r"me|tell|give|about|worldwide|global|globally|world|total|deaths?|infections?|there|any|check|get)\b")
    return " ".join(re.sub(r"[^a-z .'-]", " ", re.sub(filler, " ", text)).split())


@intent(r"\b(?:covid|corona ?virus)\b")
def covid(m, ask):
    return T.get_disease_outbreak_stats(_country(m.string))


@intent(r"\b(?:business|company|brand|startup|shop|store) names?\b", r"\bname ideas?\b", r"\bsuggest (?:a |some )?names? for\b")
def business_names(m, ask):
    keyword = re.sub(r"^.*\b(?:names?|ideas?)\b(?: (?:for|about|around|on))?\s*", "", m.string)
    keyword = re.sub(r"^(?:my|a|an|the|some)\s+", "", keyword).strip() or ask("What is the business about?")
    return T.generate_business_names(keyword)


@intent(r"\b(?:random|interesting|fun|cool|useless|amazing) fact\b", r"^(?:tell me |give me )?(?:a )?fact$",
        r"\bcat facts?\b", r"\bfact about cats\b")
def random_fact(m, ask):
    return T.get_random_fact("cat" if "cat" in m.string else "any")


@intent(r"\b(?:i(?:'m| am) bored|bored|something to do|suggest (?:an |some )?activit(?:y|ies))\b")
def bored(m, ask):
    return T.get_random_activity()


@intent(r"^(?:give me |tell me |i need |any )?(?:some |a piece of )?(?:random |life )?advice$")
def advice(m, ask):
    return T.get_random_advice()


@intent(r"\b(?:dog|puppy) (?:picture|photo|image|pic)s?\b", r"\b(?:show|give) me a (?:dog|puppy)\b",
        r"\b(?:picture|photo|image|pic)s? of (?:a )?(?:dog|puppy|dogs)\b")
def dog(m, ask):
    return T.get_dog_image()


@intent(r"\bcrack\b.*\bpassword\b", r"\bpassword crack")
def crack(m, ask):
    length = re.search(r"(\d+)\s*(?:characters?|chars?|letters?|digits?)", m.string)
    return T.password_cracking_demo(int(length.group(1)) if length else 8)


@intent(r"\bhack\b.*\b(?:random|someone|somebody|person|people|target|profile)\b", r"^start hacking$", r"^hack\b")
def hack(m, ask):
    return T.hack_a_random_profile()


@intent(r"\binstagram\b.*\b(?:profile (?:pic|picture|photo)|dp|display picture)\b",
        r"\b(?:profile (?:pic|picture|photo)|dp|display picture)\b.*\binstagram\b")
def instagram(m, ask):
    found = re.search(r"\b(?:of|for|from|account|user|username|named|called)\s+@?([a-z0-9._]+)\s*$", m.string)
    name = found.group(1) if found else ask("Which Instagram username?").strip().lstrip("@")
    if not name:
        return "Okay, never mind."
    wants_file = bool(re.search(r"\b(?:download|save|get)\b", m.string)) or not re.search(r"\b(?:open|show|view|see)\b", m.string)
    return T.instagram_profile_picture(name, wants_file)


@intent(r"\b(?:send|write|compose|draft) (?:an? |another )?(?:e-?mail|mail)\b")
def email(m, ask):
    if not (config.EMAIL_ADDRESS and config.EMAIL_PASSWORD):
        return "Email isn't set up yet, sir. Add your address and an app password to the dot env file."
    to = _spoken_address(ask("Who should I send it to? Type the address, or say it like john at gmail dot com."))
    if not to:
        return "Okay, no email then."
    subject = ask("What's the subject?").strip()
    body = ask("What should the message say?").strip()
    if not body:
        return "Okay, no email then."
    if not _confirmed(ask, f"I'll email {to}, subject {subject or 'none'}, saying: {body}. Shall I send it?"):
        return "Okay, I haven't sent anything."
    return T.send_email(to, subject or "(no subject)", body, confirmed=True)


@intent(r"\b(?:available|nearby|around|in range|visible) wi-?fi(?: networks| connections| names)?\b",
        r"\bwi-?fi (?:networks?|connections?|names?) (?:available|nearby|around|in range)\b",
        r"\b(?:list|show|scan|find|see|check|get|search)\b.*\bwi-?fi(?: networks?| connections?| names?)?\b")
def wifi_in_range(m, ask):
    if re.search(r"\b(?:pas\w*|saved|known|stored|my|current|connected)\b", m.string):
        return None                                       # the password handler answers both
    import subprocess
    try:
        shown = subprocess.run(["netsh", "wlan", "show", "networks"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        shown = ""
    names = list(dict.fromkeys(re.findall(r"^SSID \d+ : (.+)$", shown, flags=re.M)))
    names = [name.strip() for name in names if name.strip()]
    if not names:
        return "I can't see any Wi-Fi networks right now, sir. The Wi-Fi may be off, or this PC has no Wi-Fi adapter."
    return f"I can see {len(names)} Wi-Fi network{'' if len(names) == 1 else 's'}: " + ", ".join(names[:10]) + "."


def _saved_wifi_names():
    from JarvisAdvancedBot.tools import world
    try:
        return re.findall(r"^[ \t]*[^:\n]*Profile[^:\n]*:[ \t]*(.+?)[ \t]*$", world._netsh("show", "profiles"), flags=re.M)
    except ToolError:
        return []


def _all_wifi_passwords():
    """Each saved network's password goes to the screen (never aloud); the last one is left on the clipboard."""
    shown = 0
    for name in _saved_wifi_names():
        try:
            T.get_saved_wifi_password(name)
            shown += 1
        except ToolError:
            continue
    return f"I put {shown} Wi-Fi password{'' if shown == 1 else 's'} on your screen. I don't read passwords aloud."


@intent(r"\bwi-?fi\b.*\bpas\w*", r"\bpas\w*\b.*\bwi-?fi\b", r"\b(?:saved|known|stored|my) wi-?fi (?:networks|connections|names)\b")
def wifi(m, ask):
    found = re.search(r"\b(?:of|for)\s+(?:the |my )?(?:wi-?fi )?(?:network )?(?:named |called )?(.+?)(?: wi-?fi| network)?$", m.string)
    name = _as_typed(found.group(1)) if found else ""
    if not name and re.search(r"\b(?:current|connected|this)\b", m.string):
        from JarvisAdvancedBot.tools import world
        try:
            joined = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", world._netsh("show", "interfaces"), flags=re.M)
        except ToolError:
            joined = None
        name = joined.group(1) if joined else ""
    if not name:
        listing = T.get_saved_wifi_password("").replace("Tell me which one you want the password for.", "Which one do you want the password for, or all of them?")
        name = ask(listing).strip()                                 # lists the saved networks, then asks which
        if not name:
            return "Okay, never mind."
        if re.fullmatch(r"(?:all|all of them|every one|everyone|every network|each one|all networks)", normalize(name)):
            return _all_wifi_passwords()
    reply = T.get_saved_wifi_password(name)
    if re.search(r"\b(?:available|nearby|in range)\b", m.string):
        reply += " " + (wifi_in_range(re.search(r"", "available"), ask) or "")
    return reply


@intent(r"\bdownload\b.*\b(?:youtube|video|song|music|audio)\b", r"\b(?:youtube|video)\b.*\bdownload\b")
def youtube_download(m, ask):
    link = re.search(r"https?://\S+", original())
    if not link:
        link = re.search(r"https?://\S*youtu\S*", read_clipboard())            # a link the user just copied
    url = link.group(0) if link else ask("Please paste the YouTube link.").strip()
    if not url:
        return "Okay, I won't download anything."
    if not re.match(r"https?://", url):
        return "That wasn't a YouTube link, so I've cancelled the download. Say it again when you have the link, sir."
    _heads_up("Downloading. This can take a minute.")
    return T.download_youtube_video(url, bool(re.search(r"\b(?:audio|song|music|mp3|sound)\b", m.string)))


@intent(r"\bfree[- ](?:to[- ]play )?games?\b")
def free_game(m, ask):
    after = re.split(r"\bfree[- ](?:to[- ]play )?games?\b", m.string, maxsplit=1)[-1]
    title = re.sub(r"^\s*(?:called|named|of|about|for|on|the|a)\b\s*", "", after).strip()
    return T.lookup_free_game("" if title in {"suggestion", "suggestions", "recommendation", "idea"} else title)


@intent(r"\bminecraft\b.*\bserver\b", r"\bserver\b.*\bminecraft\b")
def minecraft(m, ask):
    spoken = re.sub(r"\s+dot\s+", ".", m.string)
    found = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d{1,5})?)\b", spoken)
    host = found.group(1) if found else _spoken_address(ask("What is the server address?"))
    return T.lookup_minecraft_server(host) if host else "Okay, never mind."


# ---------------------------------------------------------------- apps and websites

WEBSITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "whatsapp": "https://web.whatsapp.com", "whatsapp web": "https://web.whatsapp.com",
    "github": "https://github.com", "twitter": "https://x.com", "linkedin": "https://www.linkedin.com",
    "netflix": "https://www.netflix.com", "wikipedia": "https://www.wikipedia.org", "amazon": "https://www.amazon.com",
    "reddit": "https://www.reddit.com", "stack overflow": "https://stackoverflow.com", "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com", "claude": "https://claude.ai", "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com", "google translate": "https://translate.google.com",
}


@intent(r"^(?:open|launch|start|run) (?:the |my )?(?P<name>.+?)(?: app| application| website| site| for me)?$")
def open_something(m, ask):
    name = m["name"].strip()
    if len(name.split()) > 3 or re.search(r"\b(?:so that|i can|that i|to do|chat|taking|writing)\b", name):
        return None                                      # a sentence, not the name of an app: it is for the chat brain
    if name in WEBSITES or re.search(r"\.\w{2,}$", name):
        T.open_website(WEBSITES.get(name, name))
    else:
        T.open_app(name)
    return f"Opening {name}, sir."


@intent(r"^(?:close|quit|exit|kill|terminate) (?:the |my )?(?P<name>.+?)(?: app| application| program)?$")
def close_something(m, ask):
    name = m["name"].strip()
    if name in {"computer", "pc", "laptop", "system", "windows"}:
        return "To switch the computer off, say shut down the computer, sir."
    T.close_app(name)
    return f"Closed {name}, sir."


# ---------------------------------------------------------------- knowledge (last, as it matches broad questions)

@intent(r"^(?:search )?(?:on )?wikipedia(?: for| about)? (?P<q>.+)$",
        r"^(?:tell me|what do you know|teach me) about (?P<q>.+)$", r"^define (?P<q>.+)$",
        r"^what does (?P<q>.+) mean$", r"^(?:who|what) (?:is|are|was|were) (?:a |an |the )?(?P<q>.+)$",
        r"^(?:where|when) (?:is|was|are|were|did) (?P<q>.+)$")
def knowledge(m, ask):
    if not re.match(r"^(?:search )?(?:on )?wikipedia", m.string):       # an explicit "wikipedia ..." still goes to Wikipedia
        if ChatBrain.available():                       # the chat model explains far better than a Wikipedia summary, and
            return None                                 # MainCode speaks its answer sentence by sentence as it arrives
        if FreeBrain.available():
            reply = FreeBrain.ask_model(original() or m.string)
            if reply:
                return reply
    try:
        return _sentences(T.search_wikipedia(m["q"]))
    except ToolError as not_on_wikipedia:
        if config.WOLFRAM_APP_ID:                       # Wolfram Alpha answers many things Wikipedia has no page for
            try:
                return T.ask_wolfram_alpha(m.string)
            except ToolError:
                pass
        raise not_on_wikipedia


# ---------------------------------------------------------------- bare words, and "did you mean"

BARE_WORDS = {
    "notes": "show my notes", "note": "show my notes", "my notes": "show my notes",
    "to do": "what's on my to do list", "todo": "what's on my to do list", "to do list": "what's on my to do list",
    "tasks": "what's on my to do list", "task list": "what's on my to do list",
    "reminders": "what's on my to do list", "screenshot": "take a screenshot", "weather": "what's the weather",
    "time": "what time is it", "date": "what's the date", "joke": "tell me a joke", "battery": "how is the battery",
    "volume up": "volume up", "volume down": "volume down", "mute": "mute",
}
_LEADING = re.compile(r"^(?:(?:open|launch|start|run|show|display|use|see|check|view|read|go to|bring up|give me|tell me)\s+)+"
                      r"(?:(?:me|the|my|a|your|jarvis)\s+)*")
_TRAILING = re.compile(r"(?:\s+(?:app|application|program|window|please|now))+$")

EXAMPLES = [
    "open calculator", "open calendar", "open currency converter", "open chrome", "open downloads", "open drive d",
    "show my notes", "take a note that buy milk", "read my last note", "add buy bread to my to do list",
    "what's on my to do list", "remind me in 10 minutes to drink water", "what's on my time table",
    "what time is it", "what's the weather in London", "bitcoin price", "100 dollars in rupees", "tell me a joke",
    "translate good morning to Urdu", "who is Alan Turing", "play despacito", "volume up", "take a screenshot",
    "how much RAM do I have", "NASA picture of the day", "where is the ISS", "tell me about Jupiter",
    "send an email", "shut down the computer", "generate a password", "show Lahore on the map",
    "business names for coffee shop", "COVID cases in Pakistan", "what can you do",
    "convert 5 miles to kilometres", "how many feet in a mile",
    "remember that my sister's birthday is in March", "what do you remember about me", "open the system calendar",
    "how is my PC doing", "schedule buy bread for tomorrow", "what's on my to do list for tomorrow", "open my latest note",
    "where are my screenshots saved", "is it AM or PM", "cube root of 27",
]


OPEN_MEANS_OPEN = {"note", "notes", "my notes", "screenshot"}


def _canonical(text):
    """"jarvis calculator" style bare words, with or without open/show/the/app, become a full command."""
    core = _TRAILING.sub("", _LEADING.sub("", text)).strip()
    if core in OPEN_MEANS_OPEN and re.match(r"(?:open|launch|start|run)\b", text):
        return text                                # "open the screenshot" is not "take a screenshot", nor "open the note" "show my notes"
    return BARE_WORDS.get(core, text)


def suggest(query, count=3):
    """The example commands closest to what was said, for a "did you mean" reply."""
    text = normalize(query)
    words = set(re.findall(r"[a-z]{3,}", text))
    scored = []
    for example in EXAMPLES:
        overlap = len(words & set(re.findall(r"[a-z]{3,}", example.lower())))
        ratio = difflib.SequenceMatcher(None, text, example.lower()).ratio()
        if overlap or ratio > 0.55:
            scored.append((overlap + ratio, example))
    return [example for _, example in sorted(scored, reverse=True)[:count]]


SESSION_WORDS = re.compile(r"(?:go to |take a |you can )?(?:sleep|rest)(?: mode)?(?: now)?|(?:quit|exit|terminate|good ?bye|bye)(?: jarvis)?|"
                           r"(?:start (?:a )?)?(?:new|fresh) (?:chat|conversation)|start over")           # MainCode handles these itself
COMMAND_JOINERS = re.compile(r"\s*,?\s*\b(?:and then|and after that|after that|then)\b\s*,?\s*", re.I)


def understands(text):
    """True if one of the command patterns (not the catch-all question one) matches the text. It tells a real "do this, then
    that" from a sentence that merely has "then" in it."""
    wording = _canonical(normalize(text))
    return bool(wording) and not EXPLANATION.match(wording) and (bool(SESSION_WORDS.fullmatch(wording))
                              or any(pattern.search(wording) for pattern, handler in INTENTS if handler is not knowledge))


def split_commands(text):
    """"schedule buy bread then what's on my list" as two commands, but only when every piece is one Jarvis understands;
    otherwise the text stays whole (so "tell me what happens then" is still one question)."""
    pieces = [piece.strip() for piece in COMMAND_JOINERS.split(text) if piece.strip()]
    return pieces if len(pieces) > 1 and all(understands(piece) for piece in pieces) else [text]


# Explaining something is for the chat brain, however many command words are in the question: "what is a screenshot" must not take
# one, "how does a battery work" is not a battery report, and "what is the difference between a comet and an asteroid" is not an
# asteroid report.
EXPLANATION = re.compile(
    r"^(?:(?:what(?:'s| is| are) )?(?:the )?differences? between\b"
    r"|explain\b"
    r"|why (?:do|does|did|is) "
    r"|why are (?:the|people|some|most|there|all|many) "
    r"|how (?:do|does) .+ works?$"
    r"|what (?:is|are) (?:a|an) \w"
    r"|what (?:do|does) (?:a|an|the) \w+ (?:do|mean)\b"
    r"|how (?:do|can|should) i (?:take|make|get|install|fix|stop|learn|find|change|reset|update|speed|clear|free|connect|check|add|create|use|set)\b)")
DAY_WORDS = re.compile(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")


def _guessed_command(guess, text):
    """The command to run for the language model's guess, with the detail the model can't carry: the place for the weather,
    the day for the to do list."""
    if guess.family == "weather" and _place(text):
        return f"{guess.command} in {_place(text)}"
    day = DAY_WORDS.search(text)
    if guess.family == "list_tasks" and day:
        return f"{guess.command} for {day.group(1)}"
    return guess.command


def _by_the_language_model(text, ask):
    """The second chance for a sentence no pattern understood: the model Jarvis trained on this PC (NLU.py) guesses what was
    meant and, when it is sure, the plain command it stands for is run. Awkward-to-undo commands are checked with you first."""
    if ChatBrain.is_fragment(ChatBrain.clean_question(text)):       # "can you", "the square root of": cut off, nothing to read
        return None
    guess = NLU.interpret(text)
    if guess is None:
        return None
    command = _guessed_command(guess, text)
    print(f": (language model: understood {text!r} as {command!r}, {guess.confidence:.0%} sure)")
    if guess.ask and not _confirmed(ask, guess.ask):
        return "Okay sir, I won't."
    return LocalReply(command, ask, guessed=True)


ANOTHER = re.compile(r"(?:^|\b)(?:another|one more)(?: one)?$")
_last_fun = [""]                                        # the last joke, fact, advice, activity or dog request, for "another"


def LocalReply(query, ask=lambda question: "", guessed=False):
    """Return the reply for a command, or None if it wasn't understood. ``guessed`` is set when the command is the language
    model's rewrite of what was said, so a rewrite that no pattern understands cannot be rewritten again."""
    _context.query = query
    text = normalize(query)
    if not text or EXPLANATION.match(text):
        return None                                      # (an explanation is for the chat brain, whatever words are in it)
    text = _canonical(text)
    if ANOTHER.search(text) and _last_fun[0]:
        text = _last_fun[0]                              # "another", "that's not funny, another one": the same kind again
    for pattern, handler in INTENTS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            reply = handler(match, ask)
            if reply is not None and handler in (joke, random_fact, bored, advice, dog):
                _last_fun[0] = text
        except ToolError as e:
            return str(e)
        except Exception:
            traceback.print_exc()                       # show the real problem instead of hiding it
            return "Sorry sir, that didn't work. The details are in the window."
        if reply is not None:
            return reply
    return None if guessed else _by_the_language_model(text, ask)
