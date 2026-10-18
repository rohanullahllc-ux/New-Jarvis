"""Tests for the offline unit converter:  python -m unittest tests.test_units -v"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import units  # noqa: E402


class ConversionTests(unittest.TestCase):
    def assertClose(self, got, expected, places=6):
        self.assertAlmostEqual(got, expected, places=places)

    def test_length(self):
        self.assertClose(units.convert(5, "miles", "kilometres"), 8.04672)
        self.assertClose(units.convert(1, "mile", "feet"), 5280)
        self.assertClose(units.convert(1, "inch", "centimetres"), 2.54)
        self.assertClose(units.convert(1, "nautical mile", "metres"), 1852)
        self.assertClose(units.convert(384400, "km", "nautical miles"), 207559.395248, places=3)

    def test_weight_and_volume(self):
        self.assertClose(units.convert(100, "kg", "pounds"), 220.462262, places=5)
        self.assertClose(units.convert(16, "ounces", "pound"), 1.0)
        self.assertClose(units.convert(3, "gallons", "litres"), 11.356235, places=5)
        self.assertClose(units.convert(1, "cup", "millilitres"), 236.5882365)

    def test_speed_area_and_time(self):
        self.assertClose(units.convert(36, "kilometres per hour", "metres per second"), 10)
        self.assertClose(units.convert(60, "mph", "kph"), 96.56064, places=5)
        self.assertClose(units.convert(1, "acre", "square metres"), 4046.8564224)
        self.assertClose(units.convert(2, "hours", "minutes"), 120)
        self.assertClose(units.convert(1, "week", "days"), 7)

    def test_temperature_is_not_just_a_factor(self):
        self.assertClose(units.convert(0, "celsius", "fahrenheit"), 32)
        self.assertClose(units.convert(100, "celsius", "fahrenheit"), 212)
        self.assertClose(units.convert(72, "fahrenheit", "celsius"), 22.222222, places=5)
        self.assertClose(units.convert(0, "celsius", "kelvin"), 273.15)
        self.assertClose(units.convert(-40, "fahrenheit", "celsius"), -40)

    def test_names_are_forgiving_about_case_spaces_and_spelling(self):
        self.assertClose(units.convert(1, " KM ", "Miles"), 0.621371, places=5)
        self.assertClose(units.convert(1, "kilometers", "meters"), 1000)

    def test_mixing_kinds_or_using_unknown_units_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "Kilograms and metres measure different things"):
            units.convert(1, "kilograms", "metres")
        with self.assertRaisesRegex(ValueError, "I don't know the unit parsec"):
            units.convert(1, "parsec", "metres")
        with self.assertRaises(ValueError):
            units.convert(1, "celsius", "metres")


class SentenceTests(unittest.TestCase):
    def test_a_conversion_is_said_as_a_sentence(self):
        self.assertEqual(units.sentence(5, "miles", "kilometres"), "5 miles is 8.0467 kilometres.")
        self.assertEqual(units.sentence(1, "mile", "feet"), "1 mile is 5,280 feet.")
        self.assertEqual(units.sentence(2.54, "centimetres", "inch"), "2.54 centimetres is 1 inch.")
        self.assertEqual(units.sentence(1, "metre", "kilometres"), "1 metre is 0.001 kilometres.")
        self.assertEqual(units.sentence(1234567, "metres", "kilometres"), "1,234,567 metres is 1,234.57 kilometres.")

    def test_numbers_are_neither_cluttered_nor_rounded_away(self):
        for value, text in ((8.04672, "8.0467"), (5280.0, "5,280"), (0.001, "0.001"), (1609.344, "1,609.34"), (0.5, "0.5"), (22.2222222, "22.2222")):
            self.assertEqual(units.format_number(value), text)


class PatternTests(unittest.TestCase):
    def test_the_pattern_has_no_groups_and_prefers_the_longest_unit(self):
        pattern = re.compile(units.pattern())
        self.assertEqual(pattern.groups, 0)
        self.assertEqual(pattern.fullmatch("miles per hour").group(), "miles per hour")
        self.assertEqual(pattern.fullmatch("nautical miles").group(), "nautical miles")
        self.assertIsNone(pattern.fullmatch("dollars"))

    def test_the_preposition_in_is_not_a_unit(self):
        self.assertNotIn("in", units.NAMES)                        # "5 miles in kilometres"


if __name__ == "__main__":
    unittest.main()
