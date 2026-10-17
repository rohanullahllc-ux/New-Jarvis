"""Opens Jarvis's small utility windows (calculator, calendar, currency converter) as their own programs.

They are CustomTkinter windows and the main window is Qt: two different GUI toolkits cannot share one
thread, so each utility runs as a separate process. Both the main window's buttons and the
open_utility_app tool come through here.
"""
import os
import subprocess
import sys
from pathlib import Path

from config import BASE_DIR

HERE = Path(__file__).resolve().parent
UTILITIES = {"calculator": "calculator.py", "calendar": "calendar_view.py", "currency_converter": "currency_converter.py"}


def launch(name):
    """Start the utility called ``name``. Raises FileNotFoundError if its script is missing."""
    script = HERE / UTILITIES[name]
    if not script.exists():
        raise FileNotFoundError(f"The {name.replace('_', ' ')} window isn't installed.")
    windowless = Path(sys.executable).with_name("pythonw.exe")           # no console window behind a GUI
    interpreter = windowless if windowless.exists() else Path(sys.executable)
    env = {**os.environ, "PYTHONPATH": str(BASE_DIR)}
    subprocess.Popen([str(interpreter), str(script)], cwd=str(BASE_DIR), env=env,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
