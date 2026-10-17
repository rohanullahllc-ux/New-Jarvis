"""The look shared by the small CustomTkinter windows (the same colours as the main window)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:                      # lets these windows start straight from a terminal too
    sys.path.insert(0, str(ROOT))

import customtkinter as ctk  # noqa: E402

from gui import theme  # noqa: E402

ctk.set_appearance_mode("dark")

FONT = "Segoe UI"
ICON = ROOT / "gui" / "resources" / "jarvis.ico"


def set_icon(window):
    """Give a CustomTkinter window the JARVIS icon (it sets its own a moment after opening, so wait for that)."""
    def apply():
        try:
            window.iconbitmap(str(ICON))
        except Exception:                                  # a missing icon is only cosmetic
            pass
    window.after(300, apply)

BUTTONS = {
    "normal": dict(fg_color=theme.PANEL_ALT, hover_color="#0d2740", text_color=theme.TEXT, border_color=theme.EDGE, border_width=1),
    "operator": dict(fg_color="#0d2f45", hover_color="#124565", text_color=theme.ACCENT, border_color=theme.EDGE, border_width=1),
    "accent": dict(fg_color=theme.ACCENT, hover_color="#5fe7ff", text_color="#02131a", border_width=0),
    "danger": dict(fg_color=theme.PANEL_ALT, hover_color="#3a1418", text_color=theme.BAD, border_color=theme.EDGE, border_width=1),
}


def button(parent, text, command, kind="normal", size=16, **options):
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=8, font=(FONT, size), **BUTTONS[kind], **options)
