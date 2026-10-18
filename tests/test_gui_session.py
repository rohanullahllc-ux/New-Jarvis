"""Tests for the thread that runs the assistant behind the window:  python -m unittest tests.test_gui_session -v

A fake session stands in for the real one, so no microphone, speaker or network is touched.
"""
import io
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt  # noqa: E402

import speech  # noqa: E402
from gui.session import SessionController  # noqa: E402
from winmm_mic import MicrophoneError  # noqa: E402
from tests.isolation import no_language_model  # noqa: E402


def setUpModule():
    no_language_model()


def echo_session(listen, ask):
    """Speaks every command back until told to sleep or quit - what MainCode.taskExe does, minus the brain."""
    from MainCode import SessionStopped
    try:
        while True:
            command = listen()
            if command == "stream":
                speech.SpeakStream(["First sentence.", "Second sentence.", "Third sentence."])
                continue
            speech.Speak(f"echo {command}")
            if command in ("sleep", "quit"):
                return command
    except SessionStopped:
        return "quit"


class Recorder:
    """Collects every signal a controller emits (direct connections, so no event loop is needed)."""

    def __init__(self, controller):
        self.states, self.said, self.heard, self.log, self.problems, self.ended, self.hands_free = [], [], [], [], [], [], []
        self.said_more = []
        for signal, target in ((controller.state_changed, self.states), (controller.said, self.said),
                               (controller.said_more, self.said_more),
                               (controller.heard, self.heard), (controller.log, self.log),
                               (controller.problem, self.problems), (controller.ended, self.ended),
                               (controller.hands_free_changed, self.hands_free)):
            signal.connect(target.append, Qt.DirectConnection)


