"""Jarvis's calculator, as its own program:  python gui/utils/calculator.py

It is only the window: all the arithmetic is in calc.py, which the spoken maths uses as well.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import customtkinter as ctk  # noqa: E402

from calc import Keypad  # noqa: E402
from gui import theme  # noqa: E402
from gui.utils import style  # noqa: E402

LAYOUT = [["C", "⌫", "%", "÷"], ["7", "8", "9", "×"], ["4", "5", "6", "−"],
          ["1", "2", "3", "+"], ["±", "0", ".", "="]]
KEYBOARD = {"*": "×", "x": "×", "X": "×", "/": "÷", "-": "−", "\r": "=", "\x08": "⌫",
            "\x1b": "C", "c": "C", "C": "C", "^": "^", "(": "(", ")": ")", "%": "%", "+": "+", ".": ".", "=": "="}


def key_for(char):
    """The keypad key a typed character stands for, or None."""
    if char and char in "0123456789":
        return char
    return KEYBOARD.get(char)


class Calculator(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=theme.BG)
        self.title("Jarvis - Calculator")
        self.geometry("340x540")
        self.resizable(False, False)
        style.set_icon(self)
        self.pad = Keypad()

        screen = ctk.CTkFrame(self, fg_color=theme.PANEL, border_color=theme.EDGE, border_width=1, corner_radius=10)
        screen.pack(fill="x", padx=14, pady=(14, 10))
        self.history = ctk.CTkLabel(screen, text="", anchor="e", text_color=theme.MUTED, font=(style.FONT, 14))
        self.history.pack(fill="x", padx=14, pady=(10, 0))
        self.display = ctk.CTkLabel(screen, text="0", anchor="e", text_color=theme.TEXT, font=(style.FONT, 40))
        self.display.pack(fill="x", padx=14, pady=(0, 12))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for row, keys in enumerate(LAYOUT):
            grid.grid_rowconfigure(row, weight=1)
            for column, key in enumerate(keys):
                grid.grid_columnconfigure(column, weight=1)
                kind = "accent" if key == "=" else "operator" if key in "÷×−+%" else "danger" if key == "C" else "normal"
                style.button(grid, key, lambda key=key: self.press(key), kind, size=22).grid(row=row, column=column, padx=4, pady=4, sticky="nsew")
        self.bind("<Key>", self._typed)

    def press(self, key):
        self.pad.press(key)
        self.render()

    def _typed(self, event):
        key = key_for(event.char) or {"Return": "=", "BackSpace": "⌫", "Escape": "C", "Delete": "C"}.get(event.keysym)
        if key:
            self.press(key)

    def render(self):
        text = self.pad.display
        size = 40 if len(text) <= 11 else 30 if len(text) <= 16 else 22
        self.display.configure(text=text, font=(style.FONT, size), text_color=theme.BAD if self.pad.error else theme.TEXT)
        self.history.configure(text=f"= {self.pad.preview}" if self.pad.preview else (f"{self.pad.history} =" if self.pad.history else ""))


def main():
    Calculator().mainloop()


if __name__ == "__main__":
    main()
