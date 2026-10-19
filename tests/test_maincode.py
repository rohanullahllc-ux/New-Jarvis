"""Tests for the session module (greeting, briefing, command loop):  python -m unittest tests.test_maincode -v

Nothing here uses the microphone, speakers or network: speech, input and the tools are stand-ins.
"""
import datetime
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MainCode  # noqa: E402
import transcript  # noqa: E402
from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import tools as T  # noqa: E402
from tests.isolation import no_language_model  # noqa: E402


def setUpModule():
    """Sessions write a conversation record; in these tests it goes to a temporary folder, never to the real Logs folder."""
    no_language_model()
    folder = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(folder.cleanup)
    patcher = mock.patch.object(transcript, "LOG_DIR", Path(folder.name))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class QuitCommandTests(unittest.TestCase):
    def test_every_way_of_asking_jarvis_to_quit_is_understood(self):
        from JarvisAdvancedBot.LocalBrain import normalize
        for phrase in ("quit", "exit", "exit exit the program", "can you quit jar", "please exit the application", "close the program",
                       "quit jarvis", "stop the program", "shut down yourself", "bye", "ok goodbye jarvis"):
            polite = normalize(phrase)
            self.assertTrue(MainCode.STOP_COMMAND.fullmatch(phrase.lower().replace("jarvis", "").strip())
                            or MainCode.STOP_COMMAND.fullmatch(polite), phrase)

    def test_closing_other_things_is_not_quitting_jarvis(self):
        for phrase in ("close chrome", "close notepad", "stop the music", "turn off the sound", "shut down the computer"):
            self.assertFalse(MainCode.STOP_COMMAND.fullmatch(phrase), phrase)


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
            mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=False),       # not the Ollama that may be running here
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

    def test_the_chat_model_is_only_loaded_ahead_of_time_when_the_setting_says_so(self):
        for setting, loaded in ((False, 0), (True, 1)):
            with mock.patch.object(MainCode.threading, "Thread") as thread, mock.patch.object(MainCode, "CHAT_PRELOAD", setting), \
                    mock.patch("JarvisAdvancedBot.ChatBrain.warm_up") as warm_up:
                MainCode._prewarm()
                thread.call_args.kwargs["target"]()                      # run the background job now
            self.assertEqual(warm_up.call_count, loaded, setting)

    def test_the_language_model_is_loaded_in_the_background_while_the_greeting_is_spoken(self):
        with mock.patch.object(MainCode.threading, "Thread") as thread, mock.patch("JarvisAdvancedBot.NLU.warm_up") as warm_up:
            MainCode._prewarm()
            warm_up.assert_not_called()                                  # only the background job loads it
            thread.call_args.kwargs["target"]()
        warm_up.assert_called_once()

    def test_the_session_says_which_brain_it_is_using(self):
        for chat, expected in ((True, "chat with llama3.2:3b"), (False, "no chat model running")):
            out = io.StringIO()
            with mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=False), \
                    mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=chat), \
                    mock.patch("JarvisAdvancedBot.ChatBrain.choose_model", return_value="llama3.2:3b"), redirect_stdout(out):
                MainCode._announce_brain()
            self.assertIn(expected, out.getvalue())
            self.assertIn("free local commands", out.getvalue())


