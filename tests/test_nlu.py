"""Tests for Jarvis's own language model: the runtime (JarvisAdvancedBot/NLU.py), the phrase bank and the trainer (training/).

    python -m unittest tests.test_nlu -v

A tiny model is trained on a few phrases in the tests that need one (a second or two). Nothing here touches the real
models/nlu.joblib, the real Logs folder or the network.
"""
import json
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from JarvisAdvancedBot import LocalBrain, NLU  # noqa: E402
from training import nlu_phrases as P  # noqa: E402
from training import train_nlu as T  # noqa: E402

GENERIC_HANDLERS = {"knowledge", "open_something", "close_something", "google", "youtube_play", "calculate", "wolfram"}


def first_handler(command):
    """The name of the pattern handler LocalBrain would run for this command."""
    text = LocalBrain._canonical(LocalBrain.normalize(command))
    return next((handler.__name__ for pattern, handler in LocalBrain.INTENTS if pattern.search(text)), None)


def tiny_bank():
    """A few kinds of request with their real phrases, and some chat: enough to train in about a second."""
    bank = P.load()
    kinds = ("time", "date", "screenshot", "joke", "volume_up", "weather")
    small = {kind: bank[kind][:24] for kind in kinds}
    small[NLU.CHAT] = bank[NLU.CHAT][:90]
    return small


class FamilyTests(unittest.TestCase):
    def test_every_command_the_model_can_choose_is_one_localbrain_really_understands(self):
        for name, family in NLU.FAMILIES.items():
            with self.subTest(name):
                self.assertTrue(LocalBrain.understands(family.command), family.command)
                self.assertNotIn(first_handler(family.command), GENERIC_HANDLERS, family.command)

    def test_only_the_awkward_to_undo_commands_ask_first(self):
        self.assertEqual({name for name, family in NLU.FAMILIES.items() if family.ask}, {"forget_facts", "email", "lock_screen"})
        for family in NLU.FAMILIES.values():
            self.assertTrue(not family.ask or family.ask.endswith("Say yes or no."))

    def test_shutting_down_and_restarting_ask_by_themselves_and_stop_on_no(self):
        with mock.patch.object(LocalBrain.T, "system_power_action", side_effect=AssertionError("must not run")) as power:
            for name in ("shutdown", "restart"):
                questions = []
                reply = LocalBrain.LocalReply(NLU.FAMILIES[name].command, ask=lambda q: questions.append(q) or "no")
                self.assertIn("Are you sure", questions[0])
                self.assertTrue(reply.startswith("Okay, I won't"), reply)
            power.assert_not_called()


class BankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = P.load()

    def test_the_real_phrase_files_cover_every_kind_of_request(self):
        self.assertEqual(P.missing(self.bank), [])
        self.assertEqual(set(self.bank), set(NLU.FAMILIES) | {NLU.CHAT})
        for name, phrases in self.bank.items():
            self.assertGreaterEqual(len(phrases), 20, name)
        self.assertGreater(len(self.bank[NLU.CHAT]), 300)

    def test_a_mistake_in_a_phrase_file_is_reported_with_the_file_and_line(self):
        with tempfile.TemporaryDirectory() as folder:
            def write(text):
                (Path(folder) / "a.txt").write_text(text, encoding="utf-8")
                return P.load(folder)

            with self.assertRaisesRegex(ValueError, r"a\.txt line 1.*not a kind of request"):
                write("## make_coffee\nbrew me one\n")
            with self.assertRaisesRegex(ValueError, "before any"):
                write("hello there\n")
            with self.assertRaisesRegex(ValueError, "both 'greet' and 'thanks'"):
                write("## greet\nhello\n## thanks\nHello\n")
            self.assertEqual(write("# a comment\n\n## greet\nhello\nhello\n  Hi   There \n"), {"greet": ["hello", "hi there"]})

    def test_the_held_back_phrasings_are_never_ones_the_model_learned_from(self):
        train, test = P.split(self.bank)
        self.assertEqual(set(train), set(test))
        for name in train:
            self.assertFalse(set(train[name]) & set(test[name]), name)
            self.assertTrue(test[name] and train[name], name)
            self.assertEqual(sorted(train[name] + test[name]), sorted(self.bank[name]))
        self.assertEqual(P.split(self.bank), P.split(self.bank))                    # the same split every time

    def test_place_blanks_are_filled_with_several_different_places(self):
        out = P.concrete(["weather in {place}", "what time is it"], random.Random(1), per_template=4)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[-1], "what time is it")
        self.assertEqual(len({sentence for sentence in out if "weather" in sentence}), 4)
        self.assertFalse(any("{" in sentence for sentence in out))

    def test_noisy_versions_keep_the_meaning_words_and_are_repeatable(self):
        self.assertEqual(P.variants("take a screenshot", random.Random(5), 6), P.variants("take a screenshot", random.Random(5), 6))
        made = P.variants("take a screenshot", random.Random(5), 40)
        self.assertEqual(made[0], "take a screenshot")
        self.assertGreater(len(set(made)), 15)
        self.assertTrue(all(sentence.strip() for sentence in made))
        self.assertGreater(sum("screen" in sentence for sentence in made), 30)

    def test_made_up_chat_is_ordinary_questions_that_no_command_claims(self):
        sentences = P.made_up_chat(random.Random(3), 200)
        self.assertEqual(len(sentences), 225)
        self.assertGreater(len(set(sentences)), 100)
        for sentence in sentences:
            self.assertFalse(LocalBrain.understands(sentence), sentence)

    def test_real_sentences_load_with_their_meaning_and_stay_out_of_the_training_phrases(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "real.txt"
            path.write_text("# a comment\ngreet\tis jarvis up and running\n\nchat\t  Why is the SKY blue \nno tab here\n", encoding="utf-8")
            self.assertEqual(P.real_utterances(path), [("greet", "is jarvis up and running"), ("chat", "why is the sky blue")])
        self.assertEqual(P.real_utterances(Path("no such file")), [])
        real = P.real_utterances()                                           # the user's own file, when this PC has one
        trained_on = {phrase for phrases in P.without_real(self.bank, real).values() for phrase in phrases}
        for kind, sentence in real:
            self.assertIn(kind, set(NLU.FAMILIES) | {NLU.CHAT})
            self.assertNotIn(sentence, trained_on)

    def test_a_real_sentence_that_is_also_a_phrase_is_taken_out_of_the_training(self):
        bank = {"am_pm": ["am or pm", "is it am or pm"], "chat": ["why is the sky blue"]}
        left = P.without_real(bank, [("am_pm", "is it am or pm"), ("chat", "something else")])
        self.assertEqual(left, {"am_pm": ["am or pm"], "chat": ["why is the sky blue"]})
        self.assertEqual(bank["am_pm"], ["am or pm", "is it am or pm"])        # the bank itself is not changed


class FakePipeline:
    """Stands in for the trained model: answers from a table, so the runtime rules can be tested exactly."""
    classes_ = ["chat", "time", "weather", "lock_screen", "mystery"]

    def __init__(self, table):
        self.table = table

    def predict_proba(self, texts):
        return [self.table.get(text, [1, 0, 0, 0, 0]) for text in texts]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = mock.patch.object(NLU, "MODEL_FILE", Path(self.folder.name) / "nlu.joblib")
        patcher.start()
        self.addCleanup(patcher.stop)
        NLU.reset()
        self.addCleanup(NLU.reset)

    def use(self, table, **settings):
        NLU._bundle = {"pipeline": FakePipeline(table), **settings}

    def test_a_sure_guess_becomes_the_command_to_run(self):
        self.use({"got the time": [0.02, 0.95, 0.01, 0.01, 0.01]})
        guess = NLU.interpret("got the time")
        self.assertEqual((guess.family, guess.command, guess.ask), ("time", "what time is it", ""))
        self.assertAlmostEqual(guess.confidence, 0.95)

    def test_chat_a_weak_guess_or_a_close_second_place_do_nothing(self):
        self.use({"why is the sky blue": [0.97, 0.01, 0.01, 0.0, 0.01],
                  "maybe the time": [0.10, 0.60, 0.20, 0.05, 0.05],              # under the 0.8 default
                  "time or weather": [0.0, 0.88, 0.60 - 0.0, 0.0, 0.0],        # 0.88 but only 0.28 ahead
                  "the mystery": [0.0, 0.0, 0.0, 0.0, 1.0]})                     # a kind this version of Jarvis no longer knows
        for sentence in ("why is the sky blue", "maybe the time", "time or weather", "the mystery", "   "):
            self.assertIsNone(NLU.interpret(sentence), sentence)

    def test_the_cut_offs_come_from_the_model_file_when_it_has_them(self):
        self.use({"maybe the time": [0.10, 0.60, 0.20, 0.05, 0.05]}, threshold=0.55, margin=0.3)
        self.assertEqual(NLU.interpret("maybe the time").family, "time")

    def test_a_command_that_is_awkward_to_undo_carries_its_question(self):
        self.use({"lock it up": [0, 0, 0, 0.97, 0.03]})
        self.assertIn("lock the screen", NLU.interpret("lock it up").ask)

    def test_rank_lists_the_best_guesses_highest_first(self):
        self.use({"hmm": [0.1, 0.5, 0.3, 0.05, 0.05]})
        self.assertEqual([name for name, _ in NLU.rank("hmm", 3)], ["time", "weather", "chat"])
        self.assertEqual(NLU.rank("   "), [])

    def test_the_setting_switches_the_model_off_even_when_it_is_loaded(self):
        self.use({"got the time": [0.02, 0.95, 0.01, 0.01, 0.01]})
        with mock.patch.object(NLU.config, "LANGUAGE_MODEL", False):
            self.assertIsNone(NLU.interpret("got the time"))
            self.assertEqual(NLU.rank("got the time"), [])
            NLU.MODEL_FILE.write_bytes(b"x")
            self.assertFalse(NLU.available())
        self.assertEqual(NLU.interpret("got the time").family, "time")

    def test_without_a_model_file_it_quietly_does_nothing(self):
        self.assertFalse(NLU.available())
        self.assertIsNone(NLU.interpret("what time is it"))
        self.assertEqual(NLU.rank("what time is it"), [])

    def test_a_damaged_model_file_is_reported_once_and_ignored(self):
        NLU.MODEL_FILE.write_bytes(b"this is not a model")
        out = StringIO()
        with redirect_stdout(out):
            self.assertIsNone(NLU.interpret("what time is it"))
            self.assertIsNone(NLU.interpret("what time is it"))
        self.assertEqual(out.getvalue().count("could not be loaded"), 1)
        self.assertIn("train_nlu.py", out.getvalue())

    def test_warming_up_loads_the_model_in_the_background(self):
        NLU.warm_up()                                                                  # no file: nothing to do
        self.assertIsNone(NLU._bundle)
        NLU.MODEL_FILE.write_bytes(b"x")
        with mock.patch.object(NLU, "_load") as load, mock.patch("threading.Thread") as thread:
            thread.return_value.start.side_effect = lambda: NLU._load()
            NLU.warm_up()
        load.assert_called_once()


class JudgingTests(unittest.TestCase):
    GUESSES = [("time", 0.95, 0.02), ("date", 0.90, 0.05),       # right, right
               ("weather", 0.92, 0.03),                           # sure and wrong
               ("time", 0.60, 0.30),                              # right but not sure enough
               ("chat", 0.99, 0.01), ("time", 0.85, 0.10),        # chat stays chat; chat taken for a command
               ("chat", 0.90, 0.05)]
    TRUTH = ["time", "date", "time", "time", "chat", "chat", "chat"]

    def test_the_numbers_say_what_would_really_happen(self):
        score = T.judge(self.GUESSES, self.TRUTH, 0.8, 0.3)
        self.assertAlmostEqual(score["commands_run_right"], 2 / 4)
        self.assertAlmostEqual(score["commands_run_wrong"], 1 / 4)
        self.assertAlmostEqual(score["chat_hijacked"], 1 / 3)
        self.assertAlmostEqual(score["precision"], 2 / 4)

    def test_the_working_point_lets_the_most_through_while_staying_safe(self):
        # 80 right commands (50 very sure, 30 fairly sure), 50 chat sentences that are plainly chat, 2 that look a bit like a command
        guesses = [("time", 0.97, 0.01)] * 50 + [("time", 0.70, 0.10)] * 30 + [("chat", 0.99, 0.0)] * 50 + [("time", 0.60, 0.30)] * 2
        truth = ["time"] * 80 + ["chat"] * 52
        spot = T.choose_operating_point(guesses, truth)
        self.assertEqual(spot["chat_hijacked"], 0)
        self.assertEqual(spot["commands_run_right"], 1.0)                        # the fairly sure ones are let through once it is safe
        self.assertTrue(0.60 < spot["threshold"] <= 0.70, spot)

    def test_a_permissive_point_is_not_chosen_when_it_would_hijack_chat(self):
        guesses = [("time", 0.97, 0.01)] * 50 + [("chat", 0.99, 0.0)] * 50 + [("time", 0.80, 0.30)] * 3
        spot = T.choose_operating_point(guesses, ["time"] * 50 + ["chat"] * 53)
        self.assertGreater(spot["threshold"], 0.80)                              # 3 of 53 chat sentences would have become commands

    def test_when_nothing_is_safe_enough_it_becomes_very_strict(self):
        guesses = [("time", 0.99, 0.0)] * 10                                     # sure of a command, whatever is said
        spot = T.choose_operating_point(guesses, ["time"] * 5 + ["chat"] * 5)
        self.assertEqual((spot["threshold"], spot["margin"]), (0.95, 0.4))


class TrainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = tiny_bank()
        with mock.patch.object(T, "VARIANTS", 4), mock.patch.object(T, "CHAT_EXTRA", 40):
            cls.model, cls.numbers = T.evaluate(cls.bank, say=lambda *a: None)

    def test_it_learns_wordings_it_was_never_shown(self):
        self.assertGreater(self.numbers["accuracy"], 0.85)
        self.assertEqual(set(self.numbers["per_kind"]), set(self.bank))
        self.assertGreater(self.numbers["held_out_sentences"], 100)
        self.assertIn("threshold", self.numbers["operating_point"])

    def test_real_speech_is_judged_separately(self):
        sentences = [("time", "yo got the time"), ("chat", "why is the sky blue")]
        with mock.patch.object(T.phrases, "real_utterances", return_value=sentences):
            rows = T.real_world(self.model, {"threshold": 0.6, "margin": 0.1}, lambda text: text)
        self.assertEqual([row["meant"] for row in rows], ["time", "chat"])
        self.assertTrue(all({"said", "meant", "guess", "confidence", "runs", "outcome", "ok"} <= set(row) for row in rows))
        self.assertEqual(rows[1]["outcome"], "right")                              # chat that stays chat is right
        strict = {"threshold": 0.9999, "margin": 0.5}                              # so unsure that nothing is ever run
        with mock.patch.object(T.phrases, "real_utterances", return_value=sentences):
            rows = T.real_world(self.model, strict, lambda text: text)
        self.assertEqual([row["outcome"] for row in rows], ["missed", "right"])    # a command it would not run is "missed"
        sentences = [("joke", "yo got the time"), ("chat", "tell me a joke")]
        with mock.patch.object(T.phrases, "real_utterances", return_value=sentences):
            rows = T.real_world(self.model, {"threshold": 0.3, "margin": 0.0}, lambda text: text)
        self.assertEqual([row["outcome"] for row in rows], ["wrong", "wrong"])     # the wrong command, and chat taken for one
        with mock.patch.object(T.phrases, "real_utterances", return_value=[]):
            self.assertIsNone(T.real_world(self.model, {"threshold": 0.6, "margin": 0.1}, lambda text: text))

    def test_a_saved_model_is_used_by_the_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "models" / "nlu.joblib"
            T.save(self.model, {"threshold": 0.6, "margin": 0.1}, 123, path)
            with mock.patch.object(NLU, "MODEL_FILE", path):
                NLU.reset()
                self.addCleanup(NLU.reset)
                self.assertEqual(NLU.interpret("what time is it").command, "what time is it")
                self.assertEqual(NLU.interpret("tell me a joke").family, "joke")
                self.assertIsNone(NLU.interpret("why is the sky blue"))
                self.assertEqual(NLU._load()["examples"], 123)

    def test_the_report_is_written_in_plain_words(self):
        numbers = dict(self.numbers, real_world=[{"said": "yo got the time", "meant": "time", "guess": "time", "confidence": 0.9,
                                                  "runs": True, "outcome": "right", "ok": True}])
        with tempfile.TemporaryDirectory() as folder:
            text = T.write_report(numbers, self.bank, Path(folder))
            self.assertTrue((Path(folder) / "nlu_report.txt").is_file())
            self.assertEqual(json.loads((Path(folder) / "nlu_report.json").read_text(encoding="utf-8"))["held_out_sentences"],
                             self.numbers["held_out_sentences"])
        for words in ("accuracy on them", "commands understood and done", "chat mistaken for a command", "weakest kinds",
                      "things you really said", "1 done right, 0 left for the chat brain"):
            self.assertIn(words, text)

    def test_recent_sentences_no_command_understood_are_listed_for_the_phrase_files(self):
        import transcript
        today = __import__("datetime").date.today().isoformat()
        with tempfile.TemporaryDirectory() as folder:
            lines = [{"who": "you", "text": "turn up the bass"}, {"who": "jarvis", "text": "Sure.", "by": "chat"},
                     {"who": "you", "text": "what time is it"}, {"who": "jarvis", "text": "It's 5.", "by": "command"},
                     {"who": "you", "text": "Hello"}, {"who": "jarvis", "text": "Hi", "by": "fallback"},
                     {"who": "you", "text": "turn up the bass"}, {"who": "jarvis", "text": "Again", "by": "chat"},
                     {"who": "you", "text": "tell me a story"}, {"who": "jarvis", "text": "Once", "by": "chat"},
                     {"who": "jarvis", "text": "more", "by": "chat", "more": True}]
            (Path(folder) / f"{today}.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n", encoding="utf-8")
            (Path(folder) / "2020-01-01.jsonl").write_text(json.dumps({"who": "you", "text": "ancient"}) + "\n", encoding="utf-8")
            with mock.patch.object(transcript, "LOG_DIR", Path(folder)):
                found = T.unmatched({"greet": ["hello"], NLU.CHAT: []}, days=7)
        self.assertEqual(found, ["turn up the bass", "tell me a story"])           # once each; known phrase and old file left out


class CommandLineTests(unittest.TestCase):
    def run_main(self, *args):
        out = StringIO()
        with redirect_stdout(out):
            code = T.main(list(args))
        return code, out.getvalue()

    def test_trying_a_sentence_without_a_model_says_how_to_make_one(self):
        with mock.patch.object(NLU, "MODEL_FILE", Path("no such model.joblib")):
            code, text = self.run_main("--try", "turn it up")
        self.assertEqual(code, 1)
        self.assertIn("python training/train_nlu.py", text)

    def test_trying_a_sentence_shows_the_guesses_and_what_would_run(self):
        NLU.reset()
        self.addCleanup(NLU.reset)
        NLU._bundle = {"pipeline": FakePipeline({"yo got the time": [0.0, 0.97, 0.01, 0.01, 0.01]})}
        with mock.patch.object(NLU, "MODEL_FILE", Path(__file__)):                  # any file that exists
            code, text = self.run_main("--try", "yo got the time")
        self.assertEqual(code, 0)
        self.assertIn("what time is it", text)
        self.assertIn("Jarvis would run: what time is it", text)

    def test_training_for_real_measures_first_and_then_saves_with_the_measured_working_point(self):
        numbers = {"accuracy": 0.97, "operating_point": {"threshold": 0.7, "margin": 0.2}, "held_out_sentences": 10}
        with mock.patch.object(T.phrases, "load", return_value={"greet": ["hello"], NLU.CHAT: ["why"]}), \
                mock.patch.object(T.phrases, "missing", return_value=[]), \
                mock.patch.object(T, "evaluate", return_value=("model", numbers)), \
                mock.patch.object(T, "write_report", return_value="REPORT"), \
                mock.patch.object(T, "train_final", return_value=("final", 99)), \
                mock.patch.object(T, "save", return_value=Path("models/nlu.joblib")) as save:
            code, text = self.run_main()
            self.assertEqual(code, 0)
            save.assert_called_once_with("final", numbers["operating_point"], 99)
            self.assertIn("REPORT", text)
            save.reset_mock()
            code, _ = self.run_main("--report")
            self.assertEqual(code, 0)
            save.assert_not_called()
            numbers["accuracy"] = 0.90
            self.assertEqual(self.run_main("--report")[0], 2)                      # below the Stage 2 target

    def test_kinds_without_phrases_stop_the_training(self):
        with mock.patch.object(T.phrases, "load", return_value={"greet": ["hello"]}):
            code, text = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no phrases yet", text)


if __name__ == "__main__":
    unittest.main()
