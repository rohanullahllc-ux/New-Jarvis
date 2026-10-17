"""Jarvis's free brain: understands everyday commands without any AI service.

What you say is matched against the patterns below, in order. The first handler that understands it
runs one or more of the tools in JarvisAdvancedBot/tools and returns the sentence for Jarvis to speak.
LocalReply returns None when nothing matches, so the session can tell you it didn't understand.

ORDER MATTERS. A specific command must come before the broader one it would otherwise be mistaken
for ("open downloads" before "open <app>", "temperature of Mars" before "temperature" = weather), and
the Wikipedia catch-all stays last.
"""
import datetime
import random
import re
import threading
import traceback

import psutil
from anthropic.lib.tools import ToolError

import calc
import config
from config import DEFAULT_CITY, HOME_CURRENCY
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
    text = re.sub(r"^(?:hey|ok|okay)\s+(?=\w)", "", text.strip())
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


@intent(r"^(?:thanks|thank you|great|good job|well done|nice)\b")
def thanks(m, ask):
    return random.choice(["You're welcome, sir.", "Always a pleasure, sir.", "Happy to help."])


@intent(r"^(?:who are you|what(?:'s| is) your name|introduce yourself)")
def who_are_you(m, ask):
    return "I'm Jarvis, your personal assistant, back online and upgraded."


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
    return ("I can tell you the time, weather, crypto prices and exchange rates, do maths, look things up, translate, "
            "open apps, folders and websites, play YouTube, control music and volume, keep notes, a to-do list and your "
            "time table, set reminders, take screenshots, check your PC, show NASA photos, the space station and SpaceX "
            "launches, tell jokes and facts, send email, and shut the PC down when you confirm.")


# ---------------------------------------------------------------- time

@intent(r"\bwhat(?:'?s| is) the time\b", r"\bwhat time is it\b", r"\b(?:tell me the|current) time\b", r"^time$")
def time_now(m, ask):
    return "It's " + datetime.datetime.now().strftime("%I:%M %p").lstrip("0") + "."


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


@intent(rf"^(?:add|put|write) (?P<task>.+?) (?:to|on|in|into) (?:my |the )?{TODO}$",
        r"^(?:add|new|create) (?:a )?(?:new )?task(?: to do)?[:,]?\s*(?P<task>.*)$")
def add_task(m, ask):
    task = _as_typed(m["task"].strip()) or ask("What's the task?")
    return T.add_task(task) + "." if task else "Okay, nothing added."


@intent(rf"\b(?:what(?:'s| is)(?: on)?|show|read|list|tell me|check)\b.*\b{TODO}\b",
        rf"^(?:my )?{TODO}(?: for today)?$", r"\bwhat do i have to do\b")
def list_tasks(m, ask):
    return T.list_tasks()


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


@intent(r"^(?:what(?:'s| is)|show|check|tell me|read|open|display)\b.*\b(?:time ?table|schedule|routine)\b",
        r"^(?:my )?(?:time ?table|schedule|routine)$", r"\bwhat (?:should|do) i (?:be )?(?:doing|do) (?:now|right now|next)\b")
def timetable(m, ask):
    return T.get_timetable_block()


# ---------------------------------------------------------------- notes, password, jokes, screenshot

NOTE_START = r"^(?:(?:take|make|write|save|create)(?: a| me a)? note|note (?:that|down)|remember that)"


@intent(NOTE_START)
def take_note(m, ask):
    text = re.sub(NOTE_START + r"(?: that| saying| of| about)?[:,]?\s*", "", m.string).strip()
    text = _as_typed(text) or ask("What should the note say?")
    return T.take_note(text) + "." if text else "Okay, no note then."


@intent(r"\b(?:read|show|list|open|what are)(?: me)?(?: all)? (?:my |the )?notes?\b")
def read_notes(m, ask):
    title = re.sub(r".*?\bnotes?\b(?: (?:about|called|named|on))?\s*", "", m.string, count=1).strip()
    return _sentences(T.read_notes(title), 4)


@intent(r"\b(?:generate|create|make|give me|new|random|strong)\b.*\bpassword\b")
def password(m, ask):
    length = re.search(r"(\d+)\s*(?:characters?|chars?|letters?|digits?|long)", m.string)
    return T.generate_password(int(length.group(1)) if length else 16)


@intent(r"\bjokes?\b", r"\bmake me laugh\b")
def joke(m, ask):
    return T.get_joke()


@intent(r"\b(?:screenshot|screen shot|capture (?:the |my )?screen)\b")
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


