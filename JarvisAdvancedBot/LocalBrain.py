"""Jarvis's free brain: understands everyday commands without any AI service.

What you say is matched against the patterns below, in order. The first handler
that understands it runs one of the tools in tools.py and returns the sentence
for Jarvis to speak. LocalReply returns None when nothing matches, so MainCode
can fall back to its older keyword commands.
"""
import ast
import datetime
import math
import operator
import random
import re

import requests
from anthropic.lib.tools import ToolError

from config import DEFAULT_CITY
from JarvisAdvancedBot import tools as T

LOCAL_CURRENCY = "PKR"
INTENTS = []


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


@intent(r"^(?:what can you do|help|what are your (?:features|skills|commands))")
def help_me(m, ask):
    return ("I can tell you the time, the weather, crypto prices and exchange rates, do maths, look things up on "
            "Wikipedia, translate, open apps and websites, play YouTube, control music and volume, take notes, "
            "keep your to-do list, set reminders and timers, take screenshots and check your battery.")


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
        return found.group(1)
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
        answer = ask("When should it go off? For example, in ten minutes, or at seven thirty p m.")
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
    task = m["task"].strip() or ask("What's the task?")
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


# ---------------------------------------------------------------- notes, password, jokes, screenshot

NOTE_START = r"^(?:(?:take|make|write|save|create)(?: a| me a)? note|note (?:that|down)|remember that)"


@intent(NOTE_START)
def take_note(m, ask):
    text = re.sub(NOTE_START + r"(?: that| saying| of| about)?[:,]?\s*", "", m.string).strip()
    text = text or ask("What should the note say?")
    return T.take_note(text) + "." if text else "Okay, no note then."


@intent(r"\b(?:read|show|list|open|what are)(?: me)?(?: all)? (?:my |the )?notes?\b")
def read_notes(m, ask):
    title = re.sub(r".*?\bnotes?\b(?: (?:about|called|named|on))?\s*", "", m.string, count=1).strip()
    return _sentences(T.read_notes(title), 4)


@intent(r"\b(?:generate|create|make|give me|new|random|strong)\b.*\bpassword\b")
def password(m, ask):
    length = re.search(r"(\d+)\s*(?:characters?|chars?|letters?|digits?|long)", m.string)
    return T.generate_password(int(length.group(1)) if length else 16)


OFFLINE_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why did the computer go to the doctor? It had a virus.",
]


@intent(r"\bjokes?\b", r"\bmake me laugh\b")
def joke(m, ask):
    try:
        return requests.get("https://icanhazdadjoke.com/", headers={"Accept": "application/json"}, timeout=8).json()["joke"]
    except Exception:
        return random.choice(OFFLINE_JOKES)


