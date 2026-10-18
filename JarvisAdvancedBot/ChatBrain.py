"""Conversation: Jarvis chats with a free AI model that runs on this PC (Ollama).

LocalBrain understands commands; this answers everything else. It

* streams the model's answer, so Jarvis can start speaking after the first sentence instead of waiting for the whole
  reply (MainCode hands the sentences to speech.SpeakStream);
* remembers the conversation (the last CHAT_MEMORY_TURNS questions and answers) and the facts the user asked it to
  remember ("remember that my brother is Ali"), which live in DataBase/memory.json and survive a restart;
* looks facts up on the web first (DuckDuckGo, no key), because a small model invents what it doesn't know;
* picks the model itself: OLLAMA_MODEL if that is set, otherwise the biggest installed model that fits in the free RAM.

Everything here fails quietly into "no answer" (reply_sentences yields nothing), so the caller can fall back to
FreeBrain (a cloud key, a web answer) and then to suggestions. The only places anything is sent are the Ollama server
on this PC and, for factual questions, DuckDuckGo's search.
"""
import datetime
import json
import os
import re
import threading
import time

import psutil
import requests

import config
from JarvisAdvancedBot import FreeBrain

FACTS_FILE = config.DB_DIR / "memory.json"
MAX_FACTS = 40
MAX_FACT_CHARS = 200
WIKIPEDIA_TIMEOUT = 3                 # seconds
SEARCH_TIMEOUT = 5                    # seconds DuckDuckGo gets per request...
SEARCH_DEADLINE = 4                   # ...but the answer never waits longer than this for the whole search
SNIPPETS = 2
SNIPPET_CHARS = 220                   # a local model reads only ~50 words a second, so every extra word costs time
MAX_TOKENS = 220                      # a reply is meant to be a few sentences; this stops a rambling one
CONTEXT_TOKENS = 2048                 # a small context keeps the model's memory use down (about 235 MB less than 4096)
LONG_SENTENCE = 220                   # characters without a full stop after which speech starts anyway
EARLY_CHARS = 50                      # the first words are spoken at the first comma after this many characters
RAM_FACTOR, RAM_EXTRA = 1.25, 300e6   # a model needs about 1.25x its file size, plus some headroom, once it is answering

ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "inc", "ltd", "mt", "approx", "e.g", "i.e", "u.s", "u.k"}
STOP_WORDS = {"that", "my", "the", "a", "an", "is", "are", "was", "i", "me", "to", "of", "and", "about", "what", "you",
              "told", "said", "your", "our", "we", "it", "its", "who", "has", "have", "had"}

_lock = threading.RLock()
_history = []                          # [{"role": "user"/"assistant", "content": ...}], oldest first
_model = None                          # the model chosen for this run
_warned = set()
last_timing = ""                       # how long the latest answer took, for MainCode to print once the answer has been said
last_stats = {}                        # the same as numbers, for the conversation record


def _reset():
    """Forget everything held in memory (for tests); DataBase/memory.json is not touched."""
    global _model
    with _lock:
        _history.clear()
        _model = None
        _warned.clear()
        globals()["last_timing"] = ""
        globals()["last_stats"] = {}


def _base():
    return config.OLLAMA_URL.rstrip("/")


def _note_once(problem):
    if problem not in _warned:
        _warned.add(problem)
        print(f": (the chat brain: {problem})")


# ---------------------------------------------------------------- which model

def _installed():
    """(name, size in bytes) of every chat model Ollama has, biggest first. Empty if Ollama isn't running."""
    try:
        reply = requests.get(_base() + "/api/tags", timeout=1.5)
        reply.raise_for_status()
        models = [(m["name"], int(m.get("size", 0))) for m in reply.json().get("models", [])]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return []
    return sorted((m for m in models if "embed" not in m[0].lower()), key=lambda m: -m[1])


def _running():
    """{name: bytes of RAM} of the models Ollama has loaded right now."""
    try:
        reply = requests.get(_base() + "/api/ps", timeout=1.5)
        reply.raise_for_status()
        return {m["name"]: int(m.get("size", 0)) for m in reply.json().get("models", [])}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {}


def available():
    """True if a local chat model can answer: Ollama is running and has a model, and CHAT_ENGINE isn't "cloud"."""
    return config.CHAT_ENGINE != "cloud" and bool(_installed())


