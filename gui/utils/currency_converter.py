"""Jarvis's currency converter, as its own program:  python gui/utils/currency_converter.py

Rates come from rates.py, the same place the spoken "100 dollars in rupees" gets them.
"""
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import customtkinter as ctk  # noqa: E402

import rates  # noqa: E402
from config import HOME_CURRENCY  # noqa: E402
from gui import theme  # noqa: E402
from gui.utils import style  # noqa: E402

COMMON = ["USD", "PKR", "EUR", "GBP", "SAR", "AED", "INR", "CNY", "JPY", "CAD", "AUD", "TRY", "AFN", "BDT", "MYR", "QAR", "KWD"]


def parse_amount(text):
    """The number typed in the amount box (commas allowed). Raises ValueError if it isn't one."""
    value = float((text or "").replace(",", "").strip())
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("not a number")
    return value


def clean_code(text):
    code = (text or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"{code or 'An empty box'} is not a three-letter currency code")
    return code


def format_amount(value):
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4g}"


def format_result(amount, source, target, converted):
    return f"{format_amount(amount)} {source} = {format_amount(converted)} {target}"


class CurrencyConverter(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=theme.BG)
        self.title("Jarvis - Currency converter")
        self.geometry("420x400")
        self.resizable(False, False)
        style.set_icon(self)
        self._messages = queue.Queue()

        card = ctk.CTkFrame(self, fg_color=theme.PANEL, border_color=theme.EDGE, border_width=1, corner_radius=10)
        card.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(card, text="AMOUNT", text_color=theme.ACCENT, font=(style.FONT, 11, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        self.amount = ctk.CTkEntry(card, font=(style.FONT, 22), height=44, fg_color="#040c14", border_color=theme.EDGE, text_color=theme.TEXT)
        self.amount.pack(fill="x", padx=18)
        self.amount.insert(0, "1")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=14)
        row.grid_columnconfigure((0, 2), weight=1)
        self.source = self._menu(row, "USD")
        self.target = self._menu(row, HOME_CURRENCY if HOME_CURRENCY != "USD" else "EUR")
        self.source.grid(row=0, column=0, sticky="ew")
        style.button(row, "⇄", self.swap, size=18, width=44).grid(row=0, column=1, padx=8)
        self.target.grid(row=0, column=2, sticky="ew")

        style.button(card, "CONVERT", self.convert, "accent", size=16, height=44).pack(fill="x", padx=18)
        self.result = ctk.CTkLabel(card, text="", font=(style.FONT, 22, "bold"), text_color=theme.TEXT, wraplength=360)
        self.result.pack(pady=(18, 4), padx=18)
        self.status = ctk.CTkLabel(card, text="Loading the list of currencies...", font=(style.FONT, 12), text_color=theme.MUTED, wraplength=360)
        self.status.pack(padx=18)

        self.bind("<Return>", lambda _event: self.convert())
        threading.Thread(target=self._load_codes, daemon=True).start()
        self.after(100, self._poll)

    def _menu(self, parent, value):
        menu = ctk.CTkComboBox(parent, values=COMMON, height=40, font=(style.FONT, 16), dropdown_font=(style.FONT, 14),
                               fg_color="#040c14", border_color=theme.EDGE, button_color=theme.PANEL_ALT,
                               button_hover_color="#0d2740", text_color=theme.TEXT, dropdown_fg_color=theme.PANEL_ALT,
                               dropdown_text_color=theme.TEXT)
        menu.set(value)
        return menu

    def swap(self):
        first, second = self.source.get(), self.target.get()
        self.source.set(second)
        self.target.set(first)

    def convert(self):
        try:
            amount = parse_amount(self.amount.get())
            source, target = clean_code(self.source.get()), clean_code(self.target.get())
        except ValueError as problem:
            self._show_error(f"Enter a number and two currency codes ({problem}).")
            return
        self.result.configure(text="...", text_color=theme.MUTED)
        threading.Thread(target=self._convert, args=(amount, source, target), daemon=True).start()

    def _convert(self, amount, source, target):
        try:
            self._messages.put(("result", format_result(amount, source, target, rates.convert(amount, source, target))))
        except rates.RateError as problem:
            self._messages.put(("error", str(problem)))

    def _load_codes(self):
        try:
            self._messages.put(("codes", rates.codes("USD")))
        except rates.RateError as problem:
            self._messages.put(("status", f"Couldn't load the currency list: {problem}"))

    def _show_error(self, text):
        self.result.configure(text="", text_color=theme.TEXT)
        self.status.configure(text=text, text_color=theme.BAD)

    def _poll(self):
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "codes":
                self.source.configure(values=payload)
                self.target.configure(values=payload)
                self.status.configure(text="Live rates from open.er-api.com", text_color=theme.MUTED)
            elif kind == "result":
                self.result.configure(text=payload, text_color=theme.TEXT)
                self.status.configure(text="Live rates from open.er-api.com", text_color=theme.MUTED)
            elif kind == "error":
                self._show_error(payload)
            else:
                self.status.configure(text=payload, text_color=theme.WARN)
        self.after(100, self._poll)


def main():
    CurrencyConverter().mainloop()


if __name__ == "__main__":
    main()
