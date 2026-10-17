"""Tests for the shared exchange-rate helper:  python -m unittest tests.test_rates -v"""
import time
import unittest

import requests

from tests.tools_support import FakeResponse, ToolCase

import rates  # noqa: E402


class RateTests(ToolCase):
    def serve(self, table=None, **kwargs):
        self.http.routes = [("open.er-api.com", FakeResponse({"result": "success", "rates": table or {"PKR": 277.0, "EUR": 0.9}}, **kwargs))]

    def test_conversion_multiplies_by_the_rate(self):
        self.serve()
        self.assertAlmostEqual(rates.convert(10, "usd", " pkr "), 2770.0)
        self.assertEqual(self.http.urls(), ["https://open.er-api.com/v6/latest/USD"])

    def test_rates_are_remembered_for_an_hour(self):
        self.serve()
        rates.convert(1, "USD", "PKR")
        rates.convert(2, "USD", "EUR")
        self.assertEqual(len(self.http.calls), 1)
        rates._cache["USD"] = (time.time() - 3601, rates._cache["USD"][1])
        rates.convert(1, "USD", "PKR")
        self.assertEqual(len(self.http.calls), 2)

    def test_the_list_of_codes_is_sorted(self):
        self.serve({"PKR": 1, "EUR": 1, "AED": 1})
        self.assertEqual(rates.codes(), ["AED", "EUR", "PKR"])

    def test_only_three_letter_codes_are_looked_up(self):
        for bad in ("", "US", "USDX", "12$", None):
            with self.assertRaises(rates.RateError):
                rates.rates(bad)
        self.assertEqual(self.http.calls, [])

    def test_an_unknown_target_currency(self):
        self.serve()
        with self.assertRaises(rates.RateError) as caught:
            rates.convert(1, "USD", "zzz")
        self.assertIn("USD to ZZZ", str(caught.exception))

    def test_every_kind_of_failure_has_a_readable_message(self):
        cases = ((requests.Timeout(), "too long"), (requests.ConnectionError(), "couldn't reach"),
                 (FakeResponse({}, 500), "couldn't read"), (FakeResponse(None, text="<html>"), "couldn't read"),
                 (FakeResponse({"result": "error", "error-type": "unsupported-code"}), "couldn't get exchange rates for ZZZ"))
        for response, words in cases:
            rates._cache.clear()
            self.http.routes = [("open.er-api.com", response)]
            with self.assertRaises(rates.RateError) as caught:
                rates.rates("ZZZ")
            self.assertIn(words, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
