"""Tests for the launcher and the command dispatcher:  python -m unittest tests.test_session -v

Nothing here touches the microphone, the speakers, the webcam or the keyboard: input,
speech and the session itself are replaced with scripted stand-ins.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import gate  # noqa: E402
import MainCode  # noqa: E402
import Startup  # noqa: E402
import transcript  # noqa: E402
from tests.isolation import no_language_model  # noqa: E402


def setUpModule():
    """Commands are written to the conversation record; in these tests that is a temporary folder, never the real Logs folder."""
    no_language_model()
    folder = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(folder.cleanup)
    patcher = mock.patch.object(transcript, "LOG_DIR", Path(folder.name))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def scripted(*items):
    """A stand-in for listen()/_read_password(): returns the items in order, then ends the program."""
    queue = list(items)

    def next_item(*args, **kwargs):
        if not queue:
            raise SystemExit("script finished")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return next_item


class LauncherFlow(unittest.TestCase):
    PASSWORD = "correct horse"

    def run_startup(self, heard, passwords=(), sessions=(), face=True, face_check=True, password=PASSWORD, mode="text"):
        """Run Startup.run() with scripted input. Returns (spoken lines, session calls, password prompts, output)."""
        spoken, out = [], io.StringIO()
        session = mock.Mock(side_effect=list(sessions) or ["quit"])
        prompts = mock.Mock(side_effect=scripted(*passwords))
        with mock.patch.multiple(config, JARVIS_PASSWORD=password, JARVIS_PASSWORD_HASH=""), \
                mock.patch.object(Startup, "INPUT_MODE", mode), \
                mock.patch.object(Startup, "listen", scripted(*heard)), \
                mock.patch.object(Startup, "_read_password", prompts), \
                mock.patch.object(Startup, "Speak", spoken.append), \
                mock.patch.object(Startup, "FACE_CHECK", face_check), \
                mock.patch.object(gate, "face_check", return_value=face) as face_mock, \
                mock.patch.object(MainCode, "taskExe", session), \
                redirect_stdout(out), redirect_stderr(out):
            try:
                Startup.run()
            except SystemExit:
                pass
        return spoken, session, prompts, face_mock, out.getvalue()

    def test_wrong_password_three_times_is_refused_and_the_session_never_starts(self):
        spoken, session, prompts, _, _ = self.run_startup(["hey jarvis", "quit"], ["a", "b", "c"])
        session.assert_not_called()
        self.assertEqual(prompts.call_count, 3)
        self.assertEqual(sum("Access not granted" in line for line in spoken), 3)

    def test_correct_password_starts_the_session(self):
        spoken, session, _, _, _ = self.run_startup(["wake up"], [self.PASSWORD], ["quit"])
        session.assert_called_once()
        self.assertIn("Access granted.", spoken)

    def test_sleep_returns_to_the_wake_word_and_asks_for_the_password_again(self):
        """The old code exited the whole program on 'sleep' while promising 'say a wake word'."""
        spoken, session, prompts, _, _ = self.run_startup(
            ["hey jarvis", "hey jarvis"], [self.PASSWORD, self.PASSWORD], ["sleep", "quit"])
        self.assertEqual(session.call_count, 2)
        self.assertEqual(prompts.call_count, 2)

    def test_quit_ends_the_program(self):
        _, session, _, _, _ = self.run_startup(["hey jarvis", "hey jarvis"], [self.PASSWORD, self.PASSWORD], ["quit"])
        self.assertEqual(session.call_count, 1)             # the second wake word is never reached

    def test_quit_at_the_wake_prompt_needs_no_password(self):
        for word in ("quit", "exit", "terminate", "goodbye", "quit jarvis"):
            with self.subTest(word=word):
                _, session, prompts, _, _ = self.run_startup([word])
                prompts.assert_not_called()
                session.assert_not_called()

    def test_ordinary_chatter_does_not_quit_or_wake_jarvis(self):
        _, session, prompts, _, _ = self.run_startup(
            ["i might exit the building", "what a nice day", "", "quit"])
        prompts.assert_not_called()
        session.assert_not_called()

    def test_nobody_gets_in_when_no_password_is_configured(self):
        spoken, session, prompts, _, _ = self.run_startup(["hey jarvis", "quit"], password="")
        session.assert_not_called()
        prompts.assert_not_called()
        self.assertTrue(any("No unlock password is set" in line for line in spoken))

    def test_a_crash_inside_a_session_shows_the_real_error_and_does_not_end_the_program(self):
        _, session, _, _, output = self.run_startup(
            ["hey jarvis", "hey jarvis"], [self.PASSWORD, self.PASSWORD], [RuntimeError("feature exploded"), "quit"])
        self.assertEqual(session.call_count, 2)
        self.assertIn("RuntimeError: feature exploded", output)       # the traceback is visible, not swallowed

    def test_end_of_input_at_the_password_prompt_returns_to_the_wake_prompt(self):
        _, session, _, _, _ = self.run_startup(["hey jarvis", "quit"], [EOFError()])
        session.assert_not_called()

    def test_the_camera_never_blocks_entry(self):
        spoken, session, _, face_mock, _ = self.run_startup(["hey jarvis"], [self.PASSWORD], ["quit"], face=False)
        face_mock.assert_called_once()
        session.assert_called_once()
        self.assertTrue(any("couldn't confirm your face" in line for line in spoken))

    def test_the_camera_is_skipped_when_switched_off(self):
        _, session, _, face_mock, _ = self.run_startup(
            ["hey jarvis"], [self.PASSWORD], ["quit"], face_check=False)
        face_mock.assert_not_called()
        session.assert_called_once()

    def test_the_camera_is_not_used_before_the_password_is_right(self):
        _, _, _, face_mock, _ = self.run_startup(["hey jarvis", "quit"], ["wrong", "wrong", "wrong"])
        face_mock.assert_not_called()


class WakingByVoiceOrClap(unittest.TestCase):
    """In voice mode the offline wake word and clap detectors wake him; the password and everything after is unchanged."""
    PASSWORD = LauncherFlow.PASSWORD
    run_startup = LauncherFlow.run_startup                  # (the same scripted launcher)

    def wake(self, reasons, hint="To wake me, say 'hey Jarvis' or clap 2 times, or press START.", **options):
        """run_startup in voice mode where listener.wait_for_wake gives these reasons in turn (None = the microphone failed)."""
        queue = list(reasons)
        self.waits = mock.Mock(side_effect=lambda: queue.pop(0) if queue else (_ for _ in ()).throw(SystemExit("script finished")))
        with mock.patch("listener.wait_for_wake", self.waits), mock.patch("listener.hint", return_value=hint):
            return self.run_startup(mode="voice", **options)

    def test_a_clap_or_the_wake_word_asks_for_the_password_and_starts_the_session(self):
        for reason in ("clap", "wake word"):
            with self.subTest(reason=reason):
                spoken, session, prompts, _, output = self.wake([reason], heard=[], passwords=[self.PASSWORD], sessions=["quit"])
                session.assert_called_once()
                self.assertEqual(prompts.call_count, 1)
                self.assertIn("Access granted.", spoken)
                self.assertIn("clap 2 times", output)                       # (he says how to wake him)

    def test_a_wrong_password_after_a_clap_still_keeps_him_out(self):
        spoken, session, prompts, _, _ = self.wake(["clap"], heard=[], passwords=["a", "b", "c"])
        session.assert_not_called()
        self.assertEqual(prompts.call_count, 3)

    def test_when_the_microphone_cannot_be_used_for_it_the_old_way_still_works(self):
        spoken, session, _, _, _ = self.wake([None], heard=["hey jarvis"], passwords=[self.PASSWORD], sessions=["quit"])
        session.assert_called_once()

    def test_with_nothing_to_listen_for_it_goes_straight_to_the_old_way(self):
        spoken, session, _, _, _ = self.wake([], hint="", heard=["wake up"], passwords=[self.PASSWORD], sessions=["quit"])
        self.waits.assert_not_called()
        session.assert_called_once()

    def test_typed_mode_never_touches_the_listener(self):
        with mock.patch("listener.wait_for_wake", side_effect=AssertionError("listened in typed mode")):
            _, session, _, _, _ = self.run_startup(["hey jarvis"], [self.PASSWORD], ["quit"], mode="text")
        session.assert_called_once()


class NoBackDoor(unittest.TestCase):
    def test_maincode_cannot_be_run_as_a_launcher(self):
        source = (ROOT / "MainCode.py").read_text(encoding="utf-8")
        self.assertNotIn("__main__", source)


class CommandDispatcher(unittest.TestCase):
    def handle(self, text):
        spoken = []
        with mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=False), \
                mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=False), \
                mock.patch.object(MainCode, "Speak", spoken.append), \
                mock.patch.object(MainCode, "SpeakStream", side_effect=AssertionError("tests must not speak or chat for real")), \
                mock.patch("JarvisAdvancedBot.tools.media_control") as media, \
                mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value=None), \
                mock.patch("builtins.print"):
            outcome = MainCode.handle_command(text, ask=lambda question: "")
        return outcome, spoken, media

    def test_sleep_phrases_end_the_session_as_sleep(self):
        for text in ("sleep", "go to sleep", "sleep mode", "take a rest", "jarvis sleep"):
            with self.subTest(text=text):
                self.assertEqual(self.handle(text)[0], "sleep")

    def test_quit_phrases_end_the_session_as_quit(self):
        for text in ("quit", "exit", "goodbye", "bye jarvis", "terminate"):
            with self.subTest(text=text):
                self.assertEqual(self.handle(text)[0], "quit")

    def test_words_that_merely_contain_sleep_or_rest_do_not_end_the_session(self):
        """'that's inte-rest-ing' used to put Jarvis to sleep."""
        for text in ("that's interesting", "the rest of the list", "i was sleeping", "forest"):
            with self.subTest(text=text):
                self.assertIsNone(self.handle(text)[0])

    def test_stop_pauses_the_music_instead_of_quitting_jarvis(self):
        outcome, _, media = self.handle("stop")
        self.assertIsNone(outcome)
        media.assert_called_once_with("play_pause", 1)

    def test_a_bare_shutdown_does_not_quit_jarvis(self):
        self.assertIsNone(self.handle("shutdown")[0])

    def test_a_normal_command_is_answered_and_the_session_continues(self):
        outcome, spoken, _ = self.handle("what time is it")
        self.assertIsNone(outcome)
        self.assertTrue(any(line.startswith("It's ") for line in spoken))


if __name__ == "__main__":
    unittest.main()
