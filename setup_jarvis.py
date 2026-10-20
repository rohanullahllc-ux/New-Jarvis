"""The Jarvis setup wizard:  python setup_jarvis.py     (or double-click Setup-Jarvis.bat, which finds Python first)

Gets Jarvis ready on a bare Windows PC or a freshly restored copy of this folder, and asks you how you like things. It checks what is
already done, so running it again only does what is missing. Options:  --check (only look)  --dry-run  --yes  --help

It uses only what Python comes with, because it runs before anything has been installed.
"""
import sys
from pathlib import Path

if sys.version_info < (3, 12):
    print(f"This is Python {sys.version_info.major}.{sys.version_info.minor}; Jarvis needs Python 3.12 or newer (3.14 is the one he was built on).\n"
          "Install Python 3.14 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run Setup-Jarvis.bat again.")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis_setup.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
