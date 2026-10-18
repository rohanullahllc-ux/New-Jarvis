"""Understands loosely worded commands with a small model that was trained on this PC.

LocalBrain's patterns catch the usual ways of saying a command. This is the second chance for everything they miss: the model
(models/nlu.joblib, made by ``python training/train_nlu.py``) guesses which kind of request a sentence is. When it is sure, the
sentence is rewritten into the plain command LocalBrain already understands, so "yo what's the time" runs as "what time is it".
When it is not sure, or thinks the sentence is only chat, nothing happens and the AI model answers as it always did.

Without a trained model file this module does nothing, so Jarvis works exactly as before.
"""
import threading
from typing import NamedTuple, Optional

import config

MODEL_FILE = config.BASE_DIR / "models" / "nlu.joblib"
CHAT = "chat"                              # the kind of sentence that is not a command at all


class Family(NamedTuple):
    command: str                           # a plain command that LocalBrain's patterns already understand
    ask: str = ""                          # when set, Jarvis asks this first: acting on a wrong guess would be a nuisance


# The kinds of request the model tells apart. The name is also the heading in training/nlu/*.txt where its phrases are listed.
# Shutting down or restarting needs no question here: the command asks "Are you sure?" itself.
FAMILIES = {
    "greet": Family("hello"), "how_are_you": Family("how are you"), "thanks": Family("thank you"),
    "who_are_you": Family("who are you"), "my_name": Family("what is my name"), "help": Family("what can you do"),
    "time": Family("what time is it"), "date": Family("what's the date"), "am_pm": Family("am or pm"),
    "list_tasks": Family("what's on my to do list"), "timetable": Family("what's on my time table"),
    "take_note": Family("take a note"), "read_notes": Family("show my notes"), "open_note": Family("open the note"),
    "recall_facts": Family("what do you remember about me"),
    "forget_facts": Family("forget my facts", "Did you want me to forget everything you asked me to remember? Say yes or no."),
    "screenshot": Family("take a screenshot"), "find_screenshots": Family("where are my screenshots saved"),
    "volume_up": Family("volume up"), "volume_down": Family("volume down"), "mute": Family("mute"),
    "play_pause": Family("pause the music"), "next_track": Family("next song"), "previous_track": Family("previous song"),
    "battery": Family("how is the battery"), "cpu": Family("how is the cpu"), "ram": Family("how much ram do i have"),
    "disk": Family("disk space"), "network": Family("what is my ip address"), "pc_status": Family("how is my pc doing"),
    "open_calculator": Family("open calculator"), "system_calculator": Family("system calculator"),
    "open_calendar": Family("open calendar"), "system_calendar": Family("system calendar"),
    "open_currency": Family("open currency converter"),
    "open_downloads": Family("open downloads"), "open_desktop": Family("open desktop"), "open_documents": Family("open documents"),
    "open_pictures": Family("open pictures"), "open_music": Family("open music folder"), "open_videos": Family("open videos folder"),
    "weather": Family("what's the weather"), "location": Family("where am i"), "iss": Family("where is the iss"),
    "starlink": Family("how many starlink satellites"), "next_launch": Family("next spacex launch"),
    "last_launch": Family("latest spacex launches"), "asteroids": Family("asteroids this week"),
    "nasa_picture": Family("nasa picture of the day"), "mars_photos": Family("show me mars photos"),
    "joke": Family("tell me a joke"), "fact": Family("random fact"), "bored": Family("i'm bored"),
    "advice": Family("give me some advice"), "dog": Family("show me a dog picture"),
    "email": Family("send an email", "Did you want to send an email? Say yes or no."),
    "shutdown": Family("shut down the computer"), "restart": Family("restart the computer"),
    "lock_screen": Family("lock the screen", "Did you want me to lock the screen? Say yes or no."),
}

THRESHOLD = 0.80                           # used when the model file does not say; train_nlu.py stores the one it measured
MARGIN = 0.30                              # the best guess must also beat the runner-up by this much


class Guess(NamedTuple):
    family: str
    command: str
    confidence: float
    ask: str


_lock = threading.Lock()
_bundle = None                             # the loaded model; False once loading has failed (so it is not retried every sentence)


def available():
    return config.LANGUAGE_MODEL and MODEL_FILE.is_file()


def _load():
    global _bundle
    with _lock:
        if _bundle is None:
            _bundle = False
            if available():
                try:
                    import joblib
                    loaded = joblib.load(MODEL_FILE)
                    if isinstance(loaded, dict) and "pipeline" in loaded:
                        _bundle = loaded
                except Exception as error:                  # noqa: BLE001 - a damaged or old file just switches the feature off
                    print(f"(the language model {MODEL_FILE.name} could not be loaded: {error}. "
                          "Run python training/train_nlu.py to make a new one.)")
        return _bundle or None


def warm_up():
    """Load the model in the background, so the first sentence it has to judge is not held up by the import."""
    if available():
        threading.Thread(target=_load, daemon=True).start()


def reset():
    """Forget the loaded model (after training a new one, and for tests)."""
    global _bundle
    with _lock:
        _bundle = None


def rank(text, count=3):
    """The model's best guesses for ``text`` as [(family, probability)], highest first; [] when there is no model."""
    bundle = _load() if config.LANGUAGE_MODEL else None
    if bundle is None or not text.strip():
        return []
    pipeline = bundle["pipeline"]
    probabilities = pipeline.predict_proba([text])[0]
    ordered = sorted(zip(pipeline.classes_, probabilities), key=lambda pair: pair[1], reverse=True)
    return [(str(name), float(value)) for name, value in ordered[:count]]


def interpret(text) -> Optional[Guess]:
    """What the sentence is asking for, if the model is sure: a Guess with the command to run. None when it is not sure, when
    it thinks the sentence is chat, or when there is no trained model."""
    best = rank(text, 2)
    if not best:
        return None
    family, confidence = best[0]
    bundle = _load()
    runner_up = best[1][1] if len(best) > 1 else 0.0
    if (family == CHAT or family not in FAMILIES or confidence < bundle.get("threshold", THRESHOLD)
            or confidence - runner_up < bundle.get("margin", MARGIN)):
        return None
    wanted = FAMILIES[family]
    return Guess(family, wanted.command, confidence, wanted.ask)
