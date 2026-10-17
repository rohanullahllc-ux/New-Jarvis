"""Tests for the calculator, calendar and currency-converter windows:  python -m unittest tests.test_gui_utils -v

The logic is tested directly. Each window is also opened once, hidden, in a separate process (so the Tk
and Qt toolkits never share one), poked, and closed, to prove it builds and responds.
"""
import datetime
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gui.utils import calculator, calendar_view, currency_converter  # noqa: E402


class CalculatorWindowTests(unittest.TestCase):
    def test_typed_characters_map_to_calculator_keys(self):
        for char, key in (("7", "7"), ("*", "×"), ("x", "×"), ("/", "÷"), ("-", "−"), ("+", "+"),
                          (".", "."), ("%", "%"), ("=", "="), ("\r", "="), ("\x08", "⌫"), ("c", "C"), ("\x1b", "C")):
            self.assertEqual(calculator.key_for(char), key, repr(char))
        for char in ("a", "", None, " ", "z"):
            self.assertIsNone(calculator.key_for(char), repr(char))

    def test_every_key_on_the_pad_means_something_to_the_keypad(self):
        keys = [key for row in calculator.LAYOUT for key in row]
        self.assertEqual(len(keys), 20)
        self.assertEqual(len(set(keys)), 20)


class CalendarLogicTests(unittest.TestCase):
    def test_a_month_is_rows_of_seven_starting_on_monday(self):
        grid = calendar_view.month_grid(2026, 10)
        self.assertTrue(all(len(week) == 7 for week in grid))
        self.assertEqual(grid[0], [0, 0, 0, 1, 2, 3, 4])               # 1 October 2026 is a Thursday
        self.assertEqual(max(max(week) for week in grid), 31)
        self.assertEqual(sum(1 for week in grid for day in week if day), 31)

    def test_a_month_can_start_on_sunday_instead(self):
        self.assertEqual(calendar_view.month_grid(2026, 10, first_weekday=6)[0], [0, 0, 0, 0, 1, 2, 3])
        self.assertEqual(calendar_view.weekday_names(6)[0], "Sun")

    def test_weekday_names(self):
        self.assertEqual(calendar_view.weekday_names(), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def test_moving_between_months_and_years(self):
        shift = calendar_view.shift_month
        self.assertEqual(shift(2026, 12, 1), (2027, 1))
        self.assertEqual(shift(2026, 1, -1), (2025, 12))
        self.assertEqual(shift(2026, 10, 12), (2027, 10))
        self.assertEqual(shift(2026, 10, -24), (2024, 10))
        self.assertEqual(shift(2026, 10, 0), (2026, 10))

    def test_a_day_is_described_with_its_place_in_the_year(self):
        self.assertEqual(calendar_view.describe(datetime.date(2026, 10, 17)),
                         "Saturday, 17 October 2026\nDay 290 of 365, week 42")
        self.assertIn("Day 60 of 366", calendar_view.describe(datetime.date(2028, 2, 29)))        # a leap year
        self.assertIn("Day 1 of 365", calendar_view.describe(datetime.date(2026, 1, 1)))


class CurrencyLogicTests(unittest.TestCase):
    def test_amounts_may_contain_commas_and_spaces(self):
        self.assertEqual(currency_converter.parse_amount("1,000.50"), 1000.5)
        self.assertEqual(currency_converter.parse_amount(" 42 "), 42)

    def test_things_that_are_not_amounts_are_refused(self):
        for text in ("", "abc", "1.2.3", "inf", "nan", None, "12 dollars"):
            with self.assertRaises(ValueError, msg=repr(text)):
                currency_converter.parse_amount(text)

    def test_currency_codes_are_tidied_and_checked(self):
        self.assertEqual(currency_converter.clean_code(" pkr "), "PKR")
        for text in ("", "US", "USDX", "12$", None):
            with self.assertRaises(ValueError, msg=repr(text)):
                currency_converter.clean_code(text)

    def test_results_are_formatted_for_reading(self):
        self.assertEqual(currency_converter.format_result(10, "USD", "PKR", 2770.0), "10.00 USD = 2,770.00 PKR")
        self.assertEqual(currency_converter.format_result(1000, "PKR", "USD", 3.61), "1,000.00 PKR = 3.61 USD")
        self.assertEqual(currency_converter.format_amount(0.25), "0.25")
        self.assertEqual(currency_converter.format_amount(1234567.891), "1,234,567.89")

    def test_the_common_list_has_no_repeats_and_includes_the_main_currencies(self):
        self.assertEqual(len(currency_converter.COMMON), len(set(currency_converter.COMMON)))
        for code in ("USD", "PKR", "EUR", "GBP"):
            self.assertIn(code, currency_converter.COMMON)


SMOKE = """
import sys
sys.path.insert(0, {root!r})
{body}
print("ok")
"""


class WindowSmokeTests(unittest.TestCase):
    def run_hidden(self, body):
        code = SMOKE.format(root=str(ROOT), body=body)
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=90)
        if "TclError" in result.stderr and "display" in result.stderr:
            self.skipTest("no display available for Tk")
        self.assertEqual(result.stdout.strip().splitlines()[-1:], ["ok"], result.stderr[-1500:])

    def test_the_calculator_window_builds_and_follows_the_keys(self):
        self.run_hidden("""
from gui.utils.calculator import Calculator
w = Calculator(); w.withdraw()
for key in "12": w.press(key)
w.press("\\u00d7"); w.press("7"); w.press("=")
assert w.display.cget("text") == "84", w.display.cget("text")
w.press("C"); assert w.display.cget("text") == "0"
w.press("7"); w.press("\\u00f7"); w.press("0"); w.press("=")
assert "zero" in w.display.cget("text")
w.destroy()
""")

    def test_the_calendar_window_builds_and_moves(self):
        self.run_hidden("""
import datetime
from gui.utils.calendar_view import CalendarWindow
w = CalendarWindow(today=datetime.date(2026, 10, 17)); w.withdraw()
assert w.title_label.cget("text") == "October 2026"
w.move(1); assert w.title_label.cget("text") == "November 2026"
w.go_today(); assert w.title_label.cget("text") == "October 2026"
w.select(24); assert "24 October 2026" in w.info.cget("text")
w.destroy()
""")

    def test_the_converter_window_builds_and_swaps(self):
        self.run_hidden("""
from gui.utils.currency_converter import CurrencyConverter
w = CurrencyConverter(); w.withdraw()
w.source.set("USD"); w.target.set("PKR"); w.swap()
assert (w.source.get(), w.target.get()) == ("PKR", "USD")
w.amount.delete(0, "end"); w.amount.insert(0, "abc"); w.convert()
assert "Enter a number" in w.status.cget("text"), w.status.cget("text")
w.destroy()
""")


if __name__ == "__main__":
    unittest.main()
