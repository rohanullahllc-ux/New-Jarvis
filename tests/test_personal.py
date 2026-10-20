"""Tests for the "what Jarvis calls you" touch:  python -m unittest tests.test_personal -v"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import personal  # noqa: E402
import speech  # noqa: E402
from tests import isolation  # noqa: E402


def setUpModule():
    isolation.no_natural_voice()


class AddressTests(unittest.TestCase):
    def test_the_default_word_leaves_the_text_exactly_as_it_is(self):
        for text in ("Ok sir, shutting down.", "Sir, your battery is low.", "Good evening sir. It's Monday.", "no title here"):
            self.assertEqual(personal.address(text, "sir"), text)

    def test_another_word_replaces_sir_and_keeps_the_capital_letter(self):
        self.assertEqual(personal.address("Ok sir, shutting down.", "boss"), "Ok boss, shutting down.")
        self.assertEqual(personal.address("Sir, your battery is low.", "boss"), "Boss, your battery is low.")
        self.assertEqual(personal.address("Yes, sir.", "ma'am"), "Yes, ma'am.")
        self.assertEqual(personal.address("Sir. Sir! sir?", "chief"), "Chief. Chief! chief?")

    def test_a_title_in_front_of_a_name_and_words_that_contain_sir_are_left_alone(self):
        self.assertEqual(personal.address("Sir Isaac Newton was born in 1643.", "boss"), "Sir Isaac Newton was born in 1643.")
        self.assertEqual(personal.address("A desire to win, a sirloin steak.", "boss"), "A desire to win, a sirloin steak.")

    def test_an_empty_choice_means_no_change(self):
        self.assertEqual(personal.address("Ok sir.", "  "), "Ok sir.")

    def test_the_setting_from_config_is_used_when_no_word_is_given(self):
        with mock.patch.object(config, "ADDRESS_AS", "captain"):
            self.assertEqual(personal.address("Ok sir."), "Ok captain.")


class SpeechUsesItTests(unittest.TestCase):
    """Everything Jarvis says goes through speech.py, so that is where the word is swapped."""

    def setUp(self):
        self.heard = []
        speech.add_listener(self.heard.append)
        self.addCleanup(speech.remove_listener, self.heard.append)
        patchers = [mock.patch.object(speech, "TTS_ENABLED", False), mock.patch.object(config, "ADDRESS_AS", "boss")]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_spoken_and_shown_text_use_the_chosen_word(self):
        with mock.patch("builtins.print"):
            speech.Speak("Ok sir, done.")
            speech.Show("Opening it, sir.")
        self.assertEqual(self.heard, ["Ok boss, done.", "Opening it, boss."])

    def test_a_reply_that_is_still_being_written_gets_it_sentence_by_sentence(self):
        with mock.patch("builtins.print"):
            speech.SpeakStream(["Certainly sir.", "It is done, sir."])
        self.assertEqual(self.heard, ["Certainly boss.", "It is done, boss."])


if __name__ == "__main__":
    unittest.main()
