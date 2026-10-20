"""Speech recognition on this PC: Whisper (through faster-whisper), with no internet and no account.

microphone.py asks it first for the words in every recorded phrase; Google's web service is only the second opinion when
Whisper heard nothing (STT_ENGINE=auto), or not used at all (STT_ENGINE=whisper), or the only one (STT_ENGINE=google).

    python stt.py --download      fetch the model chosen by STT_MODEL (needs the internet once; about 150 MB for base.en)
    python stt.py file.wav        say what is in a recording

The models live in models/whisper. Whisper writes capital letters and punctuation; they are taken out here, because the
rest of Jarvis reads plain lower-case words, as Google gives them.
"""
import importlib.util
import re
import sys
import threading
import time

import numpy as np

import native_libs
from config import BASE_DIR, STT_ENGINE, STT_MODEL

MODEL_DIR = BASE_DIR / "models" / "whisper"
THREADS = 3                       # the CPU has 2 cores / 4 threads; one is left for the rest of Jarvis
MIN_SECONDS = 0.25                # shorter than this is a click, not a word

# Words Jarvis hears all day. Whisper spells a word it has just been shown far more reliably ("task", not "test").
VOCABULARY = ("Jarvis. Commands: open, close, task, tasks, note, notes, folder, to do list, add, remove, delete, clear, "
              "timer, reminder, screenshot, microphone volume, weather, battery, Wi-Fi.")
# What Whisper makes up when it is given sound with no speech in it.
INVENTED = {"thanks for watching", "thank you for watching", "subscribe to my channel", "please subscribe", "you", "the end"}

_model = None
_load_lock = threading.Lock()
_use_lock = threading.Lock()
last_error = ""


class SpeechRecognitionFailed(Exception):
    """Whisper could not be used for this recording (the caller falls back to Google)."""


def _model_folder(name=None):
    """The folder of the chosen model inside models/whisper, or None if it has not been downloaded."""
    name = name or STT_MODEL
    for snapshot in sorted(MODEL_DIR.glob(f"models--Systran--faster-whisper-{name}/snapshots/*")):
        if (snapshot / "model.bin").exists():
            return snapshot
    return None


def available():
    """True if Whisper may be used: it is switched on in .env, the library is installed and the model is downloaded."""
    return (STT_ENGINE in ("auto", "whisper") and importlib.util.find_spec("faster_whisper") is not None
            and native_libs.safe("faster_whisper") and _model_folder() is not None)


def load():
    """The loaded model (the first call takes a second or two)."""
    global _model
    with _load_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            folder = _model_folder()
            if folder is None:
                raise SpeechRecognitionFailed(f"the Whisper model {STT_MODEL} is not downloaded (python stt.py --download)")
            _model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=THREADS)
        return _model


def download():
    from faster_whisper import WhisperModel
    WhisperModel(STT_MODEL, device="cpu", compute_type="int8", download_root=str(MODEL_DIR))
    return _model_folder()


def warm_up():
    """Load the model in the background, so the first phrase does not wait for it."""
    if not available():
        return

    def work():
        try:
            load()
        except Exception:                                  # noqa: BLE001 - the real error shows when a phrase is heard
            pass
    threading.Thread(target=work, name="whisper-warm-up", daemon=True).start()


def samples_of(audio):
    """A speech_recognition AudioData as 16 kHz mono floats, which is what Whisper reads."""
    raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def tidy(text):
    """Whisper's text as plain lower-case words: no capitals, no commas or full stops, but "5:30", "3.5" and "p.m." stay."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)                          # [MUSIC], (laughs)
    text = re.sub(r"\b([ap])\.\s?m\.?", r"\1.m.", text, flags=re.I)
    text = text.lower()
    text = re.sub(r"(?<![ap]\.m)[,;:!?]+(?=\s|$)|(?<![ap]\.m)\.+(?=\s|$)|\s[-–—]+\s", " ", text)
    text = re.sub(r"[\"“”]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def transcribe(audio):
    """The words in a recording (a speech_recognition AudioData), as plain lower-case text; "" if nothing was said.

    Raises SpeechRecognitionFailed when Whisper cannot be used at all, so the caller can ask Google instead."""
    global last_error
    try:
        samples = samples_of(audio)
        if len(samples) < MIN_SECONDS * 16000:
            return ""
        model = load()
        with _use_lock:
            segments, _ = model.transcribe(samples, language="en", beam_size=1, temperature=0.0, condition_on_previous_text=False,
                                           initial_prompt=VOCABULARY, vad_filter=True,
                                           vad_parameters={"min_silence_duration_ms": 600})
            kept = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0) and s.avg_logprob > -1.6]
        last_error = ""
    except SpeechRecognitionFailed as error:
        last_error = str(error)
        raise
    except Exception as error:                              # noqa: BLE001 - whatever the library throws, Google can still try
        last_error = f"{type(error).__name__}: {error}"
        raise SpeechRecognitionFailed(last_error) from error
    text = tidy(" ".join(kept))
    if text in INVENTED or text.rstrip(" .") == tidy(VOCABULARY).rstrip(" ."):
        return ""
    return text


if __name__ == "__main__":
    if "--download" in sys.argv:
        print(f"downloading {STT_MODEL} ...")
        print("model is in", download())
        sys.exit(0)
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if not paths:
        print(__doc__)
        sys.exit(1)
    import speech_recognition as sr
    recognizer = sr.Recognizer()
    for path in paths:
        with sr.AudioFile(path) as source:
            recording = recognizer.record(source)
        started = time.time()
        print(f"{path}: {transcribe(recording)!r}  ({time.time() - started:.1f}s)")
