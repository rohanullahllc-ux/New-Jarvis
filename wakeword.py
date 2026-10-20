"""The wake word "hey Jarvis", recognised on this PC (openWakeWord): no internet, no account, and no sound leaves the computer.

A small neural model looks at the last second of sound every 80 ms and gives a score from 0 to 1 for "hey Jarvis". The score has to
stay above the level for two pieces in a row (about 160 ms), so a click or a cough cannot wake him. WAKE_SENSITIVITY sets the level
(sensitivity 0.5 means a score of 0.5): higher hears it more easily and wakes by mistake more often.

It also scores look-alikes ("hey Travis") high, which is why, once you have enrolled your voice, the wake phrase must be in your voice too.

    python wakeword.py --download      fetch the model (about 4 MB, once)
"""
import importlib.util
import sys

import numpy as np

import native_libs
from config import BASE_DIR, WAKE_SENSITIVITY

FOLDER = BASE_DIR / "models" / "wakeword"
MODEL_FILE = "hey_jarvis_v0.1.onnx"
SUPPORT_FILES = ("melspectrogram.onnx", "embedding_model.onnx")          # the two models every wake word is built on
FRAME = 1280                      # 16 kHz samples in 80 ms: the piece the detector wants at a time
IN_A_ROW = 2                      # pieces above the level before it counts (about 160 ms of the phrase)


def files_ready():
    return all((FOLDER / name).exists() for name in (MODEL_FILE, *SUPPORT_FILES))


def available():
    """True if the library and the model files are there and can be loaded safely."""
    return importlib.util.find_spec("openwakeword") is not None and files_ready() and native_libs.safe("onnxruntime")


def download():
    from openwakeword import utils
    FOLDER.mkdir(parents=True, exist_ok=True)
    utils.download_models(["hey_jarvis"], target_directory=str(FOLDER))


def level_for(sensitivity):
    """The score that wakes him: the sensitivity itself, kept away from the two ends."""
    return min(0.95, max(0.05, sensitivity))


class WakeWordDetector:
    def __init__(self, sensitivity=WAKE_SENSITIVITY, model=None):
        self.level = level_for(sensitivity)
        self.pending = np.zeros(0, dtype=np.int16)
        self.run = 0
        self.score = 0.0                      # the highest score of the last piece, for the live meter and the tests
        self.model = model or self._load()

    @staticmethod
    def _load():
        from openwakeword.model import Model
        return Model(wakeword_models=[str(FOLDER / MODEL_FILE)], inference_framework="onnx",
                     melspec_model_path=str(FOLDER / SUPPORT_FILES[0]), embedding_model_path=str(FOLDER / SUPPORT_FILES[1]))

    def reset(self):
        self.pending = np.zeros(0, dtype=np.int16)
        self.run = 0
        self.score = 0.0
        self.model.reset()

    def feed(self, samples):
        """Give it the next sound (16 kHz, 16-bit whole numbers, any length). True when "hey Jarvis" has just been said."""
        samples = np.asarray(samples)
        if samples.dtype != np.int16:
            samples = (np.clip(samples, -1, 1) * 32767).astype(np.int16) if samples.dtype.kind == "f" else samples.astype(np.int16)
        data = np.concatenate([self.pending, samples])
        whole = len(data) // FRAME * FRAME
        self.pending = data[whole:]
        heard = False
        for start in range(0, whole, FRAME):
            scores = self.model.predict(data[start:start + FRAME])
            self.score = float(max(scores.values())) if scores else 0.0
            self.run = self.run + 1 if self.score >= self.level else 0
            if self.run >= IN_A_ROW and not heard:
                heard = True
                self.run = 0
        if heard:
            self.model.reset()                 # forget the phrase, so the same one cannot be heard twice
        return heard


if __name__ == "__main__":
    if "--download" in sys.argv:
        print("downloading the wake-word model...")
        download()
        print("done:", "ready" if files_ready() else "some files are missing")
        sys.exit(0)
    print(__doc__)
