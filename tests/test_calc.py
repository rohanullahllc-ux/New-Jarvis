"""Tests for the calculator engine and keypad:  python -m unittest tests.test_calc -v"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import calc  # noqa: E402
from calc import Keypad  # noqa: E402

TIMES, DIVIDE, MINUS, DELETE, SIGN = "×", "÷", "−", "⌫", "±"


class EvaluateTests(unittest.TestCase):
    def test_plain_arithmetic(self):
        for text, value in (("2+3*4", 14), ("(2+3)*4", 20), ("10/4", 2.5), ("7%3", 1), ("2**10", 1024), ("-5+2", -3),
                            ("sqrt(144)", 12), ("sqrt(2)*sqrt(2)", 2.0000000000000004), ("  1 + 1  ", 2)):
            self.assertEqual(calc.evaluate(text), value, text)

    def test_nothing_else_is_ever_executed(self):
        for text in ("__import__('os').system('echo hi')", "open('x')", "os", "1+x", "'a'*3", "[1,2]", "lambda: 1",
                     "abs(-1)", "sqrt(1, 2)", "sqrt(x=4)", "True+1", "1 if 1 else 2", "print(1)", "", "2+", "((("):
            with self.assertRaises(ValueError, msg=text):
                calc.evaluate(text)

    def test_every_failure_is_a_value_error_with_a_reason(self):
        for text, reason in (("1/0", "division by zero"), ("2**1000", "exponent too large"), ("1e308*10", None),
                             ("sqrt(-1)", None), ("5%0", "division by zero")):
            with self.assertRaises(ValueError) as caught:
                calc.evaluate(text)
            if reason:
                self.assertIn(reason, str(caught.exception))

    def test_calculator_keys_become_python(self):
        self.assertEqual(calc.from_keys(f"12{TIMES}3{DIVIDE}4{MINUS}1^2"), "12*3/4-1**2")
        self.assertEqual(calc.evaluate(calc.from_keys(f"200{TIMES}50%")), 100)
        self.assertEqual(calc.from_keys("50%"), "(50/100)")

    def test_numbers_are_shown_the_way_a_calculator_shows_them(self):
        for value, text in ((4.0, "4"), (0.1 + 0.2, "0.3"), (2.5, "2.5"), (1 / 3, "0.333333333333"), (10 ** 20, "100000000000000000000"),
                            (1e20, "1e+20"), (-7, "-7"), (1234567.0, "1234567")):
            self.assertEqual(calc.format_display(value), text)
        for bad in (math.inf, math.nan):
            with self.assertRaises(ValueError):
                calc.format_display(bad)


def keys(*presses):
    pad = Keypad()
    for key in presses:
        pad.press(key)
    return pad


class KeypadTests(unittest.TestCase):
    def test_a_sum(self):
        pad = keys("1", "2", TIMES, "7", "=")
        self.assertEqual((pad.expression, pad.history), ("84", f"12{TIMES}7"))

    def test_decimal_sums_do_not_show_floating_point_noise(self):
        self.assertEqual(keys("0", ".", "1", "+", "0", ".", "2", "=").expression, "0.3")

    def test_the_display_shows_zero_when_empty(self):
        self.assertEqual(Keypad().display, "0")

    def test_the_preview_shows_the_answer_before_equals(self):
        self.assertEqual(keys("2", "+", "3").preview, "5")
        self.assertEqual(keys("2", "+").preview, "")
        self.assertEqual(keys("2", "+", "3", "=").preview, "")           # already showing the result

    def test_an_operator_after_a_result_carries_on_from_it(self):
        self.assertEqual(keys("2", "+", "3", "=", TIMES, "4", "=").expression, "20")

    def test_a_digit_after_a_result_starts_a_new_sum(self):
        self.assertEqual(keys("2", "+", "3", "=", "9").expression, "9")

    def test_a_second_operator_replaces_the_first(self):
        self.assertEqual(keys("5", "+", TIMES, "2").expression, f"5{TIMES}2")

    def test_minus_after_a_times_sign_is_a_negative_number(self):
        pad = keys("5", TIMES, MINUS, "3", "=")
        self.assertEqual(pad.expression, f"{MINUS}15")

    def test_only_one_decimal_point_per_number(self):
        self.assertEqual(keys("1", ".", "2", ".", "3").expression, "1.23")
        self.assertEqual(keys("1", ".", "5", "+", "2", ".", "5").expression, "1.5+2.5")

    def test_percent(self):
        self.assertEqual(keys("2", "0", "0", TIMES, "5", "0", "%", "=").expression, "100")
        self.assertEqual(keys("%").expression, "")                       # nothing to take a percent of
        self.assertEqual(keys("5", "+", "%").expression, "5+")

    def test_plus_minus_flips_the_number_being_typed(self):
        self.assertEqual(keys("8", SIGN).expression, f"{MINUS}8")
        self.assertEqual(keys("8", SIGN, SIGN).expression, "8")
        self.assertEqual(keys("5", MINUS, "3", SIGN, "=").expression, "8")       # 5 - (-3)
        self.assertEqual(keys("5", TIMES, "3", SIGN).expression, f"5{TIMES}{MINUS}3")
        self.assertEqual(keys(SIGN).expression, MINUS)

    def test_clear_and_backspace(self):
        self.assertEqual(keys("1", "2", DELETE).expression, "1")
        self.assertEqual(keys("1", "2", "C").expression, "")
        self.assertEqual(keys(DELETE).expression, "")

    def test_dividing_by_zero_is_explained_and_the_next_key_starts_over(self):
        pad = keys("7", DIVIDE, "0", "=")
        self.assertEqual(pad.display, "Can't divide by zero")
        pad.press("4")
        self.assertEqual((pad.error, pad.expression), ("", "4"))

    def test_an_unfinished_sum_gives_an_error_not_a_crash(self):
        self.assertEqual(keys("5", "+", "=").display, "Error")
        self.assertEqual(keys("=").display, "0")

    def test_a_lone_minus_cannot_take_an_operator(self):
        self.assertEqual(keys(MINUS, "+").expression, MINUS)
        self.assertEqual(keys(MINUS, "5").expression, f"{MINUS}5")

    def test_results_larger_than_a_calculator_can_show(self):
        pad = keys(*"9" * 3, "^", *"999", "=")
        self.assertEqual(pad.display, "Error")


if __name__ == "__main__":
    unittest.main()