def choose_model():
    """The model to chat with, or None. With OLLAMA_MODEL=auto it is the biggest installed model that fits in the RAM that
    is free, or the smallest if none does, but never one bigger than CHAT_AUTO_MAX_MB: on this kind of PC a 3 billion
    parameter model takes 6 to 10 seconds to start speaking against 3 to 5 for a 1.5 billion one, which is too slow for
    a voice assistant, so a bigger model has to be asked for by name. The RAM a model Ollama has already loaded is holding
    counts as free (and that model counts as fitting), so a small model left loaded from earlier can't keep a bigger one
    from being chosen. The choice is made once per run, so it doesn't flip back and forth as the free RAM changes."""
    global _model
    if config.OLLAMA_MODEL.lower() not in ("", "auto"):
        return config.OLLAMA_MODEL
    with _lock:
        installed = _installed()
        if not installed:
            return None
        if _model in dict(installed):
            return _model
        loaded = _running()
        budget = psutil.virtual_memory().available + sum(loaded.values())
        quick = [m for m in installed if m[1] <= config.CHAT_AUTO_MAX_MB * 1e6] or installed[-1:]       # none small enough: the smallest
        fits = [m for m in quick if m[0] in loaded or m[1] * RAM_FACTOR + RAM_EXTRA <= budget]
        _model = (fits[0] if fits else quick[-1])[0]
        return _model


def is_loaded():
    """True if the chat model is already in RAM, so the next question won't have to wait for it to load."""
    model = choose_model()
    return bool(model) and model in _running()


def _client():
    import httpx
    import ollama
    return ollama.Client(host=config.OLLAMA_URL, timeout=httpx.Timeout(180.0, connect=3.0))   # a cold start can take a while


def warm_up():
    """Load the chat model into RAM now, so the first question doesn't wait for it. Never raises."""
    try:
        model = choose_model() if available() else None
        if model:
            _client().chat(model=model, messages=[], keep_alive=config.OLLAMA_KEEP_ALIVE)
    except Exception:                                   # noqa: BLE001 - it is only a head start
        pass


# ---------------------------------------------------------------- what Jarvis was asked to remember