class DispatcherTests(unittest.TestCase):
    def handle(self, text, ai=False, brain_reply="Hello from Claude.", chat=None, loaded=False):
        """Run one command. ``chat`` is the sentences a running chat model would say (None = no chat model running)."""
        spoken, self.streamed = [], []

        def speak_stream(sentences, **kwargs):
            self.streamed.append(list(sentences))
            self.stream_options = kwargs
            return bool(self.streamed[-1])

        with mock.patch("JarvisAdvancedBot.JarvisAiBrain.ai_available", return_value=ai), \
                mock.patch("JarvisAdvancedBot.JarvisAiBrain.ReplyBrain", return_value=brain_reply) as reply, \
                mock.patch("JarvisAdvancedBot.JarvisAiBrain.ResetBrain") as reset, \
                mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=chat is not None),                 mock.patch("JarvisAdvancedBot.ChatBrain.is_loaded", return_value=loaded), \
                mock.patch("JarvisAdvancedBot.ChatBrain.reply_sentences", side_effect=lambda query: iter(chat or [])) as self.chat_asked, \
                mock.patch("JarvisAdvancedBot.ChatBrain.forget") as self.chat_forgotten, \
                mock.patch.object(MainCode, "SpeakStream", side_effect=speak_stream), \
                mock.patch.object(MainCode, "Speak", spoken.append), mock.patch("builtins.print"):
            outcome = MainCode.handle_command(text, ask=lambda question: "")
        return outcome, spoken, reply, reset

    def test_unknown_commands_get_an_honest_answer_that_helps(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value=None),                 mock.patch("JarvisAdvancedBot.FreeBrain.available", return_value=False):
            outcome, spoken, _, _ = self.handle("kalkulator please")
        self.assertIsNone(outcome)
        self.assertIn("didn't understand that as a command", spoken[0])
        self.assertIn("open calculator", spoken[0])

    def test_questions_no_command_covers_are_answered_by_the_free_brain(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value="Because of scattering."):
            _, spoken, _, _ = self.handle("blorp why is the sky blue zzz")
        self.assertEqual(spoken, ["Because of scattering."])

    def test_a_running_chat_model_answers_what_no_command_covers_sentence_by_sentence(self):
        outcome, spoken, _, _ = self.handle("blorp why is the sky blue zzz", chat=["Because of scattering.", "Blue light bends most."])
        self.assertIsNone(outcome)
        self.assertEqual(self.streamed, [["Because of scattering.", "Blue light bends most."]])
        self.assertEqual(spoken, [])                                     # SpeakStream said it, so it is not said again
        self.assertEqual(self.stream_options, {"if_slow": "One moment, sir.", "after": 3.0})      # the model has to load first
        self.chat_asked.assert_called_once_with("blorp why is the sky blue zzz")

    def test_how_long_the_answer_took_is_printed_once_it_has_been_said(self):
        out = io.StringIO()
        with mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=True),                 mock.patch("JarvisAdvancedBot.ChatBrain.is_loaded", return_value=True),                 mock.patch("JarvisAdvancedBot.ChatBrain.reply_sentences", return_value=iter(["Because."])),                 mock.patch("JarvisAdvancedBot.ChatBrain.last_timing", ": (chat: test - took 1s)"),                 mock.patch.object(MainCode, "SpeakStream", return_value=True), redirect_stdout(out):
            self.assertTrue(MainCode._chat("why"))
        self.assertIn(": (chat: test - took 1s)", out.getvalue())

    def test_a_model_that_is_already_loaded_is_given_longer_before_jarvis_says_one_moment(self):
        self.handle("blorp why is the sky blue zzz", chat=["Because of scattering."], loaded=True)
        self.assertEqual(self.stream_options["after"], 8.0)

    def test_a_sentence_that_was_cut_off_is_not_given_to_the_chat_model_to_invent_an_answer_for(self):
        for said in ("can you", "ok can you tell me the square root of", "cube root of", "what is your"):
            outcome, spoken, _, _ = self.handle(said, chat=["Never said."])
            self.assertIsNone(outcome)
            self.assertEqual(spoken, ["Sorry sir, I only caught part of that. Could you say it again?"], said)
            self.chat_asked.assert_not_called()

    def test_cut_off_sentences_get_the_same_answer_when_no_chat_model_is_running(self):
        self.assertEqual(self.handle("can you")[1], ["Sorry sir, I only caught part of that. Could you say it again?"])

    def test_a_command_that_ends_in_a_small_word_is_still_a_command(self):
        spoken = self.handle("what's the weather in", chat=["Never said."])[1]
        self.assertNotIn("only caught part", " ".join(spoken))

    def test_the_throat_clearing_in_front_of_a_question_is_not_what_the_model_is_asked(self):
        self.handle("ok how much is there distance zzz", chat=["It depends."])
        self.chat_asked.assert_called_once_with("ok how much is there distance zzz")        # (the chat brain itself tidies it)

    def test_two_commands_joined_by_then_are_both_carried_out_in_order(self):
        outcome, spoken, _, _ = self.handle("what time is it then what is the date")
        self.assertIsNone(outcome)
        self.assertEqual(len(spoken), 2)
        self.assertTrue(spoken[0].startswith("It's "))
        self.assertTrue(spoken[1].startswith("Today is "))

    def test_then_go_to_sleep_ends_the_session_after_the_first_part_and_nothing_follows(self):
        outcome, spoken, _, _ = self.handle("what time is it then go to sleep then what is the date")
        self.assertEqual(outcome, "sleep")
        self.assertEqual(len(spoken), 2)                                         # the time, and the goodbye; not the date
        self.assertIn("Going to sleep", spoken[1])

    def test_the_whole_sentence_is_recorded_once_not_once_per_part(self):
        recorded = []
        with mock.patch.object(MainCode.transcript, "record", side_effect=lambda who, text, **kw: recorded.append((who, text))):
            self.handle("what time is it then what is the date")
        self.assertEqual(recorded, [("you", "what time is it then what is the date")])

    def test_with_claude_a_then_is_left_for_claude_to_understand(self):
        _, spoken, reply, _ = self.handle("what time is it then what is the date", ai=True)
        reply.assert_called_once_with("what time is it then what is the date")

    def test_questions_about_the_users_own_list_or_schedule_are_never_made_up_by_the_chat_model(self):
        for said in ("skechers vibrate for tomorrow then what's on my today list for tomorrow", "what's on my calendar tomorrow",
                     "do i have any appointments today"):
            outcome, spoken, _, _ = self.handle(said, chat=["Your list includes: wake up, breakfast, lunch."])
            self.assertIsNone(outcome)
            self.assertEqual(len(spoken), 1, said)
            self.assertIn("I won't guess what is on it", spoken[0])
            self.assertIn("what's on my to do list", spoken[0])
            self.chat_asked.assert_not_called()

    def test_general_talk_about_schedules_and_lists_is_still_for_the_chat_model(self):
        for said in ("what's a good study schedule for the week", "list the planets in order", "any advice for planning my day"):
            self.handle(said, chat=["Here is some advice."])
            self.chat_asked.assert_called_with(said)

    def test_a_command_never_goes_to_the_chat_model(self):
        _, spoken, _, _ = self.handle("what time is it", chat=["Never said."])
        self.chat_asked.assert_not_called()
        self.assertTrue(spoken[0].startswith("It's "))

    def test_if_the_chat_model_has_nothing_to_say_the_other_brains_answer(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value="From the cloud or the web."):
            _, spoken, _, _ = self.handle("blorp why is the sky blue zzz", chat=[])
        self.assertEqual(spoken, ["From the cloud or the web."])

    def test_with_no_chat_model_running_it_is_not_asked(self):
        with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value="Web answer."):
            self.handle("blorp why is the sky blue zzz")
        self.chat_asked.assert_not_called()

    def test_a_fresh_start_clears_the_conversation_without_claude_too(self):
        for phrase in ("new chat", "start a new conversation", "forget everything", "clear your memory", "ok can you clear the chat",
                       "Jarvis, please start a fresh chat", "could you reset the conversation please", "start over", "wipe the history"):
            _, spoken, reply, _ = self.handle(phrase, chat=["Never said."])
            self.assertIn("Fresh start", spoken[0], phrase)
            self.chat_forgotten.assert_called_once()
            self.chat_asked.assert_not_called()
            reply.assert_not_called()

    def test_forgetting_what_the_user_told_it_is_not_mistaken_for_a_fresh_start(self):
        _, spoken, _, _ = self.handle("forget everything you know about me", chat=["Never said."])
        self.chat_forgotten.assert_not_called()
        self.assertNotIn("Fresh start", " ".join(spoken))

    def test_the_hint_to_set_up_a_chat_model_goes_away_once_one_is_running(self):
        for running, hinted in ((True, False), (False, True)):
            with mock.patch("JarvisAdvancedBot.FreeBrain.answer", return_value=None), \
                    mock.patch("JarvisAdvancedBot.FreeBrain.available", return_value=False), \
                    mock.patch("JarvisAdvancedBot.ChatBrain.available", return_value=running):
                reply = MainCode._answer_anything("calculater please")
            self.assertEqual("install the free Ollama" in reply, hinted, running)

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
