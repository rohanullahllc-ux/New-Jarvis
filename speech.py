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
* SpeakStream says a reply that is still being written, sentence by sentence, starting with the first one.

Run `python speech.py` to check that Jarvis can speak.
"""
import queue
import sys
import threading
import time

import personal
import tts_piper
from config import TTS_ENABLED, TTS_ENGINE, TTS_RATE, TTS_VOICE, TTS_VOLUME

_local = threading.local()
_listeners = []          # extra places a reply should appear, e.g. the GUI's conversation pane
_streaming = set()       # the listeners that also want to know whether a line starts a new message or continues one
_say_lock = threading.Lock()
_speaking = threading.Event()   # set while a sentence is being spoken: the microphone must not listen to Jarvis himself
_last_spoken = [0.0]            # time.monotonic() when the last sentence ended
_reported = set()        # voice problems already shown, so one broken voice doesn't repeat itself

CHECK_SENTENCES = ("Testing, one, two, three.", "This is the second sentence, to prove that Jarvis keeps on speaking.",
                   "And a third.")
CHECK_CHARACTERS_PER_SECOND = 25      # speech is slower than this, so a sentence that comes back faster was not spoken


def is_speaking():
    return _speaking.is_set()


def quiet_for():
    """Seconds since Jarvis last finished a sentence (0 while he is speaking; a very large number if he has not spoken)."""
    if _speaking.is_set():
        return 0.0
    return time.monotonic() - _last_spoken[0] if _last_spoken[0] else 1e9


def spoke_since(moment):
    """True if Jarvis spoke, or is speaking, at any time after ``moment`` (a time.monotonic() value)."""
    return _speaking.is_set() or _last_spoken[0] >= moment


def wait_until_quiet(timeout=30.0, settle=0.35):
    """Wait until Jarvis has stopped speaking, plus ``settle`` seconds for the room to stop echoing. True if it went quiet."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _speaking.is_set() and quiet_for() >= settle:
            return True
        time.sleep(0.03)
    return False


def _show(line):
    """Print a line; characters the console can't display (Urdu on a cp1252 pane) become '?' instead of crashing."""
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding))


def add_listener(callback, streaming=False):
    """Call ``callback(text)`` for every spoken line (the GUI uses this to show replies).

    With streaming=True it is called as ``callback(text, first)`` instead, where ``first`` is False for the second and
    later sentences of one reply (see SpeakStream), so a window can show them as one message.
    """
    if callback not in _listeners:
        _listeners.append(callback)
    if streaming:
        _streaming.add(callback)


def remove_listener(callback):
    if callback in _listeners:
        _listeners.remove(callback)
    _streaming.discard(callback)


def _tell_listeners(text, first=True):
    for callback in list(_listeners):
        try:
            if callback in _streaming:
                callback(text, first)
            else:
                callback(text)
        except Exception as e:                  # a faulty listener must never stop Jarvis talking
            print(f": (output listener failed - {e})")


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


def _use_piper():
    """True when Jarvis speaks with the natural Piper voice (TTS_ENGINE, and a voice installed in models/piper)."""
    return TTS_ENGINE in ("auto", "piper") and tts_piper.available()


def _rate_for(text):
    return (2 if len(text) > 30 else 0) + TTS_RATE          # long replies a little faster


def _report(problem):
    """Say a voice problem once, not on every sentence."""
    if problem not in _reported:
        _reported.add(problem)
        print(f": ({problem})")


def warm_up():
    """Load the natural voice in the background (a few seconds), so the first reply is not slow."""
    if TTS_ENABLED and _use_piper():
        tts_piper.warm_up()


def _prefetch(sentence):
    """Start making the sentence in the natural voice while the one before it is still being spoken."""
    if TTS_ENABLED and _use_piper():
        tts_piper.prefetch(sentence, _rate_for(sentence))


def _say(text):
    """Speak ``text`` and wait until it has been said. Returns False if the voice failed."""
    try:
        with _say_lock:
            _speaking.set()
            try:
                if _use_piper():
                    if tts_piper.say(text, _rate_for(text)):
                        return True
                    _report(f"the natural voice failed ({tts_piper.last_error}); the Windows voice says it instead")
                voice = _voice()
                voice.Rate = max(-10, min(10, _rate_for(text)))
                voice.Speak(text, 0)            # 0 = do not return until the whole sentence has been spoken
            finally:
                _last_spoken[0] = time.monotonic()
                _speaking.clear()
        return True
    except Exception as error:
        _local.voice = None                     # start fresh next time rather than reusing a broken voice
        _report(f"the voice is unavailable - {error}; carrying on in text")
        return False


def Speak(text):
    """Show `text`, pass it to any listeners, and say it aloud unless the voice is switched off."""
    text = personal.address(str(text).strip())          # "sir" becomes the word the user chose (ADDRESS_AS)
    if not text:
        return
    _show(f"\nA.I : {text}\n")
    _tell_listeners(text)
    if TTS_ENABLED:
        _say(text)


def Show(text):
    """Put text in front of the user (the console and the window's conversation) without saying it: for what a voice can't
    read aloud, such as an Urdu translation or a page of a book."""
    text = personal.address(str(text).strip())
    if not text:
        return
    _show(f"\nA.I : {text}\n")
    _tell_listeners(text)


_DONE = object()


def SpeakStream(sentences, if_slow=None, after=4.0):
    """Say a reply that is still being written: ``sentences`` is any iterable (usually a generator) of sentences.

    Speaking starts with the first sentence, while the next ones are still being produced on another thread. Listeners
    get them as one message (see add_listener). If nothing has arrived after ``after`` seconds, ``if_slow`` is said once,
    so a slow model isn't mistaken for a crash. Returns True if anything was said.
    """
    ready, problems = queue.Queue(), []

    def produce():
        try:
            for sentence in sentences:
                ready.put(sentence)
                _prefetch(personal.address(str(sentence).strip()))
        except BaseException as error:          # noqa: BLE001 - re-raised below, on the thread that is speaking
            problems.append(error)
        finally:
            ready.put(_DONE)

    threading.Thread(target=produce, name="reply-stream", daemon=True).start()
    first, waited = True, False
    while True:
        try:
            sentence = ready.get(timeout=after if (first and if_slow and not waited) else None)
        except queue.Empty:
            waited = True
            Speak(if_slow)
            continue
        if sentence is _DONE:
            break
        sentence = personal.address(str(sentence).strip())
        if not sentence:
            continue
        _show(f"\nA.I : {sentence}\n" if first else f"      {sentence}\n")
        _tell_listeners(sentence, first)
        if TTS_ENABLED:
            _say(sentence)
        first = False
    if problems:
        raise problems[0]
    return not first


def check():
    """Say three sentences and report how long each took. Returns True if Jarvis can speak."""
    print("== Jarvis voice check ==")
    if not TTS_ENABLED:
        print("  [INFO] TTS_ENABLED=false in .env, so Jarvis is set to stay silent.")
        return True
    try:
        if _use_piper():
            print(f"  [INFO] speaking with the natural voice {tts_piper.voice_name()} (Piper, made on this PC; "
                  f"installed: {', '.join(tts_piper.installed())})")
        else:
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