def facts():
    """What the user asked Jarvis to remember, oldest first."""
    try:
        return [str(fact) for fact in json.loads(FACTS_FILE.read_text(encoding="utf-8"))["facts"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _save_facts(items):
    FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = FACTS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"facts": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, FACTS_FILE)


def remember(text):
    """Keep a fact for good. Returns the fact as stored, or "" if there was nothing worth keeping."""
    fact = " ".join(str(text).split()).strip(" .,;:!?")[:MAX_FACT_CHARS]
    if not fact:
        return ""
    with _lock:
        items = facts()
        if fact.lower() not in (item.lower() for item in items):
            _save_facts((items + [fact])[-MAX_FACTS:])
    return fact


def forget_facts(about=None):
    """Forget everything (about=None) or the facts that mention all the main words of ``about``. Returns how many went."""
    with _lock:
        items = facts()
        if about is None:
            keep = []
        else:
            wanted = set(re.findall(r"[a-z0-9']+", about.lower())) - STOP_WORDS
            keep = [item for item in items if not wanted or not wanted <= set(re.findall(r"[a-z0-9']+", item.lower()))]
        if len(keep) != len(items):
            _save_facts(keep)
        return len(items) - len(keep)


# ---------------------------------------------------------------- looking things up
# A small model invents facts it doesn't know, so a factual question is looked up first and the result goes into the
# prompt. Wikipedia answers in about a second; DuckDuckGo's search is slower and flaky, so it is only used for the news
# and "right now" questions Wikipedia can't answer, and never for longer than SEARCH_DEADLINE seconds.

_FACTUAL = re.compile(r"^(?:who|whom|whose|what|when|where|which|how (?:many|much|old|tall|long|far|big|fast|high|deep|large))\b"
                      r"|\b(?:latest|news|current|currently|today|tonight|yesterday|this (?:week|month|year)|price of|"
                      r"population|capital|president|prime minister|ceo of|founder of|height|distance|score|winner|"
                      r"released|release date|born|died|founded|invented|discovered)\b", re.I)
_CHATTY = re.compile(r"\b(?:you|your|yourself|yours|my|mine|me|myself|i|i'm|i've|i'd|we|our)\b|"
                     r"^(?:what's up|whats up|how are|how's it going|thanks|thank you|hello|hi|hey)\b|"
                     r"\b(?:joke|story|poem|song|advice|opinion|feel|feeling|think|recommend|suggest|write|compose|translate|"
                     r"summari[sz]e|explain|remember|forget)\b", re.I)
_CURRENT = re.compile(r"\b(?:latest|news|today|tonight|yesterday|this (?:week|month|year)|right now|currently|current|price|"
                      r"score|winner|results?|breaking|live)\b", re.I)
_FOLLOW_UP = re.compile(r"^(?:and|also|what about|how about)\b|\b(?:it|its|it's|he|his|she|her|they|their|them)\b", re.I)


def needs_search(question):
    """True for a factual question (who, when, how many, the latest...) that a small model might get wrong."""
    return config.CHAT_WEB_SEARCH and bool(_FACTUAL.search(question)) and not _CHATTY.search(question)


def _search_query(question):
    """The words to search for. A short follow-up ("and its population?") borrows the previous question's topic."""
    question = question.replace("?", " ")
    if len(question.split()) <= 6 and _FOLLOW_UP.search(question):
        previous = next((m["content"] for m in reversed(_recent()) if m["role"] == "user"), "")
        if previous:
            question = f"{previous.replace('?', ' ')} {question}"
    return " ".join(question.split())


def _wikipedia_snippets(query):
    """The opening of the best-matching Wikipedia pages, as "- Title: text" lines. One quick request."""
    try:
        reply = requests.get("https://en.wikipedia.org/w/api.php", timeout=WIKIPEDIA_TIMEOUT, headers=FreeBrain.config_headers(),
                             params={"action": "query", "generator": "search", "gsrsearch": query, "gsrlimit": SNIPPETS,
                                     "prop": "extracts", "exintro": 1, "explaintext": 1, "exsentences": 2,
                                     "exlimit": SNIPPETS, "format": "json"})
        reply.raise_for_status()
        pages = sorted(reply.json().get("query", {}).get("pages", {}).values(), key=lambda page: page.get("index", 99))
    except (requests.RequestException, ValueError, AttributeError):
        return []
    lines = []
    for page in pages:
        text = " ".join(str(page.get("extract", "")).split())
        if text:
            lines.append(f"- {page.get('title', '')}: {text[:SNIPPET_CHARS]}")
    return lines[:SNIPPETS]


def _search_snippets(query):
    """Web search results as "- Title: text" lines. It is slow and flaky, so it runs on its own thread with a deadline."""
    found = {}

    def search():
        try:
            from ddgs import DDGS
            found["results"] = DDGS(timeout=SEARCH_TIMEOUT).text(query, max_results=SNIPPETS + 2)
        except Exception as error:                      # noqa: BLE001 - whatever goes wrong, chat on without it
            found["error"] = error

    worker = threading.Thread(target=search, name="chat-search", daemon=True)
    worker.start()
    worker.join(SEARCH_DEADLINE)
    if "results" not in found:
        _note_once(f"the web search didn't work ({found['error']})" if "error" in found else
                   "the web search was too slow, so I answered without it")
        return []
    lines = []
    for result in found["results"] or []:
        body = " ".join(str(result.get("body", "")).split())
        if body:
            lines.append(f"- {str(result.get('title', '')).strip()}: {body[:SNIPPET_CHARS]}")
    return lines[:SNIPPETS]


def web_context(question):
    """Reference text about the question for the model to lean on, or "" (no lookup wanted, or nothing found)."""
    if not needs_search(question):
        return ""
    query = _search_query(question)
    lines = [] if _CURRENT.search(question) else _wikipedia_snippets(query)
    return "\n".join(lines or _search_snippets(query))


# ---------------------------------------------------------------- cutting the stream into sentences

_END = re.compile(r"[.!?]+[\"')\]]*(?=\s)|\n")


def split_sentences(text):
    """Cut ``text`` into (the complete sentences, the unfinished rest).

    A sentence ends at . ! or ? followed by a space, or at a line break. "Dr.", "3.14", a list number such as "1." at the
    start of a line and an initial such as "J." do not end one. The last sentence stays in the rest until a space or the end follows it.
    """
    sentences, start = [], 0
    for match in _END.finditer(text):
        if match.group(0) != "\n":
            words = text[start:match.start()].split()
            last = words[-1].lower().strip("\"'([") if words else ""
            if last in ABBREVIATIONS or (last.isdigit() and len(words) == 1) or re.fullmatch(r"[b-hj-z]", last):
                continue
        sentence = text[start:match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    return sentences, text[start:].lstrip()


def _cut_long(rest):
    """A reply with no full stop shouldn't keep Jarvis silent: split a long unfinished sentence at a comma or a space."""
    if len(rest) < LONG_SENTENCE:
        return "", rest
    cut = rest.rfind(", ", 80, LONG_SENTENCE)
    cut = cut if cut >= 0 else rest.rfind(" ", 80, LONG_SENTENCE)
    cut = cut if cut >= 0 else LONG_SENTENCE
    return rest[:cut + 1].strip(), rest[cut + 1:]


def _cut_early(rest):
    """Speech should start at the first natural pause, not at the end of a long first sentence: a small model on this PC
    writes about six words a second, so a 40-word opening sentence would otherwise keep Jarvis silent for seven seconds."""
    found = re.search(r"[,;:]\s", rest[EARLY_CHARS:])
    if not found:
        return "", rest
    cut = EARLY_CHARS + found.end()
    return rest[:cut].strip(), rest[cut:]


def _speakable(text):
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", text)              # list bullets and numbers
    return " ".join(text.split())


class _ThinkFilter:
    """Hides <think>...</think> (some models show their reasoning), even when a tag arrives split across two pieces."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.inside, self.held = False, ""

    def feed(self, text):
        self.held += text
        shown = ""
        while True:
            if self.inside:
                end = self.held.find(self.CLOSE)
                if end < 0:
                    self.held = self.held[-len(self.CLOSE):]            # it may hold the start of the closing tag
                    return shown
                self.held, self.inside = self.held[end + len(self.CLOSE):], False
                continue
            start = self.held.find(self.OPEN)
            if start >= 0:
                shown += self.held[:start]
                self.held, self.inside = self.held[start + len(self.OPEN):], True
                continue
            keep = next((n for n in range(min(len(self.OPEN) - 1, len(self.held)), 0, -1) if self.OPEN.startswith(self.held[-n:])), 0)
            shown += self.held[:len(self.held) - keep]
            self.held = self.held[len(self.held) - keep:]
            return shown

    def flush(self):
        rest, self.held = ("" if self.inside else self.held), ""
        return rest


# ---------------------------------------------------------------- the conversation

def _recent():
    with _lock:
        return list(_history)


def _remember_turn(question, answer):
    """Keep the turn. At the limit the oldest half goes in one go, not one pair per turn: Ollama keeps what it has already
    read of the start of the conversation, but only while that start doesn't change, and a history that slid along by a pair
    every turn made it re-read the whole conversation every time (10 to 12 seconds a reply instead of 3 to 5)."""
    with _lock:
        _history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
        if len(_history) > 2 * config.CHAT_MEMORY_TURNS:
            del _history[:-2 * max(1, config.CHAT_MEMORY_TURNS // 2)]


def forget():
    """Start a fresh conversation. What Jarvis was asked to remember stays."""
    with _lock:
        _history.clear()
    FreeBrain.forget()


def system_prompt():
    """FreeBrain's spoken-style prompt plus whatever the user asked Jarvis to remember. It only changes when the day or the
    remembered facts do, so Ollama can keep the part of it it has already read."""
    text = FreeBrain.system_prompt(with_time=False)
    known = facts()
    if known:
        text += " Things the user has told you to remember: " + "; ".join(known) + "."
    return text


_TIMEY = re.compile(r"\b(?:time|clock|am|pm|a\.m\.|p\.m\.|morning|afternoon|evening|night|tonight|today|tomorrow|yesterday|now|late|"
                    r"early|o'clock|hours?|minutes?|day|date|week|month|year)\b", re.I)


def _clock_note(question):
    """The time, for the questions that are about it: the model can't know it, and used to guess ("it's afternoon" at 7 PM).
    It goes at the end of the message, and only when it is needed, so the start of the conversation stays the same."""
    if not _TIMEY.search(question):
        return ""
    now = datetime.datetime.now()
    return f"\n(It is {now.strftime('%I:%M %p').lstrip('0')} on {now:%A %d %B %Y} right now.)"


def _user_message(question, context):
    if not context:
        return question + _clock_note(question)
    return f"Facts you can use:\n{context}\n\nQuestion: {question}{_clock_note(question)}"


_LEAD_FILLER = re.compile(r"^(?:(?:ok|okay|hey|um|uh|er|hmm|jarvis|assistant|sorry|i mean|no i mean|i told you)[,.]?\s+)+(?=\S)", re.I)
_LEAD_ONLY = re.compile(r"(?:(?:can|could|would|will) you(?: please)?|please|(?:tell|show) me(?: please)?|i mean|i need|i want|"
                        r"let me know|what is|what's|who is|how|why|when|where|do you|are you|ok|okay|hey|um|uh)", re.I)
_DANGLING = re.compile(r"\b(?:of|to|in|at|for|from|with|about|the|a|an|and|or|between|than|my|your|what's|whats)$", re.I)


def clean_question(text):
    """What was said without the throat-clearing in front of it ("ok, I mean ..."), which a small model takes literally
    (it once answered "ok how much is there distance" with an asteroid called 2019 OK)."""
    cleaned = _LEAD_FILLER.sub("", text.strip())
    return cleaned or text.strip()


def is_fragment(text):
    """True for something that was cut off ("can you", "tell me the square root of"). Asking a model to answer half a sentence
    only makes it invent something, so the caller asks the user to say it again instead."""
    words = re.sub(r"[^\w\s'-]", " ", text.lower()).split()
    if not words:
        return True
    phrase = " ".join(words)
    return bool(_LEAD_ONLY.fullmatch(phrase) or _DANGLING.search(phrase))


def _explain(error, model):
    """Say once, in plain words, what went wrong with the chat model."""
    global _model
    import httpx
    status = getattr(error, "status_code", None)
    if status == 404:
        _note_once(f"Ollama doesn't have the model {model}. Get it with:  ollama pull {model}")
        _model = None                                   # choose again next time
    elif isinstance(error, (ConnectionError, httpx.TransportError)):
        _note_once("I can't reach Ollama. Open it from the Start menu.")
    else:
        _note_once(f"the chat model had a problem ({type(error).__name__}: {error})")


def _model_text(model, messages, info):
    """The model's words, piece by piece. ``info`` collects why it stopped; trouble is reported once and ends the stream."""
    import httpx
    import ollama
    stream = None
    try:
        stream = _client().chat(model=model, messages=messages, stream=True, think=False, keep_alive=config.OLLAMA_KEEP_ALIVE,
                                options={"num_predict": MAX_TOKENS, "temperature": 0.6, "num_ctx": CONTEXT_TOKENS})
        for chunk in stream:
            info["reason"] = chunk.get("done_reason") or info.get("reason")
            piece = chunk["message"]["content"]
            if piece:
                yield piece
    except (ollama.ResponseError, httpx.HTTPError, ConnectionError, OSError) as error:
        info["failed"] = True
        _explain(error, model)
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()


def complete(system, user, max_tokens=160):
    """One quick answer from the local model, for a job like translating: no conversation, no memory, no lookup.
    Returns None when there is no model or it fails, so the caller can try something else."""
    model = choose_model() if available() else None
    if model is None:
        return None
    import httpx
    import ollama
    try:
        reply = _client().chat(model=model, think=False, keep_alive=config.OLLAMA_KEEP_ALIVE,
                               messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                               options={"temperature": 0, "num_predict": max_tokens, "num_ctx": 1024})
        return " ".join(str(reply["message"]["content"]).split()) or None
    except (ollama.ResponseError, httpx.HTTPError, ConnectionError, OSError) as error:
        _explain(error, model)
        return None


def reply_sentences(question):
    """The reply to ``question``, one sentence at a time, each yielded as soon as it is complete (so it can be spoken).

    Yields nothing if there is no model or it fails, so the caller can try something else.
    """
    model = choose_model() if config.CHAT_ENGINE != "cloud" else None
    if model is None:
        return
    started = time.perf_counter()
    question = clean_question(question)
    context = web_context(question)
    looked_up = time.perf_counter() - started
    # The history is always sent, even for a standalone fact: it makes each request begin like the last one, so Ollama keeps
    # what it has already read of it. Leaving it out for some questions made the next one re-read everything.
    messages = [{"role": "system", "content": system_prompt()}, *_recent(),
                {"role": "user", "content": _user_message(question, context)}]
    info, thinking, buffer, said, first = {}, _ThinkFilter(), "", [], None
    for piece in _model_text(model, messages, info):
        buffer += thinking.feed(piece)
        sentences, buffer = split_sentences(buffer)
        early, buffer = _cut_long(buffer)
        if not said and not sentences and not early:                       # nothing said yet: start at the first pause
            early, buffer = _cut_early(buffer)
        for sentence in sentences + ([early] if early else []):
            spoken = _speakable(sentence)
            if spoken:
                said.append(spoken)
                first = first or time.perf_counter() - started
                yield spoken
    buffer += thinking.flush()
    leftover = _speakable(buffer)
    cut_off = info.get("failed") or (info.get("reason") == "length" and said)
    if leftover and not cut_off:                                           # a reply cut off mid-sentence loses its fragment
        said.append(leftover)
        first = first or time.perf_counter() - started
        yield leftover
    if said:
        _remember_turn(question, " ".join(said))
        global last_timing, last_stats
        total = time.perf_counter() - started
        last_stats = {"model": model, "lookup": round(looked_up, 1), "first_words": round(first, 1), "total": round(total, 1)}
        last_timing = f": (chat: {model} - lookup {looked_up:.1f}s, first words after {first:.1f}s, whole answer {total:.1f}s)"
