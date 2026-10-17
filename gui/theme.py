"""Colours and the stylesheet shared by every Qt window."""

BG = "#03070d"
PANEL = "#07111c"
PANEL_ALT = "#0a1a2a"
EDGE = "#0f3a57"
ACCENT = "#18d8ff"
ACCENT_DARK = "#0b8fae"
TEXT = "#d8f4ff"
MUTED = "#7aa3ba"
YOU = "#ffd166"
GOOD = "#38e08c"
WARN = "#ffb43a"
BAD = "#ff5d5d"

# The coloured dot and word in the corner of the window, by what the assistant is doing.
STATES = {
    "locked": ("LOCKED", MUTED),
    "starting": ("STARTING", WARN),
    "ready": ("READY", GOOD),
    "listening": ("LISTENING", ACCENT),
    "working": ("WORKING", WARN),
}

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {EDGE}; border-radius: 10px; }}
QFrame#screen {{ background: #000000; border: 1px solid {EDGE}; border-radius: 10px; }}
QFrame#screen QWidget {{ background: transparent; }}
QFrame#panel QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 22pt; font-weight: 600; color: {ACCENT}; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 8pt; }}
QLabel#heading {{ color: {ACCENT}; font-size: 8pt; font-weight: 600; }}
QLabel#clock {{ font-family: Consolas; font-size: 24pt; color: {TEXT}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#value {{ color: {TEXT}; }}
QLabel#splash {{ color: {MUTED}; font-size: 11pt; }}
QLabel#message {{ color: {MUTED}; }}
QPushButton {{ background: {PANEL_ALT}; border: 1px solid {EDGE}; border-radius: 8px; padding: 8px 12px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {ACCENT}; background: #0d2740; }}
QPushButton:pressed {{ background: #123452; }}
QPushButton:disabled {{ color: #48667a; border-color: #0b2233; background: #06101a; }}
QPushButton:checked {{ border-color: {ACCENT}; color: {ACCENT}; background: #0d2740; }}
QPushButton#primary {{ background: {ACCENT}; color: #02131a; border: none; font-weight: 700; padding: 12px; }}
QPushButton#primary:hover {{ background: #5fe7ff; }}
QPushButton#primary:disabled {{ background: #0b4a5c; color: #3b7f93; }}
QPushButton#danger:hover {{ border-color: {BAD}; color: {BAD}; }}
QPushButton#mic {{ font-size: 13pt; padding: 6px 14px; }}
QPushButton#tool {{ padding: 8px 4px; font-size: 9pt; }}
QLineEdit {{ background: #040c14; border: 1px solid {EDGE}; border-radius: 8px; padding: 9px 12px;
            selection-background-color: {ACCENT_DARK}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: #48667a; background: #050a10; }}
QTextBrowser, QPlainTextEdit {{ background: #040c14; border: 1px solid {EDGE}; border-radius: 10px; padding: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {EDGE}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DARK}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {ACCENT}; padding: 4px; }}
QDialog {{ background: {BG}; }}
"""
