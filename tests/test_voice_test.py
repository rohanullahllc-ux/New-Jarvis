"""Tests for the helper that scores the live voice test:  python -m unittest tests.test_voice_test -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import voice_test  # noqa: E402


class SameWordsTests(unittest.TestCase):
    def test_small_differences_that_do_not_matter_are_not_mistakes(self):
        for heard, wanted in (("Set a timer for 2 minutes.", "set a timer for two minutes"), ("Okay, open the task folder", "ok open the task folder"),
                              ("Set the microphone volume to 80.", "set the microphone volume to eighty"), ("What time is it?", "what time is it")):
            self.assertTrue(voice_test.same_words(heard, wanted), heard)

    def test_real_differences_are_mistakes(self):
        for heard, wanted in (("add a task by milk", "add a task buy milk"), ("show my note", "show my notes"), ("", "what time is it"),
                              (None, "what time is it"), ("open the test folder", "open the task folder")):
            self.assertFalse(voice_test.same_words(heard, wanted), heard)

    def test_ten_sentences_are_asked(self):
        self.assertEqual(len(voice_test.SENTENCES), 10)


if __name__ == "__main__":
    unittest.main()
