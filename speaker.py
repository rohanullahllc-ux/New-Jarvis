"""Only your voice: tells your voice from other people's, entirely on this PC.

A small speaker-recognition model (NeMo TitaNet through sherpa-onnx) turns a second or two of speech into a "voice print", a list of
192 numbers that is alike for the same person and different for different people. enroll_voice.py records you reading about
fifteen sentences and saves the average as your voice print (DataBase/voiceprint.npz, never leaves this PC and is not in git).
After that every phrase is compared with it, and a voice that is not alike enough is ignored.

It is a convenience, not a lock: a recording of your voice can fool it, a cold or a noisy room can make it refuse you, and the
password is still what lets anybody in. So the typed box and the buttons always work, and VOICE_LOCK=off (or saying "turn off the
voice lock") switches it off. Very short phrases ("yes") cannot be judged, so they are accepted for a minute after one that passed.

    python speaker.py --download      fetch the model (26 MB, once)
"""
import collections
import datetime
import importlib.util
import sys
import threading
import time
import urllib.request

import numpy as np

import native_libs
from config import BASE_DIR, DB_DIR, VOICE_LOCK, VOICE_MATCH
from stt import samples_of

MODEL_FILE = BASE_DIR / "models" / "speaker" / "nemo_en_titanet_small.onnx"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx"
PRINT_FILE = DB_DIR / "voiceprint.npz"
RATE = 16000
MIN_SPEECH = 0.8          # seconds of real speech needed to judge a voice
MIN_ENROLL = 1.2          # a sentence shorter than this does not go into the voice print
MIN_SENTENCES = 5         # fewest usable sentences that make a voice print
TRUST_SECONDS = 60        # a phrase too short to judge is accepted this long after one that passed
RELAXED = 0.08            # the wake phrase "hey Jarvis" is short, so it only needs to be this much less alike
LOWEST, HIGHEST = 0.40, 0.62      # the level chosen at enrolment stays between these

Verdict = collections.namedtuple("Verdict", "ok score reason")      # reason: off | match | mismatch | short | trusted | unavailable

_extractor = None
_extractor_lock = threading.Lock()
_print_cache = {"stamp": None, "data": None}
_override = [None]            # True / False when the user said "turn on / off the voice lock" in this run
_last_ok = [0.0]
_warned = set()


class SpeakerUnavailable(Exception):
    """The voice model cannot be used (not downloaded, library missing, or loaded in the wrong order)."""


# ---------------------------------------------------------------- the model

def model_ready():
    return MODEL_FILE.exists() and importlib.util.find_spec("sherpa_onnx") is not None


def download_model():
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MODEL_URL, MODEL_FILE)
    return MODEL_FILE


def _load():
    global _extractor
    with _extractor_lock:
        if _extractor is None:
            if not model_ready():
                raise SpeakerUnavailable("the voice model is not downloaded (python speaker.py --download)")
            if not native_libs.safe("sherpa_onnx"):
                raise SpeakerUnavailable("the voice libraries were loaded after the window library, which would crash them")
            import sherpa_onnx
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL_FILE), num_threads=1)
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        return _extractor


def embed(samples):
    """The voice print (a unit-length vector) of 16 kHz mono floats."""
    extractor = _load()
    with _extractor_lock:
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=RATE, waveform=np.asarray(samples, dtype=np.float32))
        stream.input_finished()
        vector = np.array(extractor.compute(stream), dtype=np.float32)
    length = float(np.linalg.norm(vector))
    if not length:
        raise SpeakerUnavailable("the voice model gave an empty answer")
    return vector / length


def speech_part(samples):
    """(the samples without the silence around the words, seconds of actual speech in them)."""
    samples = np.asarray(samples, dtype=np.float32)
    frame = RATE // 50                                       # 20 ms
    count = len(samples) // frame
    if count < 3:
        return samples, 0.0
    energy = np.sqrt(np.mean(samples[:count * frame].reshape(count, frame) ** 2, axis=1))
    floor = float(np.percentile(energy, 10))
    loudest = float(energy.max())
    threshold = max(loudest * 0.12, min(floor * 2.5, loudest * 0.5), 1e-4)       # (a clip with no quiet part is all speech)
    loud = np.flatnonzero(energy > threshold)
    if not len(loud):
        return samples[:0], 0.0
    start, end = max(0, loud[0] - 5), min(count, loud[-1] + 6)
    return samples[start * frame:end * frame], len(loud) * frame / RATE


# ---------------------------------------------------------------- the voice print

def _read_print():
    try:
        stamp = PRINT_FILE.stat().st_mtime_ns
    except OSError:
        _print_cache.update(stamp=None, data=None)
        return None
    if _print_cache["stamp"] != stamp:
        try:
            with np.load(PRINT_FILE, allow_pickle=False) as stored:
                _print_cache.update(stamp=stamp, data={"centroid": stored["centroid"], "threshold": float(stored["threshold"]),
                                                       "count": len(stored["embeddings"])})
        except Exception:                                    # noqa: BLE001 - a damaged file counts as no voice print
            _print_cache.update(stamp=stamp, data=None)
    return _print_cache["data"]