@intent(r"^(?:open|launch|start|show)(?: me)? (?:the |my |a )?(?P<name>calculator|calendar|currency convert[eo]r)$")
def open_a_utility(m, ask):
    name = m["name"].replace(" ", "_").replace("convertor", "converter")
    try:
        T.open_utility_app(name)
    except ToolError:                                    # Jarvis's own window isn't installed: use Windows' or the web
        if name == "calculator":
            T.open_app("calculator")
        elif name == "calendar":
            T.open_website("https://calendar.google.com")
        else:
            raise
    return f"Opening the {m['name']}, sir."


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
        (r"\bnew (?:browser )?window\b", "new_window"), (r"\b(?:browser |browsing )?history\b", "history"),
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
    (r"\bmultiplied by\b|\btimes\b|\binto\b|×|\bx\b", "*"), (r"\bdivided by\b|\bover\b|÷", "/"),
    (r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\bto the power of\b|\bpower\b|\^", "**"),
    (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"),
]


@intent(r"^(?:calculate|compute|solve|what(?:'?s| is)|how much is)\s+(?P<expr>(?:square root of |-|\()?\d.*)$",
        r"^(?:what(?:'?s| is) )?(?:the )?(?P<expr>square root of \d.*)$",
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


@intent(r"\b(?:iss|international space station|space station)\b")
def space_station(m, ask):
    return T.get_iss_location()


@intent(r"\bstarlink\b")
def starlink(m, ask):
    _heads_up("Checking the Starlink satellite list, one moment.")
    return T.spacex_starlink_count()


@intent(r"\bnext\b.*\blaunch\b", r"\bupcoming\b.*\blaunch\b", r"\bspace ?x\b.*\b(?:next|upcoming)\b")
def next_launch(m, ask):
    return T.spacex_latest_launch("next")


@intent(r"\b(?:latest|last|recent|previous)\b.*\blaunch\b", r"\bspace ?x\b.*\b(?:latest|last|recent)\b")
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


@intent(r"\b(?:weather|temperature|forecast|how (?:hot|cold|warm) is it|is it (?:going to )?rain)")
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
        r"|windows version|operating system|computer name|specs|specifications)\b")
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
    print(f": Translation: {result}")
    language = m["lang"].title()
    if all(ord(c) < 0x0370 for c in result):  # Latin script, which the voice can read aloud
        return f"In {language}, that's: {result}"
    return f"I've written the {language} translation on the screen."


# ---------------------------------------------------------------- books, acronyms, folders, Wolfram Alpha

@intent(r"\bread (?:me )?page (?P<page>\d+)(?: (?:of|from) (?:the )?(?:book |pdf )?(?P<title>.+))?$",
        r"\bread (?:me )?(?:the |a |my )?(?:book|pdf)(?: (?P<title>.+?))?(?: page (?P<page>\d+))?$")
def read_book(m, ask):
    found = m.groupdict()
    page = int(found.get("page") or 1)
    text = T.read_book_page((found.get("title") or "").strip(), page)
    print(f": {text}")
    spoken = _sentences(text, 4)
    return spoken if spoken == text else spoken + " The rest of the page is on the screen."


@intent(r"\bacronym\b")
def acronym(m, ask):
    phrase = re.sub(r"^.*?\bacronym\b(?: (?:for|of|from))?\s*", "", m.string).strip() or ask("Which phrase?")
    return T.make_acronym(phrase) if phrase else "Okay, never mind."


@intent(r"^(?:create|make|new|add) (?:a |another )?(?:new )?folder(?: (?:named|called|with the name))?\s*"
        r"(?P<name>.*?)(?: (?:on|in|inside) (?:the |my )?(?P<where>desktop|documents|downloads|pictures|music|videos))?$")
def new_folder(m, ask):
    name = _as_typed(m["name"].strip()) or ask("What should the folder be called?")
    return T.create_folder(name, m["where"] or "documents") + "." if name else "Okay, no folder then."


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


@intent(r"\bwi-?fi\b.*\bpassword\b", r"\bpassword\b.*\bwi-?fi\b", r"\b(?:saved|known|stored|my) wi-?fi (?:networks|connections|names)\b")
def wifi(m, ask):
    found = re.search(r"\b(?:of|for)\s+(?:the |my )?(?:wi-?fi )?(?:network )?(?:named |called )?(.+?)(?: wi-?fi| network)?$", m.string)
    name = _as_typed(found.group(1)) if found else ""
    if not name:
        name = ask(T.get_saved_wifi_password("")).strip()          # lists the saved networks, then asks which
        if not name:
            return "Okay, never mind."
    return T.get_saved_wifi_password(name)


@intent(r"\bdownload\b.*\b(?:youtube|video|song|music|audio)\b", r"\b(?:youtube|video)\b.*\bdownload\b")
def youtube_download(m, ask):
    link = re.search(r"https?://\S+", original())
    if not link:
        link = re.search(r"https?://\S*youtu\S*", read_clipboard())            # a link the user just copied
    url = link.group(0) if link else ask("Please paste the YouTube link.").strip()
    if not url:
        return "Okay, I won't download anything."
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
    try:
        return _sentences(T.search_wikipedia(m["q"]))
    except ToolError as not_on_wikipedia:
        if config.WOLFRAM_APP_ID:                       # Wolfram Alpha answers many things Wikipedia has no page for
            try:
                return T.ask_wolfram_alpha(m.string)
            except ToolError:
                pass
        raise not_on_wikipedia


def LocalReply(query, ask=lambda question: ""):
    """Return the reply for a command, or None if it wasn't understood."""
    _context.query = query
    text = normalize(query)
    if not text:
        return None
    for pattern, handler in INTENTS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            reply = handler(match, ask)
        except ToolError as e:
            return str(e)
        except Exception:
            traceback.print_exc()                       # show the real problem instead of hiding it
            return "Sorry sir, that didn't work. The details are in the window."
        if reply is not None:
            return reply
    return None