@intent(r"\b(?:screenshot|screen shot|capture (?:the |my )?screen)\b")
def screenshot(m, ask):
    return T.take_screenshot() + "."


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
    (T.browser_action, [
        (r"\bnew tab\b", "new_tab"), (r"\b(?:reopen|restore) (?:the )?(?:closed |last )?tab\b", "reopen_closed_tab"),
        (r"\bclose (?:this |the )?tab\b", "close_tab"), (r"\bnext tab\b", "next_tab"),
        (r"\bprevious tab\b", "previous_tab"), (r"\bincognito\b", "incognito_window"),
        (r"\bnew (?:browser )?window\b", "new_window"), (r"\b(?:browser |browsing )?history\b", "history"),
        (r"\b(?:show |open )?(?:my )?downloads\b", "downloads"), (r"\bbookmark\b", "bookmark_page"),
        (r"^(?:refresh|reload)(?: the| this)?(?: page)?$", "refresh"), (r"\bzoom in\b", "zoom_in"),
        (r"\bzoom out\b", "zoom_out"), (r"\breset (?:the )?zoom\b", "reset_zoom"),
    ]),
    (T.windows_action, [
        (r"\b(?:show (?:the )?desktop|home screen|minimi[sz]e (?:all|everything))\b", "show_desktop"),
        (r"\brestore (?:all )?windows\b", "restore_windows"),
        (r"\block (?:the |my )?(?:screen|pc|computer|laptop)\b", "lock_screen"),
        (r"^(?:open )?(?:windows |the |my )?settings$", "open_settings"),
        (r"\b(?:file explorer|my files|this pc)\b", "file_explorer"),
        (r"\b(?:task view|show all windows)\b", "task_view"), (r"\bswitch (?:the )?windows?\b", "switch_window"),
        (r"\b(?:snip|snipping|screen snip)\b", "snip_screen"),
        (r"\b(?:action center|notification center|notifications)\b", "action_center"),
        (r"\b(?:new|add a|add) (?:virtual )?desktop\b", "new_virtual_desktop"),
        (r"\bnext desktop\b", "next_virtual_desktop"), (r"\bprevious desktop\b", "previous_virtual_desktop"),
        (r"\bclose (?:this |the )?(?:virtual )?desktop\b", "close_virtual_desktop"),
        (r"\bstart menu\b", "start_menu"),
    ]),
    (T.youtube_control, [
        (r"\bfull ?screen\b", "fullscreen"), (r"\btheat(?:er|re) mode\b", "theater_mode"),
        (r"\b(?:skip|forward|fast forward)(?: by)? (?:10|ten) seconds\b", "forward_10_seconds"),
        (r"\b(?:go back|rewind|back)(?: by)? (?:10|ten) seconds\b", "back_10_seconds"),
        (r"\b(?:captions|subtitles)\b", "captions"), (r"\b(?:speed up|play faster)\b", "faster"),
        (r"\b(?:slow down|play slower)\b", "slower"),
    ]),
]

def _press(tool, *args):
    tool(*args)
    return "Done, sir."


for tool, phrases in KEY_COMMANDS:
    for pattern, action in phrases:
        intent(pattern)(lambda m, ask, tool=tool, action=action: _press(tool, action))

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
    intent(pattern)(lambda m, ask, action=action, times=times: _press(T.media_control, action, times))


@intent(r"^play (?P<q>.+?)(?: on youtube)?$")
def youtube_play(m, ask):
    return T.youtube(m["q"]) + "."


# ---------------------------------------------------------------- maths

OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}