def enrolled():
    return _read_print() is not None


def delete_print():
    """Forget the voice print. True if there was one."""
    try:
        PRINT_FILE.unlink()
        found = True
    except OSError:
        found = False
    _print_cache.update(stamp=None, data=None)
    return found


def threshold():
    """How alike a voice must be to the voice print: VOICE_MATCH if it is set, else the level chosen at enrolment."""
    data = _read_print()
    if VOICE_MATCH > 0:
        return min(0.95, max(0.1, VOICE_MATCH))
    return data["threshold"] if data else HIGHEST


def enroll(clips):
    """Make the voice print from recorded sentences (16 kHz mono floats each) and save it.

    Returns a dict: used, skipped (too short), lowest and mean similarity of each sentence to the rest, the level chosen."""
    embeddings, skipped = [], 0
    for clip in clips:
        speech, seconds = speech_part(clip)
        if seconds < MIN_ENROLL:
            skipped += 1
            continue
        embeddings.append(embed(speech))
    if len(embeddings) < MIN_SENTENCES:
        raise ValueError(f"only {len(embeddings)} usable sentences ({skipped} too short or silent): at least {MIN_SENTENCES} are needed")
    matrix = np.stack(embeddings)
    alike = []
    for i in range(len(matrix)):                              # each sentence against the average of all the others
        rest = np.delete(matrix, i, axis=0).mean(axis=0)
        alike.append(float(matrix[i] @ (rest / np.linalg.norm(rest))))
    chosen = min(HIGHEST, max(LOWEST, float(np.mean(alike) - 3 * np.std(alike))))
    centroid = matrix.mean(axis=0)
    centroid /= np.linalg.norm(centroid)
    PRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(PRINT_FILE, embeddings=matrix, centroid=centroid, threshold=chosen, model=MODEL_FILE.name,
             created=datetime.datetime.now().isoformat(timespec="seconds"))
    _print_cache.update(stamp=None, data=None)
    return {"used": len(matrix), "skipped": skipped, "lowest": min(alike), "mean": float(np.mean(alike)), "threshold": chosen}


# ---------------------------------------------------------------- deciding

def set_lock(on):
    """Switch the voice lock on or off for this run (None goes back to what .env says)."""
    _override[0] = on


def lock_active():
    """True when only the owner's voice is answered: VOICE_LOCK (or what was said this run) allows it and a voice print exists."""
    mode = "owner" if _override[0] is True else "off" if _override[0] is False else VOICE_LOCK
    return mode != "off" and enrolled()


def status():
    """One sentence about the voice lock, for the user."""
    if _override[0] is False or (_override[0] is None and VOICE_LOCK == "off"):
        return "The voice lock is off: I answer any voice."
    if not enrolled():
        return "The voice lock is waiting for your voice print. Run: python enroll_voice.py"
    return "The voice lock is on: I only answer your voice."


def score(samples):
    """How alike (-1 to 1) the voice in these samples is to the owner's voice print."""
    data = _read_print()
    if data is None:
        raise SpeakerUnavailable("there is no voice print yet (python enroll_voice.py)")
    return float(embed(samples) @ data["centroid"])


def _warn_once(text):
    if text not in _warned:
        _warned.add(text)
        print(f": ({text})")


def accept(audio, relaxed=False):
    """Is this recording (a speech_recognition AudioData) in the owner's voice? Returns a Verdict(ok, score, reason)."""
    if not lock_active():
        return Verdict(True, None, "off")
    speech, seconds = speech_part(samples_of(audio))
    if seconds < MIN_SPEECH:
        if time.monotonic() - _last_ok[0] < TRUST_SECONDS:
            return Verdict(True, None, "trusted")
        return Verdict(False, None, "short")
    try:
        value = score(speech)
    except SpeakerUnavailable as error:
        _warn_once(f"the voice lock is on but cannot be used - {error}; I am listening to every voice")
        return Verdict(True, None, "unavailable")
    ok = value >= threshold() - (RELAXED if relaxed else 0.0)
    if ok:
        _last_ok[0] = time.monotonic()
    return Verdict(ok, value, "match" if ok else "mismatch")


def warm_up():
    """Load the voice model in the background when the lock is on, so the first phrase does not wait for it."""
    if not lock_active():
        return

    def work():
        try:
            _load()
        except Exception:                                    # noqa: BLE001 - reported when a phrase is judged
            pass
    threading.Thread(target=work, name="speaker-warm-up", daemon=True).start()


if __name__ == "__main__":
    if "--download" in sys.argv:
        print("downloading the voice model (26 MB)...")
        print("saved", download_model())
        sys.exit(0)
    print(status())
    sys.exit(0)