def wait_for(condition, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class ControllerCase(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(speech, "TTS_ENABLED", False), mock.patch.object(sys, "stdout", io.StringIO()),
                        mock.patch.object(sys, "stderr", io.StringIO())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, run_session=echo_session, listen_voice=None):
        controller = SessionController(run_session=run_session, listen_voice=listen_voice or (lambda timeout, limit: ""))
        self.addCleanup(self.finish, controller)
        return controller, Recorder(controller)

    def finish(self, controller):
        controller.stop()
        if controller._thread:
            controller._thread.join(5)


class StreamingReplyTests(ControllerCase):
    def test_a_reply_that_arrives_in_pieces_is_one_message_followed_by_additions(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.submit("stream")
        self.assertTrue(wait_for(lambda: len(seen.said_more) == 2))
        self.assertEqual(seen.said, ["First sentence."])
        self.assertEqual(seen.said_more, ["Second sentence.", "Third sentence."])

    def test_an_ordinary_line_afterwards_is_a_new_message_again(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.submit("stream")
        controller.submit("hello")
        self.assertTrue(wait_for(lambda: "echo hello" in seen.said))
        self.assertEqual(seen.said, ["First sentence.", "echo hello"])
        self.assertEqual(len(seen.said_more), 2)

    def test_the_window_can_ask_for_a_fresh_conversation(self):
        controller, seen = self.make()
        self.assertFalse(controller.reset_chat())                          # nothing is running yet
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertTrue(controller.reset_chat())
        self.assertTrue(wait_for(lambda: "echo new chat" in seen.said))
        self.assertEqual(seen.heard, [])                                   # it is not shown as something the user typed


class SessionLifecycleTests(ControllerCase):
    def test_a_session_answers_commands_and_ends_with_its_outcome(self):
        controller, seen = self.make()
        self.assertEqual(controller.state, "locked")
        self.assertTrue(controller.start())
        self.assertTrue(wait_for(lambda: controller.state == "ready"))
        self.assertTrue(controller.submit("hello"))
        self.assertTrue(wait_for(lambda: "echo hello" in seen.said))
        self.assertEqual(seen.heard, ["hello"])
        self.assertTrue(controller.submit("sleep"))
        self.assertTrue(wait_for(lambda: seen.ended))
        self.assertEqual(seen.ended, ["sleep"])
        self.assertEqual(controller.state, "locked")
        self.assertFalse(controller.running)
        for state in ("starting", "ready", "working", "locked"):
            self.assertIn(state, seen.states)

    def test_the_stop_button_ends_a_session_that_is_waiting_for_a_command(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.stop()
        self.assertTrue(wait_for(lambda: seen.ended))
        self.assertEqual(seen.ended, ["quit"])

    def test_commands_with_no_session_to_receive_them_are_refused(self):
        controller, seen = self.make()
        self.assertFalse(controller.submit("hello"))
        self.assertEqual(seen.heard, [])
        self.assertFalse(controller.talk())

    def test_blank_commands_are_ignored(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertFalse(controller.submit("   "))
        self.assertEqual(seen.heard, [])

    def test_a_second_start_is_refused_while_one_is_running(self):
        controller, _ = self.make()
        self.assertTrue(controller.start())
        self.assertFalse(controller.start())

    def test_it_can_be_started_again_after_sleeping(self):
        controller, seen = self.make()
        for round_number in (1, 2):
            controller.start()
            wait_for(lambda: controller.state == "ready")
            controller.submit("sleep")
            self.assertTrue(wait_for(lambda: len(seen.ended) == round_number))
            controller._thread.join(5)
        self.assertEqual(seen.ended, ["sleep", "sleep"])

    def test_commands_typed_after_a_session_ended_do_not_leak_into_the_next_one(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.stop()
        wait_for(lambda: seen.ended)
        controller._thread.join(5)
        controller._commands.put("stale command")
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertNotIn("echo stale command", seen.said)


class FailureTests(ControllerCase):
    def test_a_crashing_session_is_reported_and_leaves_the_window_unlocked_for_another_try(self):
        def crash(listen, ask):
            raise RuntimeError("kaboom")

        controller, seen = self.make(crash)
        controller.start()
        self.assertTrue(wait_for(lambda: seen.ended))
        self.assertEqual(seen.ended, ["error"])
        self.assertTrue(any("RuntimeError: kaboom" in line for line in seen.log))
        self.assertTrue(any("error" in text for text in seen.problems))
        self.assertEqual(controller.state, "locked")

    def test_a_closed_console_cannot_kill_the_window(self):
        def exits(listen, ask):
            raise SystemExit(1)

        controller, seen = self.make(exits)
        controller.start()
        self.assertTrue(wait_for(lambda: seen.ended))
        self.assertEqual(seen.ended, ["error"])


class OutputTests(ControllerCase):
    def test_printed_text_and_errors_reach_the_log_line_by_line(self):
        def noisy(listen, ask):
            print(": Brain: free local commands")
            print("half a line", end="")
            print(" and the rest")
            sys.stderr.write("a warning\n\n")
            return "quit"

        controller, seen = self.make(noisy)
        controller.start()
        wait_for(lambda: seen.ended)
        self.assertEqual(seen.log, [": Brain: free local commands", "half a line and the rest", "a warning"])

    def test_what_jarvis_says_is_forwarded_and_the_listener_is_removed_afterwards(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.submit("quit")
        wait_for(lambda: seen.ended)
        controller._thread.join(5)
        speech.Speak("said after the session")
        self.assertNotIn("said after the session", seen.said)


class FollowUpTests(ControllerCase):
    def test_a_follow_up_question_is_shown_and_answered_by_the_next_thing_typed(self):
        answers = []

        def asks(listen, ask):
            answers.append(ask("Which one?"))
            return "quit"

        controller, seen = self.make(asks)
        controller.start()
        self.assertTrue(wait_for(lambda: "Which one?" in seen.said))
        controller.submit("the second one")
        self.assertTrue(wait_for(lambda: seen.ended))
        self.assertEqual(answers, ["the second one"])


class VoiceTests(ControllerCase):
    def test_push_to_talk_submits_what_was_said(self):
        controller, seen = self.make(listen_voice=lambda timeout, limit: "open chrome")
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertTrue(controller.talk())
        self.assertTrue(wait_for(lambda: "echo open chrome" in seen.said))
        self.assertEqual(seen.heard, ["open chrome"])
        self.assertIn("listening", seen.states)

    def test_only_one_capture_can_use_the_microphone_at_a_time(self):
        release = threading.Event()
        controller, _ = self.make(listen_voice=lambda timeout, limit: (release.wait(5), "")[1])
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertTrue(controller.talk())
        self.assertTrue(wait_for(lambda: controller.state == "listening"))
        self.assertFalse(controller.talk())
        release.set()
        self.assertTrue(wait_for(lambda: controller.state == "ready"))

    def test_hearing_nothing_says_so(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.talk()
        self.assertTrue(wait_for(lambda: seen.problems))
        self.assertIn("didn't hear", seen.problems[0])
        self.assertEqual(seen.heard, [])

    def test_hands_free_keeps_listening_and_acts_on_what_it_hears(self):
        phrases = iter(["", "", "what time is it"])
        controller, seen = self.make(listen_voice=lambda timeout, limit: next(phrases, ""))
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.set_hands_free(True)
        self.assertTrue(wait_for(lambda: "echo what time is it" in seen.said))
        self.assertEqual(seen.heard, ["what time is it"])
        self.assertTrue(controller.hands_free)
        controller.set_hands_free(False)
        self.assertEqual(seen.hands_free, [True, False])

    def test_typed_commands_still_work_in_hands_free_mode(self):
        controller, seen = self.make()
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.set_hands_free(True)
        controller.submit("typed while listening")
        self.assertTrue(wait_for(lambda: "echo typed while listening" in seen.said))

    def test_a_microphone_failure_is_reported_and_hands_free_switches_itself_off(self):
        def broken(timeout, limit):
            raise MicrophoneError("no input device")

        controller, seen = self.make(listen_voice=broken)
        controller.start()
        wait_for(lambda: controller.state == "ready")
        controller.set_hands_free(True)
        self.assertTrue(wait_for(lambda: seen.problems))
        self.assertIn("no input device", seen.problems[0])
        self.assertTrue(wait_for(lambda: not controller.hands_free))
        self.assertEqual(seen.hands_free[-1], False)

    def test_push_to_talk_works_even_in_typed_mode(self):
        controller, seen = self.make(listen_voice=lambda timeout, limit: "hello")
        controller.start()
        wait_for(lambda: controller.state == "ready")
        self.assertFalse(controller.hands_free)
        controller.talk()
        self.assertTrue(wait_for(lambda: seen.heard == ["hello"]))


if __name__ == "__main__":
    unittest.main()
