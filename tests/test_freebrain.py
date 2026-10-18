"""Tests for the free answer-anything layer:  python -m unittest tests.test_freebrain -v

No network: requests is replaced. Settings are patched, so a real key in .env never matters.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MainCode  # noqa: E402
from JarvisAdvancedBot import FreeBrain as F  # noqa: E402
from JarvisAdvancedBot import LocalBrain as L  # noqa: E402


class Reply:
    def __init__(self, data=None, status=200):
        self.status_code, self._data, self.ok = status, data, status < 400

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def chat(text):
    return Reply({"choices": [{"message": {"content": text}}]})


class BrainCase(unittest.TestCase):
    def setUp(self):
        F._history.clear()
        F._warned.clear()
        for patcher in (mock.patch.multiple(F.config, LLM_PROVIDER="auto", LLM_API_KEY="", LLM_MODEL="", LLM_BASE_URL="",
                                            USER_NAME="Mr Khan", DEFAULT_CITY="Peshawar"),
                        mock.patch("requests.get", side_effect=requests.ConnectionError())):    # no Ollama, no web
            patcher.start()
            self.addCleanup(patcher.stop)

    def with_key(self, key):
        patcher = mock.patch.object(F.config, "LLM_API_KEY", key)
        patcher.start()
        self.addCleanup(patcher.stop)


class ProviderChoiceTests(BrainCase):
    def test_the_service_is_recognised_from_the_key(self):
        for key, name, host in (("gsk_abc", "groq", "api.groq.com"), ("AIzaXYZ", "gemini", "generativelanguage.googleapis.com"),
                                ("sk-or-v1-q", "openrouter", "openrouter.ai")):
            with mock.patch.object(F.config, "LLM_API_KEY", key):
                found = F._provider()
            self.assertEqual(found[0], name)
            self.assertIn(host, found[1])

    def test_without_a_key_only_ollama_is_considered_and_only_if_it_is_running(self):
        self.assertEqual(F._provider()[0], "ollama")
        self.assertFalse(F.available())                                   # requests.get fails: Ollama isn't running
        with mock.patch("requests.get", return_value=Reply({"models": []})):
            self.assertTrue(F.available())

    def test_a_key_makes_it_available_without_asking_the_network(self):
        self.with_key("gsk_abc")
        self.assertTrue(F.available())

    def test_a_custom_service_needs_its_address_and_model(self):
        with mock.patch.multiple(F.config, LLM_PROVIDER="custom"):
            self.assertIsNone(F._provider())
        with mock.patch.multiple(F.config, LLM_PROVIDER="custom", LLM_BASE_URL="http://x/v1", LLM_MODEL="m", LLM_API_KEY="k"):
            self.assertEqual(F._provider(), ("custom", "http://x/v1", "m", "k"))

    def test_an_unknown_provider_name_is_not_available(self):
        with mock.patch.object(F.config, "LLM_PROVIDER", "nonsense"):
            self.assertFalse(F.available())


class AskModelTests(BrainCase):
    def test_the_question_goes_to_the_service_with_the_key_and_a_spoken_style_prompt(self):
        self.with_key("gsk_abc")
        with mock.patch("requests.post", return_value=chat("Because of Rayleigh scattering.")) as post:
            self.assertEqual(F.ask_model("why is the sky blue"), "Because of Rayleigh scattering.")
        url, = post.call_args[0]
        body = post.call_args[1]["json"]
        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(post.call_args[1]["headers"], {"Authorization": "Bearer gsk_abc"})
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "why is the sky blue"})
        self.assertIn("spoken aloud", body["messages"][0]["content"])
        self.assertIn("Mr Khan", body["messages"][0]["content"])

    def test_follow_up_questions_remember_the_conversation(self):
        self.with_key("gsk_abc")
        with mock.patch("requests.post", return_value=chat("Paris.")) as post:
            F.ask_model("capital of france")
            F.ask_model("and its population")
        roles = [m["content"] for m in post.call_args[1]["json"]["messages"][1:]]
        self.assertEqual(roles, ["capital of france", "Paris.", "and its population"])

    def test_markdown_and_thinking_are_removed_and_long_answers_cut(self):
        self.with_key("gsk_abc")
        with mock.patch("requests.post", return_value=chat("<think>hmm</think>**Sure**: `yes`, it is " + "very " * 300 + "good.")):
            answer = F.ask_model("q")
        self.assertTrue(answer.startswith("Sure: yes, it is very"))
        self.assertLessEqual(len(answer), F.MAX_REPLY_CHARS + 3)
        self.assertNotIn("think", answer)
        self.assertNotIn("*", answer)

    def test_each_failure_returns_none_and_explains_itself_once(self):
        self.with_key("gsk_abc")
        cases = ((requests.ConnectionError(), "couldn't reach groq"), (Reply(status=429), "free limit"),
                 (Reply(status=401), "rejected the key"), (Reply(status=500), "error 500"),
                 (Reply({"unexpected": 1}), "couldn't read"))
        for outcome, words in cases:
            F._warned.clear()
            out = []
            with mock.patch("requests.post", side_effect=[outcome, outcome]), mock.patch("builtins.print", side_effect=lambda *a: out.append(a[0])):
                self.assertIsNone(F.ask_model("q"))
                self.assertIsNone(F.ask_model("q"))
            self.assertEqual(len(out), 1, words)                         # reported once, not on every question
            self.assertIn(words, out[0])

    def test_ollama_needs_no_key_and_a_missing_model_is_explained(self):
        with mock.patch("requests.get", return_value=Reply({"models": []})), mock.patch("requests.post", return_value=chat("Hi.")) as post:
            self.assertEqual(F.ask_model("hello"), "Hi.")
        self.assertEqual(post.call_args[1]["headers"], {})
        self.assertIn("localhost:11434", post.call_args[0][0])
        out = []
        with mock.patch("requests.get", return_value=Reply({})), mock.patch("requests.post", return_value=Reply(status=404)), \
                mock.patch("builtins.print", side_effect=lambda *a: out.append(a[0])):
            self.assertIsNone(F.ask_model("hello"))
        self.assertIn("ollama pull", out[0])

    def test_nothing_is_sent_when_nothing_is_set_up(self):
        with mock.patch("requests.post") as post:
            self.assertIsNone(F.ask_model("hello"))
        post.assert_not_called()


class WebAnswerTests(BrainCase):
    def test_a_free_web_answer_is_shortened_to_two_sentences(self):
        data = {"AbstractText": "Python is a language. It is popular. It was made in 1991.", "Answer": ""}
        with mock.patch("requests.get", return_value=Reply(data)) as get:
            self.assertEqual(F.web_answer("what is python"), "Python is a language. It is popular.")
        self.assertEqual(get.call_args[1]["params"]["q"], "python")

    def test_no_answer_or_no_internet_is_none(self):
        with mock.patch("requests.get", return_value=Reply({"AbstractText": ""})):
            self.assertIsNone(F.web_answer("blorp"))
        self.assertIsNone(F.web_answer("blorp"))                          # the patched get raises ConnectionError

    def test_answer_prefers_the_model_then_the_web(self):
        with mock.patch.object(F, "ask_model", return_value="from the model"), mock.patch.object(F, "web_answer") as web:
            self.assertEqual(F.answer("q"), "from the model")
        web.assert_not_called()
        with mock.patch.object(F, "ask_model", return_value=None), mock.patch.object(F, "web_answer", return_value="from the web"):
            self.assertEqual(F.answer("q"), "from the web")


class LocalBrainIntegrationTests(BrainCase):
    def test_open_ended_questions_go_to_the_ai_before_wikipedia(self):
        self.with_key("gsk_abc")
        with mock.patch.object(L.T, "search_wikipedia") as wiki, mock.patch("requests.post", return_value=chat("A long answer.")):
            self.assertEqual(L.LocalReply("what is the best way to learn python"), "A long answer.")
        wiki.assert_not_called()

    def test_wikipedia_still_answers_when_there_is_no_ai(self):
        with mock.patch.object(L.T, "search_wikipedia", return_value="Alan Turing was a mathematician.") as wiki:
            self.assertIn("Turing", L.LocalReply("who is alan turing"))
        wiki.assert_called_once()

    def test_the_last_resort_suggests_real_commands_and_says_how_to_get_an_ai(self):
        with mock.patch.object(F, "web_answer", return_value=None):
            reply = MainCode._answer_anything("calculater please")
        self.assertIn("Did you mean", reply)
        self.assertIn("open calculator", reply)
        self.assertIn("LLM API KEY", reply)
        self.assertNotIn("don't know how to do that yet", reply)

    def test_no_setup_hint_when_an_ai_is_already_configured(self):
        self.with_key("gsk_abc")
        with mock.patch("requests.post", return_value=Reply(status=500)), mock.patch.object(F, "web_answer", return_value=None):
            reply = MainCode._answer_anything("blorp zzz")
        self.assertNotIn("LLM API KEY", reply)

    def test_suggestions_are_relevant_or_absent(self):
        self.assertIn("open calculator", L.suggest("calculater"))
        self.assertIn("take a note that buy milk", L.suggest("make a note"))
        self.assertEqual(L.suggest("qqqq zzzz"), [])


if __name__ == "__main__":
    unittest.main()
