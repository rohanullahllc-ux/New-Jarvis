"""Tests for the helper scripts in training/:  python -m unittest tests.test_training_tools -v

No Ollama and no network: requests is replaced.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training import speedtest_models as S  # noqa: E402


class FakeStream:
    """What requests.post(..., stream=True) returns: a context manager whose iter_lines yields JSON lines."""

    def __init__(self, chunks):
        self.lines = [json.dumps(c).encode() for c in chunks]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self.lines)


def say(*pieces, tokens=10, seconds=2.0):
    chunks = [{"message": {"content": p}, "done": False} for p in pieces]
    return FakeStream(chunks + [{"message": {"content": ""}, "done": True, "eval_count": tokens, "eval_duration": int(seconds * 1e9)}])


class SentenceTests(unittest.TestCase):
    def test_the_end_of_a_sentence_is_a_full_stop_question_or_exclamation_followed_by_a_space_or_the_end(self):
        for text in ("Hello there.", "Really? Yes", "Wow! ", "One. Two"):
            self.assertTrue(S.SENTENCE_END.search(text), text)

    def test_decimals_and_abbreviation_free_text_do_not_end_a_sentence_early(self):
        for text in ("Pi is 3.14", "version 2.5.1 is", "no punctuation yet"):
            self.assertFalse(S.SENTENCE_END.search(text), text)


class TimingTests(unittest.TestCase):
    def test_one_answer_reports_first_word_first_sentence_and_speed(self):
        with mock.patch("requests.post", return_value=say("Hamlet was", " written by", " Shakespeare. ", "He lived", tokens=40, seconds=8)):
            first_word, first_sentence, speed = S.time_one_answer("http://x", "m", "who wrote hamlet")
        self.assertGreaterEqual(first_sentence, first_word)
        self.assertAlmostEqual(speed, 5.0)

    def test_an_answer_with_no_full_stop_still_reports_a_time(self):
        with mock.patch("requests.post", return_value=say("just", " words", tokens=2, seconds=1)):
            first_word, first_sentence, _ = S.time_one_answer("http://x", "m", "q")
        self.assertGreater(first_sentence, 0)

    def test_the_model_is_loaded_tested_and_then_unloaded(self):
        calls = []

        def post(url, json=None, **kw):
            calls.append((url.rsplit("/", 1)[-1], json))
            return say("Fine. ") if url.endswith("/chat") and json["messages"] else mock.Mock(raise_for_status=lambda: None)

        with mock.patch("requests.post", side_effect=post):
            result = S.test_model("http://x", "tiny:1b", prompts=("a", "b"))
        self.assertEqual(result["model"], "tiny:1b")
        self.assertEqual(calls[0][1]["messages"], [])                               # load with no question
        self.assertEqual(calls[-1], ("generate", {"model": "tiny:1b", "keep_alive": 0}))     # unload at the end
        self.assertEqual(len(calls), 4)


class RecommendationTests(unittest.TestCase):
    def results(self, **timings):
        return [{"model": name, "first_sentence": seconds} for name, seconds in timings.items()]

    def test_the_biggest_model_that_is_quick_enough_wins(self):
        sizes = {"small": 1, "medium": 2, "large": 3}
        self.assertEqual(S.recommend(self.results(small=2, medium=6, large=20), sizes, limit=8), "medium")

    def test_if_none_is_quick_enough_the_quickest_is_recommended(self):
        sizes = {"a": 1, "b": 2}
        self.assertEqual(S.recommend(self.results(a=15, b=30), sizes, limit=8), "a")

    def test_no_results_means_no_recommendation(self):
        self.assertIsNone(S.recommend([], {}))


class OllamaListTests(unittest.TestCase):
    def test_installed_models_come_back_with_their_sizes(self):
        reply = mock.Mock(raise_for_status=lambda: None, json=lambda: {"models": [{"name": "a:1b", "size": 7}, {"name": "b:3b"}]})
        with mock.patch("requests.get", return_value=reply):
            self.assertEqual(S.installed_models("http://x"), [("a:1b", 7), ("b:3b", 0)])

    def test_ollama_not_running_is_none_and_the_script_says_how_to_start_it(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertIsNone(S.installed_models("http://x"))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(S.main([]), 1)
        self.assertIn("isn't running", out.getvalue())

    def test_no_models_installed_says_how_to_get_one(self):
        out = io.StringIO()
        with mock.patch.object(S, "installed_models", return_value=[]), redirect_stdout(out):
            self.assertEqual(S.main([]), 1)
        self.assertIn("ollama pull", out.getvalue())


if __name__ == "__main__":
    unittest.main()
