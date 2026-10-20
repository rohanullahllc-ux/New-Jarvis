"""Load the voice libraries' native code BEFORE the window library (PyQt5).

On this Windows, importing onnxruntime (which Piper, the wake word and Whisper's helpers use) after PyQt5 has been imported
crashes the whole program with an access violation, while the other order works. The gui package calls preload() first, so
whatever starts the window (JarvisGUI.py, anything importing gui) gets the safe order. Each library is optional: one that is not
installed, or will not load, is skipped, and the feature that needs it says so when it is used.

If PyQt5 somehow got in first, the libraries are NOT imported (that would crash), and safe() tells the voice modules to stay off.
"""
import importlib
import sys

LIBRARIES = ("onnxruntime", "sherpa_onnx", "faster_whisper")
loaded = []


def qt_is_loaded():
    return "PyQt5.QtCore" in sys.modules


def safe(name):
    """True if importing ``name`` cannot crash the program: it is already loaded, or the window library is not."""
    return name in sys.modules or not qt_is_loaded()


def preload():
    """Import each library once (when that is safe); returns the names that are loaded."""
    for name in LIBRARIES:
        if name in loaded or not safe(name):
            continue
        try:
            importlib.import_module(name)
            loaded.append(name)
        except Exception:                                  # noqa: BLE001 - optional: the feature that needs it reports the problem
            pass
    return list(loaded)
