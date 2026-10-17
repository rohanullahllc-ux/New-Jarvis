"""The one place Jarvis speaks.

Replaces the eight copy-pasted Speak() functions the project used to have. Every module
that wants to say something imports it from here:

    from speech import Speak
    Speak("Good morning, sir.")

* The text is always printed, so the program is fully usable with the sound off.
* TTS_ENABLED=false in .env turns the voice off entirely (each spoken sentence otherwise
  takes 2-3 seconds, which is most of what makes a long reply feel slow).
* A broken or missing Windows voice never crashes a session: the text is still shown.
* Every thread gets its own speech engine, because Windows' SAPI voices are COM objects
  that must not be shared across threads (the GUI speaks from a worker thread).
"""
import threading

from config import TTS_ENABLED, TTS_VOICE

_local = threading.local()
_listeners = []          # extra places a reply should appear, e.g. the GUI's conversation pane
_say_lock = threading.Lock()


def add_listener(callback):
    """Call ``callback(text)`` for every spoken line (the GUI uses this to show replies)."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback):
    if callback in _listeners:
        _listeners.remove(callback)


def _engine():
    engine = getattr(_local, "engine", None)
    if engine is None:
        from pyttsx3.engine import Engine       # a fresh engine for this thread (pyttsx3.init() would share one)
        engine = Engine("sapi5")
        voices = engine.getProperty("voices") or []
        chosen = next((v for v in voices if TTS_VOICE and TTS_VOICE.lower() in (v.name or "").lower()), None)
        if chosen is None and voices:
            chosen = voices[0]
        if chosen is not None:
            engine.setProperty("voice", chosen.id)
        _local.engine = engine
    return engine


def _say(text):
    try:
        with _say_lock:
            engine = _engine()
            engine.setProperty("rate", 200 if len(text) > 30 else 170)
            engine.say(text)
            engine.runAndWait()
    except Exception as e:
        _local.engine = None                    # start fresh next time rather than reusing a broken engine
        print(f": (the voice is unavailable - {e}; carrying on in text)")


def Speak(text):
    """Show `text`, pass it to any listeners, and say it aloud unless the voice is switched off."""
    text = str(text).strip()
    if not text:
        return
    print(f"\nA.I : {text}\n")
    for callback in list(_listeners):
        try:
            callback(text)
        except Exception as e:                  # a faulty listener must never stop Jarvis talking
            print(f": (output listener failed - {e})")
    if TTS_ENABLED:
        _say(text)
