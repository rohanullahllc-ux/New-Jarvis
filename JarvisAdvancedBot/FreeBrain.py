"""Answers anything LocalBrain has no pattern for, without any paid service.

LocalBrain is a list of command patterns; it cannot chat or explain. This is the layer behind it:

1. A free AI model, if one is set up in .env. Any OpenAI-compatible service works. Groq, Google Gemini and
   OpenRouter all give out free keys without a card (paste it as LLM_API_KEY and Jarvis recognises which
   service it belongs to), and Ollama runs a small model on this PC with no account at all.
2. Otherwise a free web answer (DuckDuckGo's instant answers), which covers facts and definitions.

Both return None when they have nothing, so the caller can fall back to suggestions.
"""
import collections
import datetime
import re

import requests

import config

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
    "ollama": (config.OLLAMA_URL.rstrip("/") + "/v1", "qwen2.5:3b"),
}
KEY_PREFIXES = (("gsk_", "groq"), ("AIza", "gemini"), ("sk-or-", "openrouter"))
TIMEOUT = 40
MAX_REPLY_CHARS = 700

_history = collections.deque(maxlen=8)          # the last few questions and answers, so follow-ups make sense
_warned = set()


def _provider():
    """(name, base url, model, key) of the AI service to use, or None."""
    name, key = config.LLM_PROVIDER, config.LLM_API_KEY
    if name in ("", "auto"):
        name = next((guess for prefix, guess in KEY_PREFIXES if key.startswith(prefix)), "" if key else "ollama")
    if name == "custom":
        return (name, config.LLM_BASE_URL, config.LLM_MODEL, key) if config.LLM_BASE_URL and config.LLM_MODEL else None
    if name not in PROVIDERS:
        return None
    base, model = PROVIDERS[name]
    if name != "ollama" and not key:
        return None
    return name, config.LLM_BASE_URL or base, config.LLM_MODEL or model, key


def _system_prompt():
    now = datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    return (f"You are Jarvis, a witty, loyal voice assistant on {config.USER_NAME}'s Windows PC. Your reply is spoken aloud: "
            "answer in one to three short sentences of plain speech, with no markdown, lists, emojis or links. "
            f"Now it is {now}. The user lives in {config.DEFAULT_CITY}. If you do not know something, say so briefly "
            "instead of guessing. You cannot control the PC yourself; other parts of Jarvis do that.")


def _clean(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)            # reasoning models show their thinking
    text = re.sub(r"[*_#`>]+", "", text)
    text = " ".join(text.split())
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return text


def available():
    """True if an AI service is configured (Ollama counts only if it is actually running)."""
    found = _provider()
    if found is None:
        return False
    if found[0] == "ollama":
        try:
            return requests.get(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=1.5).ok
        except requests.RequestException:
            return False
    return True


def _note_once(problem):
    if problem not in _warned:
        _warned.add(problem)
        print(f": (the free AI brain: {problem})")


def ask_model(question):
    """The AI model's answer, or None if none is set up or it failed (the reason is printed once)."""
    found = _provider()
    if found is None or (found[0] == "ollama" and not available()):
        return None
    name, base, model, key = found
    messages = [{"role": "system", "content": _system_prompt()}, *_history, {"role": "user", "content": question}]
    try:
        response = requests.post(base.rstrip("/") + "/chat/completions", timeout=TIMEOUT, json={
            "model": model, "messages": messages, "max_tokens": 300, "temperature": 0.6,
        }, headers={"Authorization": f"Bearer {key}"} if key else {})
    except requests.RequestException:
        _note_once(f"I couldn't reach {name}. Check the internet connection.")
        return None
    if response.status_code == 429:
        _note_once(f"{name} says I've used up its free limit for now.")
        return None
    if response.status_code in (401, 403):
        _note_once(f"{name} rejected the key in LLM_API_KEY.")
        return None
    if response.status_code == 404 and name == "ollama":
        _note_once(f"Ollama doesn't have the model {model}. Run:  ollama pull {model}")
        return None
    if not response.ok:
        _note_once(f"{name} had a problem (error {response.status_code}).")
        return None
    try:
        answer = _clean(response.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError):
        _note_once(f"{name} sent an answer I couldn't read.")
        return None
    if answer:
        _history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
    return answer or None


def web_answer(question):
    """A short factual answer from DuckDuckGo's free instant-answer service, or None."""
    topic = re.sub(r"^(?:what|who|where|when|why|how)(?:'s| is| are| was| were| does| do| did)?\s+(?:a |an |the )?", "", question.strip(), flags=re.I)
    try:
        data = requests.get("https://api.duckduckgo.com/", timeout=10, headers=config_headers(),
                            params={"q": topic or question, "format": "json", "no_html": 1, "skip_disambig": 1}).json()
    except (requests.RequestException, ValueError):
        return None
    text = data.get("Answer") or data.get("AbstractText") or data.get("Definition") or ""
    text = _clean(text if isinstance(text, str) else "")
    return " ".join(re.split(r"(?<=[.!?])\s+", text)[:2]) or None


def config_headers():
    return {"User-Agent": "JarvisAssistant/2.0 (personal voice assistant)"}


def answer(question):
    """Best free answer to anything: the AI model if there is one, else a web answer, else None."""
    return ask_model(question) or web_answer(question)


def forget():
    _history.clear()
