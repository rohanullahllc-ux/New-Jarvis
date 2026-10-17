"""Jarvis's calendar, as its own program:  python gui/utils/calendar_view.py

Click a day to see which weekday it is, and which day and week of the year. Arrow keys move
between months (left/right) and years (up/down); T jumps back to today.
"""
import calendar
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import customtkinter as ctk  # noqa: E402

from gui import theme  # noqa: E402
from gui.utils import style  # noqa: E402

FIRST_WEEKDAY = calendar.MONDAY


def month_grid(year, month, first_weekday=FIRST_WEEKDAY):
    """The month as rows of seven day numbers, with 0 for days that belong to the neighbouring months."""
    return calendar.Calendar(first_weekday).monthdayscalendar(year, month)


def weekday_names(first_weekday=FIRST_WEEKDAY):
    return [calendar.day_abbr[(first_weekday + offset) % 7] for offset in range(7)]


def shift_month(year, month, change):
    """(year, month) moved by ``change`` months."""
    index = year * 12 + (month - 1) + change
    return index // 12, index % 12 + 1


def describe(day):
    length = 366 if calendar.isleap(day.year) else 365
    return f"{day:%A}, {day.day} {day:%B %Y}\nDay {day.timetuple().tm_yday} of {length}, week {day.isocalendar().week}"


class CalendarWindow(ctk.CTk):
    def __init__(self, today=None):
        super().__init__(fg_color=theme.BG)
        self.title("Jarvis - Calendar")
        self.geometry("400x470")
        self.resizable(False, False)
        style.set_icon(self)
        self.today = today or datetime.date.today()
        self.selected = self.today
        self.year, self.month = self.today.year, self.today.month

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        for text, change, side in (("«", -12, "left"), ("‹", -1, "left"), ("»", 12, "right"), ("›", 1, "right")):
            style.button(header, text, lambda change=change: self.move(change), size=18, width=40).pack(side=side, padx=2)
        self.title_label = ctk.CTkLabel(header, text="", font=(style.FONT, 18, "bold"), text_color=theme.ACCENT)
        self.title_label.pack(expand=True)

        body = ctk.CTkFrame(self, fg_color=theme.PANEL, border_color=theme.EDGE, border_width=1, corner_radius=10)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        for column, name in enumerate(weekday_names()):
            body.grid_columnconfigure(column, weight=1)
            ctk.CTkLabel(body, text=name, text_color=theme.MUTED, font=(style.FONT, 12)).grid(row=0, column=column, pady=(10, 4))
        self.cells = []
        for row in range(1, 7):
            body.grid_rowconfigure(row, weight=1)
            for column in range(7):
                cell = ctk.CTkButton(body, text="", width=44, height=38, corner_radius=8, font=(style.FONT, 14), border_width=0)
                cell.grid(row=row, column=column, padx=2, pady=2)
                self.cells.append(cell)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(6, 14))
        self.info = ctk.CTkLabel(footer, text="", justify="left", anchor="w", text_color=theme.TEXT, font=(style.FONT, 13))
        self.info.pack(side="left", fill="x", expand=True)
        style.button(footer, "Today", self.go_today, "accent", size=14, width=80).pack(side="right")

        for key, change in (("<Left>", -1), ("<Right>", 1), ("<Up>", -12), ("<Down>", 12)):
            self.bind(key, lambda _event, change=change: self.move(change))
        self.bind("t", lambda _event: self.go_today())
        self.render()

    def move(self, change):
        self.year, self.month = shift_month(self.year, self.month, change)
        self.render()

    def go_today(self):
        self.selected = self.today
        self.year, self.month = self.today.year, self.today.month
        self.render()

    def select(self, number):
        self.selected = datetime.date(self.year, self.month, number)
        self.render()

    def render(self):
        self.title_label.configure(text=f"{calendar.month_name[self.month]} {self.year}")
        numbers = [number for week in month_grid(self.year, self.month) for number in week]
        numbers += [0] * (len(self.cells) - len(numbers))
        for cell, number in zip(self.cells, numbers):
            if not number:
                cell.configure(text="", state="disabled", fg_color="transparent", border_width=0)
                continue
            day = datetime.date(self.year, self.month, number)
            chosen, is_today = day == self.selected, day == self.today
            cell.configure(text=str(number), state="normal", command=lambda number=number: self.select(number),
                           fg_color=theme.ACCENT if chosen else theme.PANEL_ALT, hover_color="#5fe7ff" if chosen else "#0d2740",
                           text_color="#02131a" if chosen else theme.TEXT,
                           border_width=2 if is_today else 0, border_color=theme.ACCENT)
        self.info.configure(text=describe(self.selected))


def main():
    CalendarWindow().mainloop()


if __name__ == "__main__":
    main()
