"""Tests for the session module (greeting, briefing, command loop):  python -m unittest tests.test_maincode -v

Nothing here uses the microphone, speakers or network: speech, input and the tools are stand-ins.
"""
import datetime
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MainCode  # noqa: E402
from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import tools as T  # noqa: E402


class GreetingTests(unittest.TestCase):
    def test_it_is_one_sentence_with_the_part_of_the_day_the_date_and_the_time(self):
        with mock.patch.object(MainCode, "USER_NAME", "Mr Khan"):
            self.assertEqual(MainCode.greeting(datetime.datetime(2026, 10, 17, 14, 35)),
                             "Good afternoon Mr Khan. It's Saturday, 17 October, 2:35 PM.")
            self.assertEqual(MainCode.greeting(datetime.datetime(2026, 3, 2, 9, 5)),
                             "Good morning Mr Khan. It's Monday, 2 March, 9:05 AM.")

    def test_parts_of_the_day(self):
        expected = {0: "Good evening", 4: "Good evening", 5: "Good morning", 11: "Good morning", 12: "Good afternoon",
                    16: "Good afternoon", 17: "Good evening", 23: "Good evening"}
        for hour, words in expected.items():
            self.assertTrue(MainCode.greeting(datetime.datetime(2026, 1, 1, hour, 0)).startswith(words), hour)


class BriefingTests(unittest.TestCase):
    def patched(self, **tools):
        defaults = {"weather_report": lambda city: f"Sunny in {city}.", "get_timetable_block": lambda: "Right now: Study until 09:00.",
                    "list_tasks": lambda: "To-do list for Saturday: 1. Buy bread"}
        defaults.update(tools)
        return mock.patch.multiple(T, **defaults)

    def battery(self, percent, plugged):
        return mock.patch.object(MainCode.psutil, "sensors_battery",
                                 return_value=SimpleNamespace(percent=percent, power_plugged=plugged))

    def test_everything_is_included_in_a_fixed_order(self):
        with self.patched(), self.battery(20, False), mock.patch.object(MainCode, "DEFAULT_CITY", "Peshawar"):
            self.assertEqual(MainCode.briefing(), [
                "Sunny in Peshawar.", "Right now: Study until 09:00.", "To-do list for Saturday: 1. Buy bread",
                "Your battery is at 20 percent, so you may want to plug in."])

    def test_an_empty_time_table_and_an_empty_list_are_left_out(self):
        with self.patched(get_timetable_block=lambda: "Your time table is empty. Add your own routine...",
                          list_tasks=lambda: "The to-do list for Saturday 17 October is empty."), self.battery(90, True):
            self.assertEqual(MainCode.briefing(), ["Sunny in Peshawar."])

    def test_the_battery_is_only_mentioned_when_low_and_unplugged(self):
        for percent, plugged in ((20, True), (80, False), (80, True)):
            with self.patched(), self.battery(percent, plugged):
                self.assertEqual(len(MainCode.briefing()), 3, (percent, plugged))
        with self.patched(), mock.patch.object(MainCode.psutil, "sensors_battery", return_value=None):      # a desktop PC
            self.assertEqual(len(MainCode.briefing()), 3)

    def test_an_item_that_fails_never_stops_the_others(self):
        def no_internet(city):
            raise ToolError("I couldn't reach open-meteo.com.")

        def crash():
            raise RuntimeError("corrupt file")

        with self.patched(weather_report=no_internet, get_timetable_block=crash), self.battery(90, True):
            self.assertEqual(MainCode.briefing(), ["To-do list for Saturday: 1. Buy bread"])


class SessionCase(unittest.TestCase):
    def run_session(self, commands, mode="short", handler=None, **kwargs):
        """Run taskExe() with scripted commands. Returns (outcome, spoken lines, printed output, handler mock)."""
        spoken, out, err = [], io.StringIO(), io.StringIO()
        heard = iter(commands)

        def listen():
            try:
                return next(heard)
            except StopIteration:
                raise MainCode.SessionStopped() from None

        patches = [
            mock.patch.object(MainCode, "Speak", spoken.append),
            mock.patch.object(MainCode, "_prewarm"),
            mock.patch.object(MainCode, "STARTUP_GREETING", mode),
            mock.patch.object(MainCode, "USER_NAME", "Mr Khan"),
            mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=False),
        ]
        if handler is not None:
            patches.append(mock.patch.object(MainCode, "handle_command", handler))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with redirect_stdout(out), redirect_stderr(err):
            outcome = MainCode.taskExe(listen=kwargs.pop("listen", listen), **kwargs)
        return outcome, spoken, out.getvalue() + err.getvalue()


