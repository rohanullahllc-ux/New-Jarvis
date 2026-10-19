"""Tests for the settings readers in config.py:  python -m unittest tests.test_config -v"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


class SettingReaderTests(unittest.TestCase):
    def env(self, **values):
        return mock.patch.dict(os.environ, values)

    def test_whole_numbers_fractions_and_flags_are_read_and_nonsense_falls_back(self):
        with self.env(T_INT="7", T_FLOAT="1.75", T_BAD="slow", T_FLAG="yes", T_OFF="no"):
            self.assertEqual(config.number("T_INT", 1), 7)
            self.assertEqual(config.number("T_BAD", 1), 1)
            self.assertEqual(config.decimal("T_FLOAT", 1.3), 1.75)
            self.assertEqual(config.decimal("T_BAD", 1.3), 1.3)
            self.assertEqual(config.decimal("T_MISSING", 1.3), 1.3)
            self.assertTrue(config.flag("T_FLAG", False))
            self.assertFalse(config.flag("T_OFF", True))
            self.assertTrue(config.flag("T_MISSING", True))

    def test_spaces_around_a_setting_are_ignored(self):
        with self.env(T_PADDED="  8  "):
            self.assertEqual(config.number("T_PADDED", 1), 8)


class MicrophoneVolumeSettingTests(unittest.TestCase):
    def test_the_setting_is_always_a_percentage(self):
        self.assertTrue(0 <= config.MIC_VOLUME <= 100)

    def test_the_example_settings_explain_it_and_give_the_default(self):
        text = (config.BASE_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^MIC_VOLUME=80$")
        self.assertIn("0 = never touch", text)


class LocalAddressTests(unittest.TestCase):
    """On this Windows PC a connection to "localhost" waits two seconds for IPv6 to fail before trying IPv4."""

    def test_localhost_becomes_the_numeric_address(self):
        for written, expected in (("http://localhost:11434", "http://127.0.0.1:11434"),
                                  ("http://localhost", "http://127.0.0.1"),
                                  ("HTTP://LOCALHOST:11434/api", "HTTP://127.0.0.1:11434/api"),
                                  ("https://localhost/v1", "https://127.0.0.1/v1")):
            self.assertEqual(config.local_address(written), expected)

    def test_other_addresses_are_left_alone(self):
        for address in ("http://127.0.0.1:11434", "http://192.168.1.5:11434", "http://mylocalhost:5",
                        "http://localhost.example.com:1", "https://ollama.example.com"):
            self.assertEqual(config.local_address(address), address)

    def test_the_default_ollama_address_is_numeric_and_a_localhost_setting_is_rewritten(self):
        self.assertNotIn("localhost", config.OLLAMA_URL)
        self.assertEqual(config.local_address("http://localhost:11434".strip()), "http://127.0.0.1:11434")


if __name__ == "__main__":
    unittest.main()
