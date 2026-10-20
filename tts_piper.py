"""Jarvis's natural voice: Piper, a neural text-to-speech that runs entirely on this PC (no internet, no account).

speech.py uses it instead of the Windows voice whenever a voice is installed in models/piper (TTS_ENGINE=windows switches it
off) and falls back to the Windows voice for any sentence Piper cannot say.

    python tts_piper.py --demo      play every installed voice, so you can choose PIPER_VOICE in .env
    python tts_piper.py "some text" say something with the chosen voice

Voices are .onnx files (with a .json beside each) in models/piper. More come from:
    python -m piper.download_voices en_US-ryan-medium --download-dir models/piper

A sentence takes about a fifth of its own length to make on this CPU, so the next sentence of a reply is made while the
current one is still being spoken (prefetch).
"""
import collections
import importlib.util
import io
import sys
import threading
import time
import wave

import native_libs
from config import BASE_DIR, PIPER_VOICE, TTS_VOLUME

VOICE_DIR = BASE_DIR / "models" / "piper"
_voice = None
_voice_name = ""
_load_lock = threading.Lock()
_make_lock = threading.Lock()          # the phonemizer inside Piper is not safe to use from two threads at once
_cache = collections.OrderedDict()     # (text, speed) -> (pcm bytes, sample rate): sentences already made, for prefetch
_CACHE_SIZE = 12
last_error = ""                        # why the last sentence could not be said ("" when it could)


def installed():
    """Names of the voices in models/piper (each needs its .onnx and its .json)."""
    if not VOICE_DIR.is_dir():
        return []
    return sorted(path.stem for path in VOICE_DIR.glob("*.onnx") if path.with_name(path.name + ".json").exists())


def chosen():
    """The voice to use: PIPER_VOICE if it is installed, otherwise the first one that is. "" if none is."""
    names = installed()
    return PIPER_VOICE if PIPER_VOICE in names else (names[0] if names else "")


def available():
    """True if Piper and at least one voice are installed and can be loaded safely (nothing is loaded by asking)."""
    return importlib.util.find_spec("piper") is not None and bool(chosen()) and native_libs.safe("onnxruntime")


def load():
    """The loaded voice (the first call takes a few seconds)."""
    global _voice, _voice_name
    with _load_lock:
        if _voice is None:
            name = chosen()
            if not name:
                raise RuntimeError("no Piper voice is installed in models/piper")
            from piper import PiperVoice
            _voice = PiperVoice.load(str(VOICE_DIR / f"{name}.onnx"))
            _voice_name = name
        return _voice


def voice_name():
    return _voice_name or chosen()


def warm_up():
    """Load the voice and make one short sentence in the background, so the first real reply is not slow."""
    def work():
        try:
            load()
            synthesize("Ready.")
        except Exception:                                  # noqa: BLE001 - the real error shows when a sentence is spoken
            pass
    threading.Thread(target=work, name="piper-warm-up", daemon=True).start()


def speed_for(rate):
    """Piper's speed for the TTS_RATE scale (-10 slower ... 10 faster, 0 normal)."""
    return min(1.6, max(0.6, 1.0 + 0.05 * rate))


def _settings(length_scale, volume):
    from piper import SynthesisConfig
    return SynthesisConfig(length_scale=length_scale, volume=volume)


def synthesize(text, speed=1.0):
    """(16-bit mono sound as bytes, sample rate) for ``text``."""
    key = (text, round(speed, 2))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    voice = load()
    settings = _settings(1.0 / speed, min(1.0, max(0.0, TTS_VOLUME / 100)))
    with _make_lock:
        if key in _cache:
            return _cache[key]
        pcm = b"".join(chunk.audio_int16_bytes for chunk in voice.synthesize(text, syn_config=settings))
        made = (pcm, voice.config.sample_rate)
        _cache[key] = made
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return made


def prefetch(text, rate=0):
    """Start making ``text`` in the background (the next sentence of a reply, while the current one is spoken)."""
    text = (text or "").strip()
    if not text or not available():
        return

    def work():
        try:
            synthesize(text, speed_for(rate))
        except Exception:                                  # noqa: BLE001 - say() will report it if it matters
            pass
    threading.Thread(target=work, name="piper-prefetch", daemon=True).start()


def _wave_bytes(pcm, rate):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def play(pcm, rate):
    """Play the sound and return when it has finished."""
    import winsound
    winsound.PlaySound(_wave_bytes(pcm, rate), winsound.SND_MEMORY)


def stop():
    """Cut off whatever is being spoken."""
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:                                      # noqa: BLE001
        pass


def say(text, rate=0):
    """Speak ``text`` aloud and return when it has been said. False (and ``last_error``) if it could not be."""
    global last_error
    try:
        pcm, sample_rate = synthesize(text, speed_for(rate))
        if not pcm:
            raise RuntimeError("Piper made no sound for that text")
        play(pcm, sample_rate)
        last_error = ""
        return True
    except Exception as error:                             # noqa: BLE001 - the Windows voice takes over
        last_error = f"{type(error).__name__}: {error}"
        return False


def use(name):
    """Switch to another installed voice (the demo does; the setting in .env is what normally decides)."""
    global _voice, _voice_name, PIPER_VOICE
    with _load_lock:
        _voice, _voice_name = None, ""
    PIPER_VOICE = name
    _cache.clear()


def demo():
    names = installed()
    if not names:
        print("No Piper voice is installed in models/piper.")
        return 1
    original = chosen()
    for name in names:
        print(f"Voice {name}" + ("   <- the one set in PIPER_VOICE" if name == original else ""))
        use(name)
        started = time.time()
        ok = say("Good evening sir. It is Monday, 19 October. I have added two tasks to your list: buy milk, and call Ali at five p m.")
        print(f"   {'spoken' if ok else 'FAILED: ' + last_error} in {time.time() - started:.1f}s")
    use(original)
    print("\nTo keep one, put its name after PIPER_VOICE= in the .env file.")
    return 0


if __name__ == "__main__":
    if "--demo" in sys.argv:
        sys.exit(demo())
    spoken = " ".join(arg for arg in sys.argv[1:] if not arg.startswith("--")) or "Hello sir. This is my new voice."
    print("speaking with", voice_name() or "(no voice installed)")
    sys.exit(0 if say(spoken) else 1)
