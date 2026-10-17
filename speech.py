"""The one place Jarvis speaks.

Every module that wants to say something imports it from here:

    from speech import Speak
    Speak("Good morning, sir.")

* The text is always printed, so the program is fully usable with the sound off.
* It speaks through Windows' own speech (SAPI) directly and waits until each sentence has been said. The
  pyttsx3 package used to do this, but its current version says the first sentence and then stays silent
  for every one after it, which is why Jarvis seemed to stop talking after the greeting.
* TTS_ENABLED=false in .env turns the voice off; TTS_VOICE, TTS_VOLUME and TTS_RATE tune it.
* A broken or missing Windows voice never crashes a session: the text is still shown, and the problem is
  reported once rather than on every sentence.
* Every thread gets its own voice, because SAPI voices are COM objects that must stay on the thread that
  made them (the window speaks from a worker thread, reminders from a timer thread).

Run `python speech.py` to check that Jarvis can speak.
"""
import sys
import threading
import time

from config import TTS_ENABLED, TTS_RATE, TTS_VOICE, TTS_VOLUME

_local = threading.local()
_listeners = []          # extra places a reply should appear, e.g. the GUI's conversation pane
_say_lock = threading.Lock()
_reported = set()        # voice problems already shown, so one broken voice doesn't repeat itself

CHECK_SENTENCES = ("Testing, one, two, three.", "This is the second sentence, to prove that Jarvis keeps on speaking.",
                   "And a third.")
CHECK_CHARACTERS_PER_SECOND = 25      # speech is slower than this, so a sentence that comes back faster was not spoken


def _show(line):
    """Print a line; characters the console can't display (Urdu on a cp1252 pane) become '?' instead of crashing."""
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding))


def add_listener(callback):
    """Call ``callback(text)`` for every spoken line (the GUI uses this to show replies)."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback):
    if callback in _listeners:
        _listeners.remove(callback)


def _create_voice():
    """A new Windows voice for the calling thread (kept in one place so tests can supply a stand-in)."""
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitialize()                 # COM has to be started on every thread that uses it
    except OSError:
        pass                                    # it already is on this one
    return comtypes.client.CreateObject("SAPI.SpVoice")


def _voice():
    voice = getattr(_local, "voice", None)
    if voice is None:
        voice = _create_voice()
        voice.Volume = max(0, min(100, TTS_VOLUME))
        if TTS_VOICE:
            wanted = TTS_VOICE.lower()
            chosen = next((token for token in voice.GetVoices() if wanted in (token.GetDescription() or "").lower()), None)
            if chosen is not None:
                voice.Voice = chosen            # otherwise the Windows default voice stays
        _local.voice = voice
    return voice


def _say(text):
    """Speak ``text`` and wait until it has been said. Returns False if the voice failed."""
    try:
        with _say_lock:
            voice = _voice()
            voice.Rate = max(-10, min(10, (2 if len(text) > 30 else 0) + TTS_RATE))     # long replies a little faster
            voice.Speak(text, 0)                # 0 = do not return until the whole sentence has been spoken
        return True
    except Exception as error:
        _local.voice = None                     # start fresh next time rather than reusing a broken voice
        problem = f"{type(error).__name__}: {error}"
        if problem not in _reported:
            _reported.add(problem)
            print(f": (the voice is unavailable - {error}; carrying on in text)")
        return False


def Speak(text):
    """Show `text`, pass it to any listeners, and say it aloud unless the voice is switched off."""
    text = str(text).strip()
    if not text:
        return
    _show(f"\nA.I : {text}\n")
    for callback in list(_listeners):
        try:
            callback(text)
        except Exception as e:                  # a faulty listener must never stop Jarvis talking
            print(f": (output listener failed - {e})")
    if TTS_ENABLED:
        _say(text)


def check():
    """Say three sentences and report how long each took. Returns True if Jarvis can speak."""
    print("== Jarvis voice check ==")
    if not TTS_ENABLED:
        print("  [INFO] TTS_ENABLED=false in .env, so Jarvis is set to stay silent.")
        return True
    try:
        voice = _voice()
        print(f"  [INFO] installed voices: {', '.join(token.GetDescription() for token in voice.GetVoices())}")
        print(f"  [INFO] speaking with: {voice.Voice.GetDescription()} (volume {voice.Volume}, rate adjustment {TTS_RATE})")
    except Exception as error:
        print(f"  [FAIL] Windows speech can't be started: {error}")
        return False
    healthy = True
    for number, sentence in enumerate(CHECK_SENTENCES, 1):
        started = time.time()
        spoke = _say(sentence)
        took = time.time() - started
        ok = spoke and took >= len(sentence) / CHECK_CHARACTERS_PER_SECOND
        healthy = healthy and ok
        note = "" if ok else "  <- came back too fast: that sentence was not spoken" if spoke else "  <- the voice failed"
        print(f"  [{' OK ' if ok else 'FAIL'}] sentence {number}: {took:.1f}s{note}")
    print("== Result ==\n  " + ("Jarvis can speak, and keeps speaking." if healthy else
          "Something is wrong with speech. Check the Windows volume, the output device, and that a voice is installed "
          "(Settings, Time & Language, Speech)."))
    return healthy


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
