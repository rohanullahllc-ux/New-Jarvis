"""Tests for the conversation record:  python -m unittest tests.test_transcript -v

Everything is written to a temporary folder. Nothing here speaks, listens or touches the network.
"""
import datetime
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MainCode  # noqa: E402
import speech  # noqa: E402
import transcript as T  # noqa: E402
from tests.isolation import no_language_model  # noqa: E402


def setUpModule():
    no_language_model()


class RecordCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name) / "conversations"
        for patcher in (mock.patch.object(T, "LOG_DIR", self.folder),
                        mock.patch.multiple(T.config, LOG_CONVERSATIONS=True, CONVERSATION_LOG_DAYS=30)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def today_file(self):
        return self.folder / f"{datetime.date.today():%Y-%m-%d}.jsonl"

    def lines(self):
        return [json.loads(line) for line in self.today_file().read_text(encoding="utf-8").splitlines()]


class RecordingTests(RecordCase):
    def test_each_thing_said_is_one_line_in_todays_file(self):
        T.record("you", "why is the sky blue")
        T.record("jarvis", "Because of scattering.", by="chat")
        lines = self.lines()
        self.assertEqual([(l["who"], l["text"]) for l in lines], [("you", "why is the sky blue"), ("jarvis", "Because of scattering.")])
        self.assertEqual(lines[1]["by"], "chat")
        datetime.datetime.fromisoformat(lines[0]["at"])                          # a real timestamp

    def test_spaces_are_tidied_and_empty_text_is_not_recorded(self):
        T.record("you", "  too    many \n spaces ")
        T.record("you", "   ")
        T.record("you", "")
        self.assertEqual([l["text"] for l in self.lines()], ["too many spaces"])

    def test_empty_extra_fields_are_left_out(self):
        T.record("jarvis", "hello", by=None, more=False, kind="")
        self.assertEqual(set(self.lines()[0]), {"at", "who", "text"})

    def test_other_alphabets_are_kept_readable(self):
        T.record("you", "شکریہ جارویس")
        self.assertIn("شکریہ جارویس", self.today_file().read_text(encoding="utf-8"))
        self.assertEqual(self.lines()[0]["text"], "شکریہ جارویس")

    def test_switching_it_off_in_the_settings_records_nothing(self):
        with mock.patch.object(T.config, "LOG_CONVERSATIONS", False):
            T.record("you", "private")
        self.assertFalse(self.folder.exists())

    def test_a_folder_that_cannot_be_written_never_stops_jarvis(self):
        blocker = self.folder.parent / "blocked"
        blocker.write_text("a file where the folder should be", encoding="utf-8")
        with mock.patch.object(T, "LOG_DIR", blocker / "conversations"):
            T.record("you", "still works")                                       # must not raise

    def test_speech_is_recorded_with_what_answered_and_later_sentences_are_marked_as_part_of_the_same_reply(self):
        T.source("chat")
        T.on_speech("First sentence.", True)
        T.on_speech("Second sentence.", False)
        first, second = self.lines()
        self.assertEqual((first["by"], first.get("more")), ("chat", None))
        self.assertEqual((second["by"], second["more"]), ("chat", True))

    def test_speech_with_no_command_behind_it_is_labelled_system(self):
        T.source(None)
        T.on_speech("A reminder fired.", True)
        T.source("system")
        T.on_speech("Another one.", True)
        self.assertEqual([l["by"] for l in self.lines()], ["system", "system"])

    def test_the_source_belongs_to_the_thread_that_set_it(self):
        import threading
        T.source("chat")
        seen = []
        worker = threading.Thread(target=lambda: (T.on_speech("from a timer", True), seen.append(True)))
        worker.start()
        worker.join()
        self.assertEqual(self.lines()[-1]["by"], "system")                        # not "chat": that was another thread's command


class ReadingTests(RecordCase):
    def write(self, day, *events):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{day}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def test_the_last_days_are_read_oldest_first(self):
        today = datetime.date(2026, 10, 18)
        self.write("2026-10-16", {"at": "2026-10-16T09:00:00", "who": "you", "text": "two days ago"})
        self.write("2026-10-17", {"at": "2026-10-17T09:00:00", "who": "you", "text": "yesterday"})
        self.write("2026-10-18", {"at": "2026-10-18T09:00:00", "who": "you", "text": "today"})
        self.assertEqual([e["text"] for e in T.read(1, today)], ["today"])
        self.assertEqual([e["text"] for e in T.read(2, today)], ["yesterday", "today"])
        self.assertEqual([e["text"] for e in T.read(5, today)], ["two days ago", "yesterday", "today"])

    def test_a_damaged_line_does_not_hide_the_others(self):
        self.folder.mkdir(parents=True)
        (self.folder / "2026-10-18.jsonl").write_text(
            '{"at": "2026-10-18T09:00:00", "who": "you", "text": "before"}\n{not json\n[1, 2]\n{"no": "time"}\n'
            '{"at": "2026-10-18T09:00:05", "who": "you", "text": "after"}\n', encoding="utf-8")
        self.assertEqual([e["text"] for e in T.read(1, datetime.date(2026, 10, 18))], ["before", "after"])

    def test_nothing_saved_reads_as_nothing(self):
        self.assertEqual(T.read(3), [])


class FormattingTests(unittest.TestCase):
    EVENTS = [
        {"at": "2026-10-18T15:44:30", "who": "system", "text": "session started", "brain": "commands + chat with qwen2.5:1.5b"},
        {"at": "2026-10-18T15:46:02", "who": "you", "text": "why is the sky blue"},
        {"at": "2026-10-18T15:46:09", "who": "jarvis", "text": "Because of scattering,", "by": "chat"},
        {"at": "2026-10-18T15:46:10", "who": "jarvis", "text": "which bends blue light.", "by": "chat", "more": True},
        {"at": "2026-10-18T15:46:10", "who": "system", "text": "timing", "kind": "timing", "model": "qwen2.5:1.5b", "first_words": 3.9, "total": 5.1},
        {"at": "2026-10-18T15:47:00", "who": "you", "text": "open calculator"},
        {"at": "2026-10-18T15:47:01", "who": "jarvis", "text": "Opening the calculator.", "by": "command"},
        {"at": "2026-10-18T15:47:30", "who": "jarvis", "text": "Which city?", "by": "command"},
        {"at": "2026-10-18T15:47:35", "who": "you", "text": "London", "kind": "answer"},
        {"at": "2026-10-19T08:00:00", "who": "you", "text": "good morning"},
        {"at": "2026-10-19T08:00:02", "who": "system", "text": "session ended", "outcome": "quit"},
    ]

    def test_the_conversation_reads_like_a_conversation(self):
        text = T.format_events(self.EVENTS)
        self.assertIn("=== Sunday 18 October 2026 ===", text)
        self.assertIn("=== Monday 19 October 2026 ===", text)
        self.assertIn("15:46:02  YOU    : why is the sky blue", text)
        self.assertIn("15:46:09  JARVIS : [chat] Because of scattering, which bends blue light.", text)    # one reply, one line
        self.assertIn("15:47:01  JARVIS : [command] Opening the calculator.", text)
        self.assertIn("15:47:35  YOU    : (answer) London", text)
        self.assertIn("(qwen2.5:1.5b: first words after 3.9s, whole answer 5.1s)", text)
        self.assertIn("--     : session started (brain commands + chat with qwen2.5:1.5b)", text)
        self.assertIn("--     : session ended (outcome quit)", text)

    def test_only_what_the_user_said_can_be_listed(self):
        text = T.format_events(self.EVENTS, only_you=True)
        self.assertIn("YOU    : why is the sky blue", text)
        self.assertIn("YOU    : good morning", text)
        self.assertNotIn("JARVIS", text)
        self.assertNotIn("session", text)

    def test_system_lines_are_not_labelled_as_a_source(self):
        text = T.format_events([{"at": "2026-10-18T09:00:00", "who": "jarvis", "text": "Good morning.", "by": "system"}])
        self.assertIn("JARVIS : Good morning.", text)
        self.assertNotIn("[system]", text)

    def test_a_bad_date_does_not_crash_the_listing(self):
        self.assertIn("JARVIS : hi", T.format_events([{"at": "garbage-date" + "T09:00:00", "who": "jarvis", "text": "hi"}]))


class PruneTests(RecordCase):
    def test_conversations_older_than_the_limit_are_deleted_and_recent_ones_kept(self):
        self.folder.mkdir(parents=True)
        today = datetime.date(2026, 10, 18)
        for days_back in (0, 10, 29, 31, 90):
            (self.folder / f"{today - datetime.timedelta(days=days_back):%Y-%m-%d}.jsonl").write_text("{}\n", encoding="utf-8")
        (self.folder / "notes.jsonl").write_text("not a date", encoding="utf-8")
        self.assertEqual(T.prune(30, today), 2)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["2026-07-20.jsonl".replace("07-20", f"{(today - datetime.timedelta(days=0)).month:02d}-{today.day:02d}")]
                         + [f"{today - datetime.timedelta(days=d):%Y-%m-%d}.jsonl" for d in (10, 29)] + ["notes.jsonl"]
                         if False else sorted(p.name for p in self.folder.iterdir()))
        remaining = {p.name for p in self.folder.iterdir()}
        self.assertEqual(remaining, {f"{today - datetime.timedelta(days=d):%Y-%m-%d}.jsonl" for d in (0, 10, 29)} | {"notes.jsonl"})

    def test_zero_keeps_everything(self):
        self.folder.mkdir(parents=True)
        (self.folder / "2020-01-01.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertEqual(T.prune(0, datetime.date(2026, 10, 18)), 0)
        self.assertTrue((self.folder / "2020-01-01.jsonl").exists())

    def test_no_folder_is_fine(self):
        self.assertEqual(T.prune(30), 0)

    def test_starting_a_session_prunes_by_the_setting(self):
        self.folder.mkdir(parents=True)
        (self.folder / "2020-01-01.jsonl").write_text("{}\n", encoding="utf-8")
        T.begin("test brain")
        self.assertFalse((self.folder / "2020-01-01.jsonl").exists())
        self.assertEqual(self.lines()[0]["text"], "session started")
        self.assertEqual(self.lines()[0]["brain"], "test brain")
        T.end("sleep")
        self.assertEqual((self.lines()[-1]["text"], self.lines()[-1]["outcome"]), ("session ended", "sleep"))


class CommandLineTests(RecordCase):
    def run_main(self, *argv, answer="no"):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("builtins.input", return_value=answer):
            code = T.main(list(argv))
        return code, out.getvalue()

    def test_it_prints_today_in_plain_form(self):
        T.record("you", "hello jarvis")
        T.record("jarvis", "Hello sir.", by="command")
        code, text = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("YOU    : hello jarvis", text)
        self.assertIn("JARVIS : [command] Hello sir.", text)

    def test_it_says_so_when_nothing_has_been_saved(self):
        self.assertIn("Nothing has been saved today.", self.run_main()[1])
        self.assertIn("in the last 3 days", self.run_main("--days", "3")[1])

    def test_it_says_when_the_record_is_switched_off(self):
        with mock.patch.object(T.config, "LOG_CONVERSATIONS", False):
            self.assertIn("LOG_CONVERSATIONS is false", self.run_main()[1])

    def test_only_what_you_said(self):
        T.record("you", "open calculator")
        T.record("jarvis", "Opening it.", by="command")
        text = self.run_main("--you")[1]
        self.assertIn("open calculator", text)
        self.assertNotIn("Opening it.", text)

    def test_deleting_asks_first_and_only_a_yes_deletes(self):
        T.record("you", "keep me")
        code, text = self.run_main("--delete", answer="no")
        self.assertEqual(code, 1)
        self.assertTrue(self.today_file().exists())
        code, text = self.run_main("--delete", answer="YES")
        self.assertEqual(code, 0)
        self.assertIn("Deleted 1 file", text)
        self.assertFalse(self.today_file().exists())
        self.assertIn("no saved conversations", self.run_main("--delete")[1].lower())


class SessionRecordTests(RecordCase):
    """A whole session through the real command handler and the real speech code (silent), then what the record says."""

    def run_session(self, commands, chat=None):
        """``chat`` maps what is said to the sentences the chat model would answer; None means no chat model is running."""
        heard = iter(commands)

        def listen():
            try:
                return next(heard)
            except StopIteration:
                raise MainCode.SessionStopped() from None

        patches = [
            mock.patch.object(speech, "TTS_ENABLED", False),
            mock.patch.object(MainCode, "_prewarm"),
            mock.patch.object(MainCode, "STARTUP_GREETING", "short"),
            mock.patch.object(MainCode, "USER_NAME", "Mr Khan"),
            mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=False),
            mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=chat is not None),
            mock.patch("JarvisAdvancedBot.ChatBrain.is_loaded", return_value=True),
            mock.patch("JarvisAdvancedBot.ChatBrain.choose_model", return_value="test-model:1b"),
            mock.patch("JarvisAdvancedBot.ChatBrain.reply_sentences", side_effect=lambda query: iter((chat or {}).get(query, []))),
            mock.patch("JarvisAdvancedBot.ChatBrain.last_timing", ": (chat: test)"),
            mock.patch("JarvisAdvancedBot.ChatBrain.last_stats", {"model": "test-model:1b", "lookup": 0.0, "first_words": 1.5, "total": 2.5}),
            mock.patch("JarvisAdvancedBot.ChatBrain.forget"),
            mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value=None),
            mock.patch("JarvisAdvancedBot.FreeBrain.available", return_value=False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return MainCode.taskExe(listen=listen)

    def test_the_whole_conversation_is_recorded_with_what_answered_each_time(self):
        outcome = self.run_session(["what time is it", "why is the sky blue", "frobnicate the widgets please", "new chat", "quit"],
                                   chat={"why is the sky blue": ["Because of scattering,", "which bends blue light."]})
        self.assertEqual(outcome, "quit")
        events = self.lines()
        said = [(e["who"], e.get("by"), e["text"]) for e in events if e["who"] in ("you", "jarvis")]
        self.assertEqual(said[0][:2], ("jarvis", "system"))                                       # the greeting
        self.assertIn("Ready for your command, sir.", said[0][2])
        self.assertEqual(said[1], ("you", None, "what time is it"))
        self.assertEqual((said[2][0], said[2][1]), ("jarvis", "command"))
        self.assertTrue(said[2][2].startswith("It's "))
        self.assertEqual(said[3], ("you", None, "why is the sky blue"))
        self.assertEqual(said[4], ("jarvis", "chat", "Because of scattering,"))
        self.assertEqual(said[5], ("jarvis", "chat", "which bends blue light."))
        self.assertEqual(said[7][:2], ("jarvis", "fallback"))                                     # nothing could answer "calculater"
        self.assertIn("Did you mean", said[7][2])
        self.assertEqual(said[9][:2], ("jarvis", "reset"))
        self.assertEqual(said[-1], ("jarvis", "command", "Goodbye, sir."))

    def test_the_session_start_and_end_and_the_timing_are_recorded(self):
        self.run_session(["why is the sky blue", "quit"], chat={"why is the sky blue": ["Because."]})
        events = self.lines()
        self.assertEqual((events[0]["text"], events[0]["brain"]), ("session started", "commands + chat with test-model:1b"))
        self.assertEqual((events[-1]["text"], events[-1]["outcome"]), ("session ended", "quit"))
        timing = next(e for e in events if e.get("kind") == "timing")
        self.assertEqual((timing["model"], timing["first_words"], timing["total"]), ("test-model:1b", 1.5, 2.5))

    def test_answers_to_jarvis_questions_are_recorded_as_answers(self):
        self.run_session(["take a note", "buy milk", "quit"])
        answers = [e["text"] for e in self.lines() if e.get("kind") == "answer"]
        self.assertEqual(answers, ["buy milk"])

    def test_the_listener_is_removed_when_the_session_ends_even_if_it_crashes(self):
        with mock.patch.object(MainCode, "handle_command", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_session(["anything"])
        self.assertNotIn(T.on_speech, speech._listeners)
        self.assertEqual(self.lines()[-1]["outcome"], "error")

    def test_sleep_is_the_outcome_when_jarvis_goes_to_sleep(self):
        self.assertEqual(self.run_session(["sleep"]), "sleep")
        self.assertEqual(self.lines()[-1]["outcome"], "sleep")
        self.assertNotIn(T.on_speech, speech._listeners)

    def test_noise_too_short_to_be_a_command_is_not_recorded(self):
        self.run_session(["uh", "quit"])
        self.assertNotIn("uh", [e["text"] for e in self.lines() if e["who"] == "you"])


if __name__ == "__main__":
    unittest.main()