MATH_WORDS = [
    (r"(?<=\d),(?=\d{3})", ""), (r"(\d+(?:\.\d+)?)\s*(?:%|percent) of\b", r"(\1/100)*"),
    (r"(\d+(?:\.\d+)?)\s*(?:%|percent)", r"(\1/100)"), (r"\bsquare root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)"),
    (r"\bmultiplied by\b|\btimes\b|\binto\b|×|\bx\b", "*"), (r"\bdivided by\b|\bover\b|÷", "/"),
    (r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\bto the power of\b|\bpower\b|\^", "**"),
    (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"),
]


def _evaluate(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "sqrt" and len(node.args) == 1:
        return math.sqrt(_evaluate(node.args[0]))
    raise ValueError("not plain arithmetic")


@intent(r"^(?:calculate|compute|solve|what(?:'?s| is)|how much is)\s+(?P<expr>(?:square root of |-|\()?\d.*)$",
        r"^(?:what(?:'?s| is) )?(?:the )?(?P<expr>square root of \d.*)$",
        r"^(?P<expr>[\d(][\d\s.,+\-*/x×÷()^%]*[\d)%])$")
def calculate(m, ask):
    expr = m["expr"]
    for pattern, replacement in MATH_WORDS:
        expr = re.sub(pattern, replacement, expr)
    try:
        value = _evaluate(ast.parse(expr.strip(), mode="eval").body)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
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
    dst = CURRENCIES[groups["dst"]] if groups.get("dst") else (LOCAL_CURRENCY if src != LOCAL_CURRENCY else "USD")
    amount = float(groups["amount"].replace(",", "")) if groups.get("amount") else 1
    return T.convert_currency(amount, src, dst)


# ---------------------------------------------------------------- weather, location, PC

def _place(text):
    found = re.search(r"\b(?:in|at|for) ([a-z][a-z .'-]*?)(?: (?:today|tomorrow|tonight|right now|now|this week))?$", text)
    place = found.group(1).strip() if found else ""
    return "" if place in {"today", "tomorrow", "tonight", "now", "right now", "this week", "the week"} else place


@intent(r"\b(?:weather|temperature|forecast|how (?:hot|cold|warm) is it|is it (?:going to )?rain)")
def weather(m, ask):
    return T.weather_report(_place(m.string) or DEFAULT_CITY)


@intent(r"\bwhere am i\b", r"\b(?:my|current) location\b", r"\bwhich city am i in\b")
def location(m, ask):
    return T.get_my_location()


@intent(r"\b(?:battery|cpu|ram|memory usage|disk space|storage|system (?:status|info|information|details)"
        r"|pc status|computer status|uptime)\b")
def system_status(m, ask):
    battery = T.psutil.sensors_battery()
    if "battery" in m.string and battery:
        state = "charging" if battery.power_plugged else "not charging"
        return f"The battery is at {battery.percent:.0f} percent and {state}."
    return T.get_system_status() + "."


# ---------------------------------------------------------------- translation

LANGUAGES = {
    "urdu": "ur", "english": "en", "arabic": "ar", "hindi": "hi", "pashto": "ps", "punjabi": "pa", "persian": "fa",
    "farsi": "fa", "french": "fr", "spanish": "es", "german": "de", "chinese": "zh-CN", "turkish": "tr",
    "japanese": "ja", "korean": "ko", "russian": "ru", "italian": "it", "portuguese": "pt",
}
LANG = "|".join(LANGUAGES)
MYMEMORY_CODES = {
    "ur": "ur-PK", "en": "en-GB", "ar": "ar-SA", "hi": "hi-IN", "ps": "ps-AF", "pa": "pa-IN", "fa": "fa-IR",
    "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "tr": "tr-TR", "ja": "ja-JP", "ko": "ko-KR", "ru": "ru-RU",
    "it": "it-IT", "pt": "pt-PT",
}


@intent(rf"^translate (?P<text>.+?) (?:to|into|in) (?P<lang>{LANG})$", rf"^how do you say (?P<text>.+?) in (?P<lang>{LANG})$")
def translate(m, ask):
    from deep_translator import GoogleTranslator, MyMemoryTranslator
    target = LANGUAGES[m["lang"]]
    try:
        result = GoogleTranslator(source="auto", target=target).translate(m["text"])
    except Exception:  # Google's free endpoint sometimes rate-limits; MyMemory is a free backup
        source = "ur-PK" if target == "en" else "en-GB"
        result = MyMemoryTranslator(source=source, target=MYMEMORY_CODES.get(target, target)).translate(m["text"])
    print(f": Translation: {result}")
    language = m["lang"].title()
    if all(ord(c) < 0x0370 for c in result):  # Latin script, which the voice can read aloud
        return f"In {language}, that's: {result}"
    return f"I've written the {language} translation on the screen."


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


@intent(r"^(?:close|quit|exit|kill|terminate|shut down|shutdown) (?:the |my )?(?P<name>.+?)(?: app| application| program)?$")
def close_something(m, ask):
    name = m["name"].strip()
    if name in {"computer", "pc", "laptop", "system", "windows"}:
        return "I don't shut the computer down by voice, sir. Please do that from the Start menu."
    T.close_app(name)
    return f"Closed {name}, sir."


# ---------------------------------------------------------------- knowledge (last, as it matches broad questions)

@intent(r"^(?:search )?(?:on )?wikipedia(?: for| about)? (?P<q>.+)$",
        r"^(?:tell me|what do you know|teach me) about (?P<q>.+)$", r"^define (?P<q>.+)$",
        r"^what does (?P<q>.+) mean$", r"^(?:who|what) (?:is|are|was|were) (?:a |an |the )?(?P<q>.+)$",
        r"^(?:where|when) (?:is|was|are|were|did) (?P<q>.+)$")
def knowledge(m, ask):
    return _sentences(T.search_wikipedia(m["q"]))


def LocalReply(query, ask=lambda question: ""):
    """Return the reply for a command, or None if it wasn't understood."""
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
        except Exception as e:
            print(f": Command problem: {e}")
            return "Sorry sir, that didn't work."
        if reply is not None:
            return reply
    return None