class StartupModeTests(SessionCase):
    def test_short_greets_and_says_it_is_ready_in_one_utterance(self):
        outcome, spoken, _ = self.run_session(["sleep"])
        self.assertEqual(outcome, "sleep")
        self.assertRegex(spoken[0], r"^Good \w+ Mr Khan\. It's \w+day, \d+ \w+, \d+:\d\d [AP]M\. Ready for your command, sir\.$")
        self.assertEqual(spoken[1], "Going to sleep, sir. Say a wake word when you need me.")

    def test_full_puts_the_briefing_between_the_greeting_and_the_ready_line(self):
        with mock.patch.object(MainCode, "briefing", return_value=["Sunny.", "Study until nine."]):
            _, spoken, _ = self.run_session(["quit"], mode="full")
        self.assertRegex(spoken[0], r"^Good .* Sunny\. Study until nine\. Ready for your command, sir\.$")
        self.assertEqual(spoken[1], "Goodbye, sir.")

    def test_full_with_nothing_to_report_says_nothing_extra(self):
        with mock.patch.object(MainCode, "briefing", return_value=[]):
            _, spoken, _ = self.run_session(["quit"], mode="full")
        self.assertTrue(spoken[0].endswith("Ready for your command, sir."))
        self.assertNotIn("  ", spoken[0])

    def test_short_never_builds_the_briefing(self):
        with mock.patch.object(MainCode, "briefing") as briefing:
            self.run_session(["quit"], mode="short")
        briefing.assert_not_called()

    def test_silent_says_nothing_until_you_do(self):
        outcome, spoken, output = self.run_session(["quit"], mode="silent")
        self.assertEqual(outcome, "quit")
        self.assertEqual(spoken, ["Goodbye, sir."])
        self.assertIn(": Ready.", output)

    def test_the_brain_in_use_is_printed(self):
        _, _, output = self.run_session(["quit"], mode="silent")
        self.assertIn("free local commands", output)


class CommandLoopTests(SessionCase):
    def test_commands_are_answered_until_quit(self):
        outcome, spoken, _ = self.run_session(["what is the date", "what time is it", "quit"], mode="silent")
        self.assertEqual(outcome, "quit")
        self.assertTrue(spoken[0].startswith("Today is "))
        self.assertTrue(spoken[1].startswith("It's "))

    def test_the_stop_button_ends_the_session(self):
        outcome, _, _ = self.run_session([], mode="silent")                 # the scripted listen() raises SessionStopped
        self.assertEqual(outcome, "quit")

    def test_a_broken_command_shows_the_real_error_and_the_session_carries_on(self):
        handler = mock.Mock(side_effect=[RuntimeError("feature exploded"), "quit"])
        outcome, spoken, output = self.run_session(["one", "two"], mode="silent", handler=handler)
        self.assertEqual(outcome, "quit")
        self.assertEqual(handler.call_count, 2)
        self.assertIn("RuntimeError: feature exploded", output)
        self.assertTrue(any("something went wrong" in line for line in spoken))

    def test_follow_up_questions_are_asked_by_voice_and_answered_with_the_next_thing_heard(self):
        captured = {}

        def handler(query, ask):
            captured["answer"] = ask("Which one?")
            return "quit"

        _, spoken, _ = self.run_session(["open something", "the second one"], mode="silent", handler=handler)
        self.assertEqual(captured["answer"], "the second one")
        self.assertIn("Which one?", spoken)

    def test_a_gui_can_supply_its_own_way_of_asking(self):
        seen = []
        handler = mock.Mock(side_effect=lambda query, ask: (seen.append(ask("Name?")), "quit")[1])
        self.run_session(["hello there"], mode="silent", handler=handler, ask=lambda question: f"typed answer to {question}")
        self.assertEqual(seen, ["typed answer to Name?"])

    def test_prewarming_happens_in_the_background(self):
        with mock.patch.object(MainCode.threading, "Thread") as thread:
            MainCode._prewarm()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()


class DispatcherTests(unittest.TestCase):
    def handle(self, text, ai=False, brain_reply="Hello from Claude."):
        spoken = []
        with mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=ai), \
                mock.patch("JarvisAdvancedBot.JarvisAiBrain.ReplyBrain", return_value=brain_reply) as reply, \
                mock.patch("JarvisAdvancedBot.JarvisAiBrain.ResetBrain") as reset, \
                mock.patch.object(MainCode, "Speak", spoken.append), mock.patch("builtins.print"):
            outcome = MainCode.handle_command(text, ask=lambda question: "")
        return outcome, spoken, reply, reset

    def test_unknown_commands_get_an_honest_answer_that_helps(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value=None),                 mock.patch("JarvisAdvancedBot.FreeBrain.available", return_value=False):
            outcome, spoken, _, _ = self.handle("calculater please")
        self.assertIsNone(outcome)
        self.assertIn("didn't understand that as a command", spoken[0])
        self.assertIn("open calculator", spoken[0])

    def test_questions_no_command_covers_are_answered_by_the_free_brain(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value="Because of scattering."):
            _, spoken, _, _ = self.handle("blorp why is the sky blue zzz")
        self.assertEqual(spoken, ["Because of scattering."])

    def test_very_short_noise_is_ignored(self):
        _, spoken, _, _ = self.handle("uh")
        self.assertEqual(spoken, [])

    def test_with_an_api_key_commands_go_to_claude(self):
        _, spoken, reply, _ = self.handle("tell me about black holes", ai=True)
        reply.assert_called_once_with("tell me about black holes")
        self.assertEqual(spoken, ["Hello from Claude."])

    def test_with_an_api_key_a_fresh_start_resets_the_conversation(self):
        _, spoken, reply, reset = self.handle("new conversation", ai=True)
        reset.assert_called_once()
        reply.assert_not_called()
        self.assertIn("Fresh start", spoken[0])

    def test_sleep_and_quit_still_work_with_claude_switched_on(self):
        self.assertEqual(self.handle("sleep", ai=True)[0], "sleep")
        self.assertEqual(self.handle("goodbye", ai=True)[0], "quit")


if __name__ == "__main__":
    unittest.main()
