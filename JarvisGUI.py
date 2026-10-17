"""Window launcher:  python JarvisGUI.py

One of the two ways in (the other is Startup.py). START asks for the password through gate.py, exactly
as the terminal does, before any session begins.
"""
import sys

from gui.main_window import main

if __name__ == "__main__":
    sys.exit(main())
