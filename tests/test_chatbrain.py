"""Tests for the chat brain:  python -m unittest tests.test_chatbrain -v

No network and no Ollama: requests, the Ollama client and the web search are replaced, and the facts are kept in a
temporary folder. The real model is tried by hand (see README) because its answers differ from run to run.
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import ollama
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from JarvisAdvancedBot import ChatBrain as C  # noqa: E402


class Reply:
    def __init__(self, data=None, status=200):
        self.status_code, self._data = status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def pages(*pairs):
    """A Wikipedia generator=search answer for (title, text) pairs."""
    return {"query": {"pages": {str(n): {"title": t, "extract": x, "index": n} for n, (t, x) in enumerate(pairs, 1)}}}


def chunks(*pieces, reason="stop"):
    """What the Ollama client streams: one dict per piece of text, then a closing one."""
    return [{"message": {"content": p}, "done": False} for p in pieces] + [{"message": {"content": ""}, "done": True, "done_reason": reason}]


class FakeClient:
    """Stands in for ollama.Client: remembers each chat() call and streams what it was given."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream()

    def stream(self):
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        for item in step:
            if isinstance(item, BaseException):
                raise item
            yield item


class ChatCase(unittest.TestCase):
    models = [{"name": "big:3b", "size": 2_000_000_000}, {"name": "small:1b", "size": 1_000_000_000}]
    free_ram = 4_000_000_000
    running = []
    wikipedia = None

    def setUp(self):
        C._reset()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for patcher in (
            mock.patch.object(C, "FACTS_FILE", Path(folder.name) / "memory.json"),
            mock.patch.multiple(C.config, CHAT_ENGINE="auto", OLLAMA_MODEL="auto", OLLAMA_KEEP_ALIVE="10m", CHAT_MEMORY_TURNS=3,
                                CHAT_AUTO_MAX_MB=100_000,
                                CHAT_WEB_SEARCH=True, USER_NAME="Mr Khan", DEFAULT_CITY="Peshawar", OLLAMA_URL="http://ollama.test"),
            mock.patch.object(C.psutil, "virtual_memory", side_effect=lambda: SimpleNamespace(available=self.free_ram)),
            mock.patch("requests.get", side_effect=self.get),
            mock.patch("builtins.print"),                                        # the timing line each answer prints
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        search = mock.patch("ddgs.DDGS")                                       # never the real web search
        search.start().return_value.text.return_value = []
        self.addCleanup(search.stop)

    def get(self, url, **kwargs):
        if url.endswith("/api/tags"):
            return Reply({"models": self.models})
        if url.endswith("/api/ps"):
            sizes = {m["name"]: m["size"] for m in self.models}
            return Reply({"models": [{"name": name, "size": sizes[name]} for name in self.running]})
        if "wikipedia.org" in url:
            return Reply(self.wikipedia if self.wikipedia is not None else {"query": {}})
        raise requests.ConnectionError(url)

    def client(self, *script):
        fake = FakeClient(list(script))
        patcher = mock.patch.object(C, "_client", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def say(self, question):
        return list(C.reply_sentences(question))


class SplittingTests(unittest.TestCase):
    def test_sentences_end_at_a_full_stop_question_or_exclamation_followed_by_a_space(self):
        self.assertEqual(C.split_sentences("Hello there. How are you? Fine! And"), (["Hello there.", "How are you?", "Fine!"], "And"))

    def test_the_last_sentence_waits_until_something_follows_it(self):
        self.assertEqual(C.split_sentences("One. Two."), (["One."], "Two."))

    def test_titles_decimals_initials_and_list_numbers_do_not_end_a_sentence(self):
        for text in ("Dr. Khan is here. Next", "Pi is 3.14 roughly. Next", "It was written by J. K. Rowling. Next",
                     "1. Apples are red. Next", "The U.S. Army came. Next"):
            sentences, rest = C.split_sentences(text)
            self.assertEqual(len(sentences), 1, text)
            self.assertEqual(rest, "Next")

    def test_a_year_or_a_single_i_at_the_end_still_ends_the_sentence(self):
        self.assertEqual(C.split_sentences("It ended in 1945. Then it began. Next")[0], ["It ended in 1945.", "Then it began."])
        self.assertEqual(C.split_sentences("So do I. Next")[0], ["So do I."])

    def test_a_line_break_ends_a_sentence(self):
        self.assertEqual(C.split_sentences("First line\nSecond line\nThird")[0], ["First line", "Second line"])

    def test_quotes_after_the_full_stop_stay_with_the_sentence(self):
        self.assertEqual(C.split_sentences('He said "stop." Then left')[0], ['He said "stop."'])

    def test_a_long_reply_with_no_full_stop_is_cut_at_a_comma_so_speech_can_start(self):
        text = "word " * 20 + "and, " + "more " * 40
        early, rest = C._cut_long(text)
        self.assertTrue(early.endswith(","))
        self.assertLess(len(early), C.LONG_SENTENCE)
        self.assertTrue(rest.strip())
        self.assertEqual(C._cut_long("short"), ("", "short"))

    def test_markdown_and_list_bullets_are_not_read_aloud(self):
        self.assertEqual(C._speakable("**Bold** and `code` and # heading"), "Bold and code and heading")
        self.assertEqual(C._speakable("- first point"), "first point")
        self.assertEqual(C._speakable("2) second point"), "second point")


class ThinkingTests(unittest.TestCase):
    def feed(self, *pieces):
        hide = C._ThinkFilter()
        return "".join(hide.feed(p) for p in pieces) + hide.flush()

    def test_reasoning_is_hidden(self):
        self.assertEqual(self.feed("<think>let me see</think>The answer."), "The answer.")

    def test_tags_split_across_pieces_are_still_found(self):
        self.assertEqual(self.feed("Be", "fore <thi", "nk>hidden</th", "ink> after"), "Before  after")

    def test_a_less_than_sign_that_is_not_a_tag_is_kept(self):
        self.assertEqual(self.feed("3 < 5 and <b>bold</b>"), "3 < 5 and <b>bold</b>")

    def test_an_unfinished_thought_is_dropped_at_the_end(self):
        self.assertEqual(self.feed("Hi <think>never finished"), "Hi ")


class ModelChoiceTests(ChatCase):
    def test_the_biggest_model_that_fits_in_the_free_ram_is_chosen(self):
        self.assertEqual(C.choose_model(), "big:3b")                         # 2 GB x 1.25 + 0.3 GB fits in 4 GB

    def test_a_smaller_model_is_chosen_when_the_ram_is_short(self):
        self.free_ram = 2_000_000_000
        self.assertEqual(C.choose_model(), "small:1b")

    def test_if_nothing_fits_the_smallest_is_still_used(self):
        self.free_ram = 500_000_000
        self.assertEqual(C.choose_model(), "small:1b")

    def test_a_model_that_is_already_loaded_wins_because_loading_it_costs_no_more_ram(self):
        self.free_ram, self.running = 500_000_000, ["big:3b"]
        self.assertEqual(C.choose_model(), "big:3b")

    def test_automatic_choice_never_picks_a_model_too_big_to_be_quick_even_with_plenty_of_ram(self):
        self.free_ram = 8_000_000_000
        with mock.patch.object(C.config, "CHAT_AUTO_MAX_MB", 1600):
            self.assertEqual(C.choose_model(), "small:1b")                   # big:3b is 2.0 GB

    def test_the_limit_is_ignored_when_no_installed_model_is_small_enough(self):
        self.models = [{"name": "big:3b", "size": 2_000_000_000}, {"name": "bigger:7b", "size": 4_000_000_000}]
        with mock.patch.object(C.config, "CHAT_AUTO_MAX_MB", 1600):
            self.assertEqual(C.choose_model(), "big:3b")                     # the smallest there is

    def test_a_big_model_is_used_when_the_settings_name_it(self):
        with mock.patch.object(C.config, "CHAT_AUTO_MAX_MB", 1600), mock.patch.object(C.config, "OLLAMA_MODEL", "big:3b"):
            self.assertEqual(C.choose_model(), "big:3b")

    def test_a_big_model_already_loaded_does_not_get_around_the_limit(self):
        self.running = ["big:3b"]
        with mock.patch.object(C.config, "CHAT_AUTO_MAX_MB", 1600):
            self.assertEqual(C.choose_model(), "small:1b")

    def test_a_small_model_left_loaded_does_not_keep_a_bigger_one_out_when_that_would_now_fit(self):
        self.free_ram, self.running = 2_000_000_000, ["small:1b"]           # 2 GB free + the 1 GB the small one holds
        self.assertEqual(C.choose_model(), "big:3b")

    def test_but_a_bigger_one_that_would_not_fit_even_then_stays_out(self):
        self.free_ram, self.running = 1_000_000_000, ["small:1b"]
        self.assertEqual(C.choose_model(), "small:1b")

    def test_the_choice_does_not_flip_when_the_ram_changes_later(self):
        self.assertEqual(C.choose_model(), "big:3b")
        self.free_ram = 100_000_000
        self.assertEqual(C.choose_model(), "big:3b")

    def test_the_settings_can_name_the_model(self):
        with mock.patch.object(C.config, "OLLAMA_MODEL", "my-model:7b"):
            self.assertEqual(C.choose_model(), "my-model:7b")

    def test_embedding_models_are_not_chat_models(self):
        self.models = [{"name": "nomic-embed-text:latest", "size": 300_000_000}]
        self.assertFalse(C.available())
        self.assertIsNone(C.choose_model())

    def test_without_ollama_nothing_is_available(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertFalse(C.available())
            self.assertIsNone(C.choose_model())

    def test_cloud_only_switches_the_local_chat_off(self):
        with mock.patch.object(C.config, "CHAT_ENGINE", "cloud"):
            self.assertFalse(C.available())
            self.assertEqual(self.say("hello"), [])

    def test_a_removed_model_is_replaced_by_the_next_choice(self):
        self.assertEqual(C.choose_model(), "big:3b")
        self.models = [{"name": "small:1b", "size": 1_000_000_000}]
        self.assertEqual(C.choose_model(), "small:1b")


class StreamingTests(ChatCase):
    def test_sentences_come_out_one_by_one_as_they_complete(self):
        fake = self.client(chunks("Hello", " there.", " How", " are you?", " Fine"))
        self.assertEqual(self.say("hi"), ["Hello there.", "How are you?", "Fine"])
        call = fake.calls[0]
        self.assertEqual((call["model"], call["stream"], call["think"], call["keep_alive"]), ("big:3b", True, False, "10m"))
        self.assertEqual(call["options"]["num_ctx"], C.CONTEXT_TOKENS)

    def test_the_first_sentence_is_available_before_the_rest_has_arrived(self):
        gate = threading.Event()

        def pieces():
            yield {"message": {"content": "First sentence. Sec"}, "done": False}
            gate.wait(5)
            yield {"message": {"content": "ond."}, "done": False}
            yield {"message": {"content": ""}, "done": True}

        self.client(pieces())
        stream = C.reply_sentences("hi")
        self.assertEqual(next(stream), "First sentence.")                      # the model has not finished yet
        gate.set()
        self.assertEqual(list(stream), ["Second."])

    def test_the_prompt_carries_the_persona_the_user_and_the_question(self):
        fake = self.client(chunks("Hi."))
        self.say("how are things")
        system, user = fake.calls[0]["messages"][0], fake.calls[0]["messages"][-1]
        self.assertEqual(system["role"], "system")
        self.assertIn("Jarvis", system["content"])
        self.assertIn("Mr Khan", system["content"])
        self.assertIn("Peshawar", system["content"])
        self.assertEqual(user, {"role": "user", "content": "how are things"})

    def test_the_prompt_names_the_user_and_does_not_let_the_model_pretend_it_can_remember_or_act(self):
        prompt = C.system_prompt()
        self.assertIn("The user is Mr Khan; address them as sir", prompt)
        self.assertIn("never say you did something or will remember it", prompt)
        self.assertIn("'remember that'", prompt)

    def test_each_answer_keeps_a_line_saying_how_long_the_lookup_the_first_words_and_the_whole_answer_took(self):
        self.client(chunks("One. Two."))
        self.assertEqual(C.last_timing, "")
        self.say("hello there")
        self.assertRegex(C.last_timing, r"^: \(chat: big:3b - lookup \d+\.\ds, first words after \d+\.\ds, whole answer \d+\.\ds\)$")

    def test_there_is_no_timing_line_when_there_was_no_answer(self):
        self.client(ConnectionError("down"))
        with mock.patch("builtins.print"):
            self.say("hello there")
        self.assertEqual(C.last_timing, "")

    def test_the_system_prompt_has_no_clock_so_the_model_can_keep_reading_it_from_its_cache(self):
        self.assertNotRegex(C.system_prompt(), r"\d\d:\d\d")
        self.assertEqual(C.system_prompt(), C.system_prompt())

    def test_reasoning_markup_and_markdown_never_reach_the_listener(self):
        self.client(chunks("<think>hmm</think>**Sure**", ", it is `fine`."))
        self.assertEqual(self.say("is it fine"), ["Sure, it is fine."])

    def test_a_reply_cut_off_by_the_length_limit_loses_its_unfinished_fragment(self):
        self.client(chunks("A full sentence. And a fragment that never", reason="length"))
        self.assertEqual(self.say("tell me"), ["A full sentence."])

    def test_but_a_cut_off_reply_with_nothing_else_is_kept(self):
        self.client(chunks("Only a long fragment that never", reason="length"))
        self.assertEqual(self.say("tell me"), ["Only a long fragment that never"])

    def test_a_reply_without_any_full_stop_still_starts_speaking(self):
        self.client(chunks("word " * 30 + "and, " + "more " * 30))
        sentences = self.say("ramble")
        self.assertGreater(len(sentences), 1)
        self.assertLess(len(sentences[0]), C.LONG_SENTENCE)

    def test_the_stream_is_closed_if_the_listener_stops_early(self):
        closed = []

        class Stream:
            def __iter__(self):
                return self

            def __next__(self):
                return {"message": {"content": "One. Two. Three. "}, "done": False}

            def close(self):
                closed.append(True)

        fake = FakeClient([])
        fake.chat = lambda **kwargs: Stream()
        with mock.patch.object(C, "_client", return_value=fake):
            stream = C.reply_sentences("go on")
            next(stream)
            stream.close()
        self.assertEqual(closed, [True])


class EarlyStartTests(ChatCase):
    OPENING = "The sky appears blue because of a phenomenon called Rayleigh scattering,"

    def test_a_long_first_sentence_is_started_at_its_first_comma_after_fifty_characters(self):
        self.assertGreater(len(self.OPENING), C.EARLY_CHARS)
        self.client(chunks("The sky appears blue because of a phenomenon called Rayleigh scattering", ", where shorter waves", " scatter more.",
                           " Sunsets are red."))
        self.assertEqual(self.say("why is the sky blue"), [self.OPENING, "where shorter waves scatter more.", "Sunsets are red."])

    def test_a_comma_too_early_is_not_a_place_to_start(self):
        self.client(chunks("Well, it is a long story that goes on and on without any more pauses at all."))
        self.assertEqual(len(self.say("tell me")), 1)

    def test_the_early_start_only_applies_to_the_first_words_of_an_answer(self):
        self.client(chunks("Short one. A second sentence that is quite long indeed, and carries on for quite a while, until the end."))
        self.assertEqual(self.say("tell me"), ["Short one.", "A second sentence that is quite long indeed, and carries on for quite a while, until the end."])

    def test_cut_early_leaves_short_text_and_text_without_a_pause_alone(self):
        self.assertEqual(C._cut_early("Short, text"), ("", "Short, text"))
        self.assertEqual(C._cut_early("x" * 60 + " no pause here at all"), ("", "x" * 60 + " no pause here at all"))
        self.assertEqual(C._cut_early("x" * 55 + ", then more"), ("x" * 55 + ",", "then more"))


class MemoryTests(ChatCase):
    def test_a_follow_up_sees_the_earlier_turns(self):
        fake = self.client(chunks("Paris."), chunks("About two million."))
        self.say("tell me a city")
        self.say("and how big is it")
        roles = [(m["role"], m["content"]) for m in fake.calls[1]["messages"][1:]]
        self.assertEqual(roles, [("user", "tell me a city"), ("assistant", "Paris."), ("user", "and how big is it")])

    def test_at_the_limit_the_oldest_half_is_forgotten_in_one_go(self):
        """Sliding one pair per turn changed the start of the conversation every turn, so Ollama re-read all of it each time."""
        self.client(chunks("ok."))
        sizes_and_starts = []
        with mock.patch.object(C.config, "CHAT_MEMORY_TURNS", 4):
            for n in range(8):
                self.say(f"chat number {n}")
                sizes_and_starts.append((len(C._recent()) // 2, C._recent()[0]["content"]))
        self.assertEqual(sizes_and_starts, [
            (1, "chat number 0"), (2, "chat number 0"), (3, "chat number 0"), (4, "chat number 0"),     # growing: same start
            (2, "chat number 3"),                                                                       # over the limit: half goes
            (3, "chat number 3"), (4, "chat number 3"),                                                 # growing again: same start
            (2, "chat number 6"),
        ])

    def test_the_start_of_the_conversation_is_the_same_in_consecutive_requests_between_trims(self):
        fake = self.client(chunks("ok."))
        for n in range(4):
            self.say(f"chat number {n}")
        starts = [call["messages"][1]["content"] for call in fake.calls[1:]]            # the first message after the system prompt
        self.assertEqual(starts, ["chat number 0"] * 3)

    def test_a_tiny_limit_still_keeps_at_least_the_latest_pair(self):
        self.client(chunks("ok."))
        with mock.patch.object(C.config, "CHAT_MEMORY_TURNS", 2):
            for n in range(5):
                self.say(f"chat number {n}")
        self.assertGreaterEqual(len(C._recent()), 2)
        self.assertEqual(C._recent()[-2]["content"], "chat number 4")

    def test_forgetting_starts_a_fresh_conversation_but_keeps_the_facts(self):
        self.client(chunks("ok."))
        C.remember("my brother is Ali")
        self.say("hello")
        with mock.patch.object(C.FreeBrain, "forget") as cloud:
            C.forget()
        cloud.assert_called_once()
        self.assertEqual(C._recent(), [])
        self.assertEqual(C.facts(), ["my brother is Ali"])

    def test_a_failed_answer_is_not_remembered(self):
        self.client(ConnectionError("down"))
        with mock.patch("builtins.print"):
            self.say("hello")
        self.assertEqual(C._recent(), [])

    def test_every_question_carries_the_history_even_a_standalone_fact_so_each_request_starts_like_the_last(self):
        fake = self.client(chunks("Hi."), chunks("Rome."))
        self.say("hello there")
        self.say("What is the capital of Italy?")
        self.assertEqual([m["role"] for m in fake.calls[1]["messages"]], ["system", "user", "assistant", "user"])

    def test_the_throat_clearing_in_front_of_a_question_never_reaches_the_model_or_the_history(self):
        fake = self.client(chunks("Rome."))
        self.say("ok, I mean what is the capital of Italy")
        self.assertEqual(fake.calls[0]["messages"][-1]["content"], "what is the capital of Italy")
        self.assertEqual(C._recent()[0]["content"], "what is the capital of Italy")

    def test_the_time_is_given_to_the_model_only_for_questions_about_it(self):
        fake = self.client(chunks("It is evening."), chunks("Blue."))
        self.say("is it am or pm")
        self.say("why is the sky blue")
        self.assertRegex(fake.calls[0]["messages"][-1]["content"], r"^is it am or pm\n\(It is \d{1,2}:\d\d [AP]M on \w+ \d+ \w+ \d{4} right now\.\)$")
        self.assertEqual(fake.calls[1]["messages"][-1]["content"], "why is the sky blue")           # no clock: it isn't needed
        self.assertNotIn("right now", " ".join(m["content"] for m in C._recent()))                  # and it is never kept in the history

    def test_the_clock_goes_after_the_facts_and_the_question(self):
        fake = self.client(chunks("Moscow."))
        with mock.patch.object(C, "web_context", return_value="- Moscow: The capital of Russia."):
            self.say("what is the capital of Russia today")
        user = fake.calls[0]["messages"][-1]["content"]
        self.assertTrue(user.startswith("Facts you can use:\n- Moscow: The capital of Russia."))
        self.assertRegex(user, r"Question: what is the capital of Russia today\n\(It is ")

    def test_a_factual_follow_up_keeps_the_history(self):
        fake = self.client(chunks("Rome."), chunks("About three million."))
        self.say("What is the capital of Italy?")
        self.say("and its population?")
        self.assertEqual(len(fake.calls[1]["messages"]), 4)


class FactsTests(ChatCase):
    def test_facts_are_kept_between_runs_in_a_file(self):
        self.assertEqual(C.remember("  my brother's name is Ali. "), "my brother's name is Ali")
        self.assertEqual(C.facts(), ["my brother's name is Ali"])
        self.assertTrue(C.FACTS_FILE.exists())
        C._reset()
        self.assertEqual(C.facts(), ["my brother's name is Ali"])

    def test_the_same_fact_is_not_stored_twice(self):
        C.remember("I like tea")
        C.remember("i LIKE tea")
        self.assertEqual(C.facts(), ["I like tea"])

    def test_nothing_is_stored_for_an_empty_fact(self):
        self.assertEqual(C.remember(" ... "), "")
        self.assertEqual(C.facts(), [])

    def test_only_the_newest_facts_are_kept(self):
        for n in range(C.MAX_FACTS + 5):
            C.remember(f"fact number {n}")
        self.assertEqual(len(C.facts()), C.MAX_FACTS)
        self.assertEqual(C.facts()[-1], f"fact number {C.MAX_FACTS + 4}")

    def test_a_long_fact_is_shortened(self):
        C.remember("word " * 100)
        self.assertLessEqual(len(C.facts()[0]), C.MAX_FACT_CHARS)

    def test_facts_can_be_forgotten_by_what_they_mention(self):
        C.remember("my brother's name is Ali")
        C.remember("my sister's birthday is in March")
        self.assertEqual(C.forget_facts("that my brother is Ali"), 0)          # "is" and "that" are ignored but "brother's" differs
        self.assertEqual(C.forget_facts("my brother's name"), 1)
        self.assertEqual(C.facts(), ["my sister's birthday is in March"])

    def test_forgetting_with_only_filler_words_forgets_nothing(self):
        C.remember("I like tea")
        self.assertEqual(C.forget_facts("that is the"), 0)
        self.assertEqual(C.facts(), ["I like tea"])

    def test_everything_can_be_forgotten_at_once(self):
        C.remember("one fact")
        C.remember("another fact")
        self.assertEqual(C.forget_facts(), 2)
        self.assertEqual(C.facts(), [])
        self.assertEqual(C.forget_facts(), 0)

    def test_a_damaged_file_means_no_facts_rather_than_a_crash(self):
        C.FACTS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(C.facts(), [])
        C.FACTS_FILE.write_text('{"facts": 5}', encoding="utf-8")
        self.assertEqual(C.facts(), [])

    def test_remembered_facts_are_part_of_the_prompt(self):
        fake = self.client(chunks("Ali."))
        C.remember("my brother's name is Ali")
        self.say("what is my brother's name")
        self.assertIn("my brother's name is Ali", fake.calls[0]["messages"][0]["content"])


class LookupTests(ChatCase):
    def test_factual_questions_are_looked_up_and_chatty_ones_are_not(self):
        for question in ("Who wrote Hamlet?", "What's the capital of Australia", "how many moons does Mars have",
                         "when was the telephone invented", "what is the latest news", "and its population?"):
            self.assertTrue(C.needs_search(question), question)
        for question in ("how are you", "who are you", "what do you think about music", "tell me a joke", "explain gravity to a child",
                         "what is my brother's name", "I'm feeling tired", "write a poem about rain"):
            self.assertFalse(C.needs_search(question), question)

    def test_the_lookup_can_be_switched_off(self):
        with mock.patch.object(C.config, "CHAT_WEB_SEARCH", False):
            self.assertFalse(C.needs_search("Who wrote Hamlet?"))
            self.assertEqual(C.web_context("Who wrote Hamlet?"), "")

    def test_wikipedia_gives_the_facts_that_go_into_the_question(self):
        self.wikipedia = pages(("Hamlet", "A tragedy by William Shakespeare."), ("Hamlet (1996 film)", "A film by Kenneth Branagh."))
        fake = self.client(chunks("Shakespeare."))
        self.say("Who wrote Hamlet?")
        user = fake.calls[0]["messages"][-1]["content"]
        self.assertTrue(user.startswith("Facts you can use:\n- Hamlet: A tragedy by William Shakespeare.\n- Hamlet (1996 film)"))
        self.assertTrue(user.endswith("Question: Who wrote Hamlet?"))

    def test_the_facts_are_not_kept_in_the_conversation_history(self):
        self.wikipedia = pages(("Hamlet", "A tragedy by William Shakespeare."))
        self.client(chunks("Shakespeare."))
        self.say("Who wrote Hamlet?")
        self.assertEqual(C._recent()[0], {"role": "user", "content": "Who wrote Hamlet?"})

    def test_a_snippet_is_shortened(self):
        self.wikipedia = pages(("Long", "word " * 200))
        self.assertLessEqual(len(C.web_context("Who is long?")), C.SNIPPET_CHARS + 20)

    def test_a_follow_up_borrows_the_previous_question_for_the_search(self):
        self.client(chunks("Rome."), chunks("Millions."))
        self.say("What is the capital of Italy?")
        with mock.patch.object(C, "_wikipedia_snippets", return_value=["- x: y"]) as wiki:
            self.say("and its population?")
        self.assertEqual(wiki.call_args[0][0], "What is the capital of Italy and its population")

    def test_without_a_wikipedia_answer_or_for_news_the_web_search_is_used(self):
        results = [{"title": "Dawn", "body": "Top story today."}, {"title": "Empty", "body": ""}]
        with mock.patch("ddgs.DDGS") as search:
            search.return_value.text.return_value = results
            self.assertEqual(C.web_context("who is the mayor of Nowhereville"), "- Dawn: Top story today.")    # Wikipedia has nothing
            self.wikipedia = pages(("Pakistan", "A country."))
            self.assertEqual(C.web_context("what is the latest news"), "- Dawn: Top story today.")        # news skips Wikipedia

    def test_a_slow_web_search_is_abandoned_after_the_deadline(self):
        release = threading.Event()

        def slow(*args, **kwargs):
            release.wait(5)
            return []

        self.addCleanup(release.set)
        out = []
        with mock.patch("ddgs.DDGS") as search, mock.patch.object(C, "SEARCH_DEADLINE", 0.1), \
                mock.patch("builtins.print", side_effect=lambda *a: out.append(a[0])):
            search.return_value.text.side_effect = slow
            started = time.time()
            self.assertEqual(C.web_context("what is the latest news"), "")
        self.assertLess(time.time() - started, 2)
        self.assertIn("too slow", out[0])

    def test_a_broken_web_search_never_stops_the_chat_and_is_reported_once(self):
        out = []
        with mock.patch("ddgs.DDGS") as search, mock.patch("builtins.print", side_effect=lambda *a: out.append(a[0])):
            search.return_value.text.side_effect = RuntimeError("No results found.")
            self.assertEqual(C.web_context("what is the latest news"), "")
            self.assertEqual(C.web_context("what is the latest news"), "")
        self.assertEqual(len(out), 1)
        self.assertIn("No results found", out[0])

    def test_wikipedia_being_down_is_not_an_error(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError()), mock.patch("ddgs.DDGS") as search:
            search.return_value.text.return_value = []
            self.assertEqual(C.web_context("Who wrote Hamlet?"), "")


class TroubleTests(ChatCase):
    def noted(self, script):
        self.client(*script)
        out = []
        with mock.patch("builtins.print", side_effect=lambda *a: out.append(a[0])):
            sentences = self.say("hello")
            self.say("hello again")
        return sentences, out

    def test_ollama_not_running_gives_nothing_and_explains_once(self):
        sentences, out = self.noted([ConnectionError("refused")])
        self.assertEqual(sentences, [])
        self.assertEqual(len(out), 1)
        self.assertIn("Open it from the Start menu", out[0])

    def test_a_timeout_is_reported_the_same_way(self):
        sentences, out = self.noted([httpx.ConnectTimeout("slow")])
        self.assertEqual((sentences, len(out)), ([], 1))

    def test_a_missing_model_says_how_to_get_it_and_is_chosen_afresh_next_time(self):
        sentences, out = self.noted([ollama.ResponseError("model not found", 404)])
        self.assertEqual(sentences, [])
        self.assertIn("ollama pull big:3b", out[0])
        self.assertIsNone(C._model)

    def test_any_other_server_error_is_reported(self):
        _, out = self.noted([ollama.ResponseError("out of memory", 500)])
        self.assertIn("out of memory", out[0])

    def test_trouble_in_the_middle_keeps_what_was_already_said(self):
        self.client([{"message": {"content": "Good start. Then it"}, "done": False}, ConnectionError("dropped")])
        with mock.patch("builtins.print"):
            self.assertEqual(self.say("hello"), ["Good start."])
        self.assertEqual(C._recent()[-1]["content"], "Good start.")

    def test_bugs_in_our_own_code_are_not_hidden_as_network_trouble(self):
        self.client([{"message": {"content": "Hi."}, "done": False}, {"unexpected": 1}])
        with self.assertRaises(KeyError):
            self.say("hello")


class FragmentTests(unittest.TestCase):
    def test_sentences_that_stop_in_the_middle_are_recognised(self):
        for said in ("can you", "could you please", "tell me the square root of", "cube root of", "i live in", "what is your",
                     "tell me about the", "how", "ok can you", "what's", "show me", "and", "between earth and"):
            self.assertTrue(C.is_fragment(C.clean_question(said)), said)

    def test_whole_sentences_are_not_mistaken_for_fragments(self):
        for said in ("what can you do", "how are you", "thank you", "i dont know why", "what is that", "who are you", "tell me a joke",
                     "where is the moon", "why is the sky blue", "i want to go home", "that's what it is", "do you know me"):
            self.assertFalse(C.is_fragment(C.clean_question(said)), said)

    def test_nothing_at_all_counts_as_a_fragment(self):
        self.assertTrue(C.is_fragment(""))
        self.assertTrue(C.is_fragment("   ..."))


class CleaningTests(unittest.TestCase):
    def test_leading_throat_clearing_is_removed(self):
        self.assertEqual(C.clean_question("ok how much is there distance"), "how much is there distance")
        self.assertEqual(C.clean_question("Okay, hey Jarvis, what time is it"), "what time is it")
        self.assertEqual(C.clean_question("I mean the nearest planet"), "the nearest planet")
        self.assertEqual(C.clean_question("no I mean cube root of 8"), "cube root of 8")
        self.assertEqual(C.clean_question("assistant, why is the sky blue"), "why is the sky blue")
        self.assertEqual(C.clean_question("i told you the nearest planet"), "the nearest planet")

    def test_words_that_carry_meaning_are_kept(self):
        for said in ("and its population", "but you open calculator", "so what now", "well done", "ok"):
            self.assertEqual(C.clean_question(said), said if said != "ok" else "ok")

    def test_a_question_that_is_only_filler_is_left_alone(self):
        self.assertEqual(C.clean_question("okay"), "okay")


class CompleteTests(ChatCase):
    """One quick answer from the model, for jobs like translating."""

    def test_it_returns_the_models_words_tidied_with_no_memory_and_no_lookup(self):
        fake = self.client(chunks("unused"))
        fake.chat = lambda **kwargs: (fake.calls.append(kwargs) or {"message": {"content": "  Comment   allez-vous ?\n"}})
        self.assertEqual(C.complete("You translate.", "how are you"), "Comment allez-vous ?")
        call = fake.calls[0]
        self.assertEqual([m["role"] for m in call["messages"]], ["system", "user"])
        self.assertEqual(call["options"]["temperature"], 0)
        self.assertIs(call["think"], False)
        self.assertEqual(C._recent(), [])                                       # not part of the conversation

    def test_without_a_model_or_when_it_fails_it_returns_none(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertIsNone(C.complete("s", "u"))
        fake = self.client(chunks("unused"))
        fake.chat = lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
        with mock.patch("builtins.print"):
            self.assertIsNone(C.complete("s", "u"))

    def test_an_empty_answer_is_none(self):
        fake = self.client(chunks("unused"))
        fake.chat = lambda **kwargs: {"message": {"content": "   "}}
        self.assertIsNone(C.complete("s", "u"))


class LoadedTests(ChatCase):
    def test_a_model_in_ram_is_loaded_and_one_that_is_not_is_not(self):
        self.running = ["big:3b"]
        self.assertTrue(C.is_loaded())
        C._reset()
        self.running = ["small:1b"]
        self.assertFalse(C.is_loaded())                                  # the model chosen is big:3b, which is not in RAM

    def test_without_ollama_nothing_is_loaded(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError()):
            self.assertFalse(C.is_loaded())


class WarmUpTests(ChatCase):
    def test_warm_up_loads_the_model_without_asking_anything(self):
        fake = self.client(chunks("unused"))
        C.warm_up()
        self.assertEqual(fake.calls[0]["messages"], [])
        self.assertEqual(fake.calls[0]["model"], "big:3b")

    def test_warm_up_never_raises(self):
        with mock.patch.object(C, "_client", side_effect=RuntimeError("boom")):
            C.warm_up()
        with mock.patch("requests.get", side_effect=requests.ConnectionError()):
            C.warm_up()


if __name__ == "__main__":
    unittest.main()
