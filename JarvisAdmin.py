"""The admin panel on its own:  python JarvisAdmin.py     (or double-click Admin-Panel.bat)

Asks for the Jarvis password, then opens the panel where every setting, shortcut and contact can be changed and a backup made. It works
even when the main Jarvis window will not open, so a wrong setting can always be put right. (Inside the Jarvis window the same
panel opens with the ADMIN button, or when you say "open the admin panel".)
"""
import sys

from gui.admin_panel import open_admin
from gui import theme
from PyQt5.QtWidgets import QApplication


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Jarvis admin")
    app.setStyleSheet(theme.STYLESHEET)
    opened = open_admin()
    return 0 if opened else 1


if __name__ == "__main__":
    sys.exit(main())
