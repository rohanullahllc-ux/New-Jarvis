"""Tests that what you say reaches the right tool with the right arguments:  python -m unittest tests.test_localbrain -v

Every tool is replaced by a recorder, so these tests check the ROUTING (including the order of the
patterns, which decides what wins when two could match) without doing anything real.
"""
import datetime
import io
import os
import time
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import LocalBrain as L  # noqa: E402
from JarvisAdvancedBot import tools as T  # noqa: E402


class BrainCase(unittest.TestCase):
    def setUp(self):
        self.calls, self.results, self.raises, self.questions = [], {}, {}, []

        def recorder(name):
            def run(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                if name in self.raises:
                    raise self.raises[name]
                return self.results.get(name, f"<{name}>")
            return run

        names = [tool.name for tool in T.TOOLS] + ["weather_report"]
        for patcher in (
            mock.patch.multiple(T, **{name: recorder(name) for name in names}),
            mock.patch("speech.Speak"),
            mock.patch.object(L, "read_clipboard", return_value=""),
            mock.patch.object(L, "HOME_CURRENCY", "PKR"),
            mock.patch.object(L, "DEFAULT_CITY", "Peshawar"),
            mock.patch.object(L.FreeBrain, "available", return_value=False),     # a real key in .env must not change routing
            mock.patch.object(L.ChatBrain, "available", return_value=False),     # nor must an Ollama that happens to be running
            mock.patch.object(L.NLU, "MODEL_FILE", Path("no such language model.joblib")),     # nor a model trained on this PC
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        L.NLU.reset()
        self.addCleanup(L.NLU.reset)
        self.spoken = sys.modules["speech"].Speak

    def say(self, phrase, answers=()):
        """Run a command; ``answers`` are what the user says to Jarvis's follow-up questions."""
        script = list(answers)
        self.calls.clear()
        self.questions.clear()

        def ask(question):
            self.questions.append(question)
            return script.pop(0) if script else ""

        out = io.StringIO()
        with redirect_stdout(out):
            return L.LocalReply(phrase, ask)

    def routes(self, phrase, name, *args, answers=(), **kwargs):
        """Assert the phrase calls exactly one tool, with exactly these arguments; returns the reply."""
        reply = self.say(phrase, answers)
        self.assertEqual(self.calls, [(name, args, kwargs)], phrase)
        return reply

    def no_tool(self, phrase, answers=()):
        reply = self.say(phrase, answers)
        self.assertEqual(self.calls, [], phrase)
        return reply


class EverydayCommandTests(BrainCase):
    def test_time_and_date_need_no_tool(self):
        self.assertRegex(self.no_tool("what time is it"), r"^It's \d{1,2}:\d{2} [AP]M\.$")
        self.assertIn(str(datetime.date.today().year), self.no_tool("what's the date"))

    def test_questions_about_the_voice_get_a_helpful_answer(self):
        for phrase in ("why are you not speaking", "why aren't you talking", "why are you never speaking to me", "say something",
                       "can you speak", "are you there", "can you hear me", "test your voice", "voice test"):
            with mock.patch.object(L.config, "TTS_ENABLED", True):
                reply = self.no_tool(phrase)
            self.assertIn("I'm speaking now", reply, phrase)
        with mock.patch.object(L.config, "TTS_ENABLED", False):
            self.assertIn("switched off", self.no_tool("why are you not speaking"))

    def test_greetings_and_help(self):
        self.assertTrue(self.no_tool("hello"))
        reply = self.no_tool("what can you do")
        self.assertIn("chat about almost anything", reply)
        self.assertLess(len(reply), 260)                                  # it used to be 400 characters: 25 seconds of talking

    def test_reminders(self):
        self.routes("remind me in 10 minutes to drink water", "set_reminder", message="drink water", minutes_from_now=10.0)
        self.routes("set a timer for half an hour", "set_reminder", message="Your timer is done", minutes_from_now=30)
        self.routes("remind me at 7:30 pm to pray", "set_reminder", message="pray", at_time="19:30")
        reply = self.routes("remind me to call mum", "add_task", "call mum")
        self.assertIn("to-do list", reply)

    def test_reminder_text_keeps_the_capitals_you_typed(self):
        self.routes("Remind me in 5 minutes to call Ali", "set_reminder", message="call Ali", minutes_from_now=5.0)

    def test_a_reminder_without_a_time_asks_for_one(self):
        self.routes("set an alarm", "set_reminder", message="Wake up, sir", minutes_from_now=10.0, answers=["in ten minutes"])
        self.assertEqual(len(self.questions), 1)

    def test_to_do_list(self):
        self.routes("add buy bread to my todo list", "add_task", "buy bread")
        self.routes("add Call Ali to my to-do list", "add_task", "Call Ali")
        self.routes("what's on my to do list", "list_tasks")
        self.routes("remove task 2", "remove_task", 2)
        self.routes("create a new task finish homework", "add_task", "finish homework")
        self.routes("add a task", "add_task", "wash the car", answers=["wash the car"])

    def test_notes(self):
        self.routes("take a note that the exam is on friday", "take_note", "the exam is on friday")
        self.routes("Take a note that Ali called", "take_note", "Ali called")
        self.routes("read my notes", "read_notes", "")
        self.routes("write a note", "take_note", "buy milk", answers=["buy milk"])

    def test_password_joke_screenshot(self):
        self.routes("generate a 20 character password", "generate_password", 20)
        self.routes("give me a strong password", "generate_password", 16)
        self.routes("tell me a joke", "get_joke")
        self.routes("take a screenshot", "take_screenshot")

    def test_searching(self):
        self.routes("youtube lo fi beats", "youtube", "lo fi beats", play=False)
        self.routes("google python tutorials", "search_google", "python tutorials")
        self.routes("play despacito", "youtube", "despacito")

    def test_keyboard_shortcuts_and_media_keys(self):
        self.routes("new tab", "browser_action", "new_tab")
        self.routes("show desktop", "windows_action", "show_desktop")
        self.routes("lock the screen", "windows_action", "lock_screen")
        self.routes("full screen", "youtube_control", "fullscreen")
        self.routes("volume up", "media_control", "volume_up", 5)
        self.routes("mute", "media_control", "mute", 1)
        self.routes("next song", "media_control", "next_track", 1)
        self.routes("pause", "media_control", "play_pause", 1)

    def test_maths_needs_no_tool(self):
        self.assertEqual(self.no_tool("what is 15 percent of 200"), "That's 30.")
        self.assertEqual(self.no_tool("calculate 2 plus 3 times 4"), "That's 14.")
        self.assertEqual(self.no_tool("square root of 144"), "That's 12.")

    def test_money(self):
        self.routes("bitcoin price", "get_crypto_price", "bitcoin", "usd")
        self.routes("what is the price of ethereum in pkr", "get_crypto_price", "ethereum", "pkr")
        self.routes("100 dollars in rupees", "convert_currency", 100.0, "USD", "PKR")
        self.routes("dollar rate", "convert_currency", 1, "USD", "PKR")
        self.routes("convert 100 dollars to rupees", "convert_currency", 100.0, "USD", "PKR")      # not Wolfram

    def test_the_home_currency_comes_from_settings(self):
        with mock.patch.object(L, "HOME_CURRENCY", "INR"):
            self.routes("dollar rate", "convert_currency", 1, "USD", "INR")

    def test_weather_location_and_pc(self):
        self.routes("weather in london", "weather_report", "london")
        self.routes("what's the weather", "weather_report", "Peshawar")
        self.routes("where am i", "get_my_location")
        self.routes("system status", "get_system_status")

    def test_pc_questions_pick_the_right_detail(self):
        for phrase, topic in (("what cpu do i have", "cpu"), ("how much ram do i have", "memory"),
                              ("disk space", "disks"), ("what is my ip address", "network"),
                              ("which windows version is this", "system")):
            self.routes(phrase, "get_system_details", topic)

    def test_battery_is_read_straight_from_the_pc(self):
        with mock.patch.object(L.psutil, "sensors_battery", return_value=SimpleNamespace(percent=44.0, power_plugged=True)):
            self.assertEqual(self.no_tool("how is the battery"), "The battery is at 44 percent and charging.")

    def test_translation(self):
        reply = self.routes("translate good morning to urdu", "translate_text", "good morning", "urdu")
        self.assertEqual(reply, "In Urdu, that's: <translate_text>")
        self.results["translate_text"] = "صبح بخیر"
        shown = []
        with mock.patch("speech.Show", side_effect=shown.append):
            reply = self.say("translate good morning to urdu")
        self.assertEqual(reply, "")                                       # what is said is the heads-up; the Urdu is only shown
        self.assertEqual(shown, ["صبح بخیر"])
        self.assertIn("Here is the Urdu translation, sir.", [call.args[0] for call in self.spoken.call_args_list])

    def test_apps_and_websites(self):
        self.routes("open chrome", "open_app", "chrome")
        self.routes("open github", "open_website", "https://github.com")
        self.routes("launch example.com", "open_website", "example.com")
        self.routes("close chrome", "close_app", "chrome")
        self.assertIn("shut down the computer", self.no_tool("close the computer"))

    def test_knowledge_questions_go_to_wikipedia(self):
        self.routes("who is albert einstein", "search_wikipedia", "albert einstein")
        self.routes("tell me about the roman empire", "search_wikipedia", "the roman empire")

    def test_wikipedia_gaps_are_filled_by_wolfram_when_it_is_set_up(self):
        self.raises["search_wikipedia"] = ToolError("Nothing found on Wikipedia for x.")
        with mock.patch.object(L.config, "WOLFRAM_APP_ID", "id"):
            self.assertEqual(self.say("what is the boiling point of lead"), "<ask_wolfram_alpha>")
            self.assertEqual([call[0] for call in self.calls], ["search_wikipedia", "ask_wolfram_alpha"])
        with mock.patch.object(L.config, "WOLFRAM_APP_ID", ""):
            self.assertEqual(self.say("what is the boiling point of lead"), "Nothing found on Wikipedia for x.")

    def test_unknown_requests_return_none_so_the_session_can_say_so(self):
        self.assertIsNone(self.no_tool("blorp zzz qqq"))
        self.assertIsNone(self.no_tool(""))


class NameTests(BrainCase):
    def test_jarvis_knows_the_name_it_was_given_without_asking_a_model(self):
        with mock.patch.object(L.config, "USER_NAME", "Mr Khan"):
            for phrase in ("what is my name", "what's my name", "who am i", "do you know my name", "what do you call me"):
                self.assertEqual(self.no_tool(phrase), "You're Mr Khan, sir.", phrase)

    def test_asking_for_jarvis_own_name_is_still_a_different_question(self):
        self.assertIn("I'm Jarvis", self.no_tool("what is your name"))


class ChatRoutingTests(BrainCase):
    """With a chat model running, open questions are left for it to answer (MainCode speaks the answer as it arrives)."""

    def test_open_questions_are_left_for_the_chat_model(self):
        with mock.patch.object(L.ChatBrain, "available", return_value=True):
            self.assertIsNone(self.no_tool("who is albert einstein"))
            self.assertIsNone(self.no_tool("tell me about the roman empire"))
            self.assertIsNone(self.no_tool("what is the best way to learn python"))

    def test_an_explicit_wikipedia_request_still_goes_to_wikipedia(self):
        with mock.patch.object(L.ChatBrain, "available", return_value=True):
            self.routes("wikipedia alan turing", "search_wikipedia", "alan turing")
            self.routes("wikipedia for the roman empire", "search_wikipedia", "the roman empire")

    def test_commands_are_never_sent_to_the_chat_model(self):
        with mock.patch.object(L.ChatBrain, "available", return_value=True):
            self.routes("what's the weather in london", "weather_report", "london")
            self.assertIn("It's", self.no_tool("what time is it"))

    def test_without_a_chat_model_a_cloud_key_still_answers_before_wikipedia(self):
        with mock.patch.object(L.FreeBrain, "available", return_value=True),                 mock.patch.object(L.FreeBrain, "ask_model", return_value="From the cloud.") as cloud:
            self.assertEqual(self.no_tool("who is albert einstein"), "From the cloud.")
        cloud.assert_called_once()


class MemoryCommandTests(BrainCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(L.ChatBrain, "FACTS_FILE", Path(folder.name) / "memory.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_remember_that_keeps_a_fact_with_the_capital_letters_it_was_said_with(self):
        self.assertEqual(self.no_tool("Remember that my brother's name is Ali"), "Okay sir, I'll remember that.")
        self.assertEqual(L.ChatBrain.facts(), ["my brother's name is Ali"])
        self.no_tool("remember my sister Sana lives in Lahore")
        self.assertEqual(L.ChatBrain.facts()[-1], "my sister Sana lives in Lahore")

    def test_remember_that_is_no_longer_a_note_but_taking_a_note_still_is(self):
        self.no_tool("remember that the wifi password is on the fridge")
        self.assertFalse(any(name == "take_note" for name, _, _ in self.calls))
        self.routes("take a note that buy milk", "take_note", "buy milk")

    def test_a_fact_never_swallows_the_command_said_after_then(self):
        reply = self.no_tool("remember that my favourite fruit is mango, then what do you remember about me new chat")
        self.assertEqual(L.ChatBrain.facts(), ["my favourite fruit is mango"])
        self.assertIn("Okay sir, I'll remember that.", reply)
        self.assertIn("didn't catch what you said after 'then'", reply)

    def test_a_fact_without_then_is_kept_whole_and_gets_no_apology(self):
        self.assertEqual(self.no_tool("remember that my brother is Ali"), "Okay sir, I'll remember that.")
        self.assertEqual(L.ChatBrain.facts(), ["my brother is Ali"])

    def test_remember_to_do_something_is_not_a_fact(self):
        self.say("remember to call Ali")
        self.assertEqual(L.ChatBrain.facts(), [])

    def test_jarvis_can_say_what_it_remembers(self):
        self.assertIn("haven't asked me to remember anything", self.no_tool("what do you remember about me"))
        L.ChatBrain.remember("I like tea")
        L.ChatBrain.remember("my brother is Ali")
        for phrase in ("what do you remember about me", "what do you know about me", "what have I told you to remember",
                       "list my facts"):
            self.assertEqual(self.no_tool(phrase), "You asked me to remember: I like tea; my brother is Ali.", phrase)

    def test_a_long_list_of_facts_is_summarised(self):
        for n in range(9):
            L.ChatBrain.remember(f"fact {n}")
        reply = self.no_tool("what do you remember")
        self.assertIn("fact 8", reply)
        self.assertNotIn("fact 0", reply)
        self.assertIn("and 3 more", reply)

    def test_one_fact_can_be_forgotten_by_what_it_mentions(self):
        L.ChatBrain.remember("my brother is Ali")
        L.ChatBrain.remember("I like tea")
        self.assertEqual(self.no_tool("forget that my brother is Ali"), "Forgotten, sir.")
        self.assertEqual(L.ChatBrain.facts(), ["I like tea"])
        self.assertIn("don't have anything like that", self.no_tool("forget my favourite colour"))

    def test_all_facts_can_be_forgotten(self):
        L.ChatBrain.remember("one")
        L.ChatBrain.remember("two")
        for phrase in ("forget my facts", "forget everything you know about me", "clear all memories"):
            L.ChatBrain.remember("one")
            L.ChatBrain.remember("two")
            self.assertIn("forgotten 2 things", self.no_tool(phrase), phrase)
        self.assertIn("wasn't remembering anything", self.no_tool("forget my facts"))


class RealSessionFixesTests(BrainCase):
    """Each of these was said in a real session and was misunderstood or answered with an invention."""

    def tomorrow(self):
        return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    def test_i_mean_and_other_throat_clearing_in_front_of_a_command_is_ignored(self):
        self.assertEqual(L.normalize("ok sorry, i mean open the windows calendar"), "open the windows calendar")
        self.assertEqual(L.normalize("I mean can you write a note"), "write a note")
        self.assertEqual(L.normalize("well done"), "well done")                              # words that mean something stay
        self.routes("i mean can you write a note", "take_note", "buy milk", answers=["buy milk"])

    def test_jarvis_heard_as_assistant_and_a_repeat_after_a_miss_are_still_the_command(self):
        self.assertEqual(L.normalize("assistant calendar"), "calendar")
        self.assertEqual(L.normalize("hey assistant, open the calculator"), "open the calculator")
        self.assertEqual(L.normalize("i told you system calendar"), "system calendar")
        self.assertEqual(L.normalize("i said open the note"), "open the note")
        self.assertEqual(L.normalize("what is an assistant professor"), "what is an assistant professor")     # only at the start
        self.routes("assistant calendar", "open_utility_app", "calendar")
        self.routes("i told you system calendar", "open_app", "calendar")

    def test_the_windows_calendar_and_calculator_can_be_asked_for_with_or_without_a_verb(self):
        self.routes("system calendar", "open_app", "calendar")
        self.routes("i mean can you open the windows calendar", "open_app", "calendar")
        self.routes("can you open the system calculator", "open_app", "calculator")
        self.routes("windows calculator", "open_app", "calculator")
        self.routes("open the jarvis calendar", "open_utility_app", "calendar")

    def test_the_state_of_the_pc_is_a_report_not_a_guess(self):
        for phrase in ("what's the current status of pc", "how is my pc doing", "what is the health of my computer", "how's my laptop"):
            self.routes(phrase, "get_system_status")

    def test_the_space_station_as_it_is_often_misheard_and_the_latest_launches_in_the_plural(self):
        self.routes("where is is", "get_iss_location")
        self.routes("where is the ISS", "get_iss_location")
        self.routes("can you tell me the latest spacex launches", "spacex_latest_launch", "latest")
        self.routes("when are the next spacex launches", "spacex_latest_launch", "next")

    def test_questions_about_jarvis_own_password_are_never_answered_by_a_model_or_a_generator(self):
        for phrase in ("what's the current password of jarvis program", "tell me the jarvis password", "what is my unlock password",
                       "i forgot my login password"):
            reply = self.no_tool(phrase)
            self.assertIn("python gate.py --set-password", reply, phrase)
        self.routes("generate a password", "generate_password", 16)
        self.routes("give me a strong password", "generate_password", 16)
        self.assertNotIn("set-password", self.say("what is a good password for my bank") or "")      # advice: not the guard's business

    def test_passwords_and_card_numbers_are_not_kept_as_facts(self):
        for phrase in ("remember that my wifi password is hunter2", "remember my pin is 1234", "remember that my card number is 4111"):
            self.assertIn("rather not keep passwords", self.no_tool(phrase), phrase)

    def test_scheduling_a_task(self):
        self.routes("ok schedule a task", "add_task", "return the book", answers=["return the book"])       # asks what the task is
        self.assertEqual(self.questions, ["What's the task?"])
        self.routes("schedule return statement i will complete my assignment by tomorrow", "add_task",
                    "return statement i will complete my assignment", self.tomorrow())
        self.routes("schedule buy bread", "add_task", "buy bread", "")
        today = datetime.date.today()
        friday = (today + datetime.timedelta(days=(4 - today.weekday()) % 7 or 7)).isoformat()
        self.routes("schedule dentist on friday", "add_task", "dentist", friday)

    def test_asking_for_the_tasks_of_a_day(self):
        self.routes("can you check what task was casual for tomorrow", "list_tasks", self.tomorrow())
        self.routes("what's on my to do list for tomorrow", "list_tasks", self.tomorrow())
        self.routes("what task was scheduled", "list_tasks")
        self.routes("can you check my task and schedule", "list_tasks")
        self.routes("what's on my to do list", "list_tasks")

    def test_opening_a_note_is_not_reading_it(self):
        self.routes("can you open the note", "open_notes", "latest")
        self.routes("open note", "open_notes", "latest")
        self.routes("open the note file", "open_notes", "latest")
        self.routes("open my latest note", "open_notes", "latest")
        self.routes("open the notes", "open_notes", "folder")                    # all of them: the folder
        self.routes("open the notes folder", "open_notes", "folder")
        self.routes("open my notes app", "open_notes", "folder")
        self.assertEqual(self.say("open the note file"), "<open_notes>, sir.")
        self.routes("can you show me the saved note", "read_notes", "")
        self.routes("read my last note", "read_notes", "", True)

    def test_asking_where_the_screenshot_is_does_not_take_another_one(self):
        self.routes("screenshot", "take_screenshot")
        self.routes("take a screenshot", "take_screenshot")
        self.routes("capture the screen", "take_screenshot")
        self.assertIn("screenshots folder", self.routes("where is the screenshot was saved", "open_screenshots", "folder"))
        self.routes("where are my screenshots", "open_screenshots", "folder")
        self.routes("open the screenshot", "open_screenshots", "latest")
        self.routes("show me the last screenshot", "open_screenshots", "latest")
        self.routes("open the screenshots", "open_screenshots", "folder")

    def test_is_it_am_or_pm(self):
        for phrase in ("is it am or pm", "am or pm", "a.m. or p.m.", "is it a.m. or p.m.", "is it morning", "what part of the day is it"):
            self.assertRegex(self.no_tool(phrase), r"^It's \d{1,2}:\d\d [AP]M, so it's (?:morning|afternoon|evening|night), sir\.$")

    def test_cube_roots_are_worked_out_not_guessed(self):
        self.assertEqual(self.no_tool("i mean cube root of 215"), "That's 5.990726.")                 # a model said 6.013
        self.assertEqual(self.no_tool("what is the cube root of 27"), "That's 3.")
        self.assertEqual(self.no_tool("cube root of 8"), "That's 2.")
        self.assertEqual(self.no_tool("square root of 6000"), "That's 77.459667.")

    def test_a_place_with_its_country_goes_to_the_weather_tool_whole(self):
        self.routes("what's the weather in narayan khan in pakistan", "weather_report", "narayan khan in pakistan")

    def test_a_short_acknowledgement_is_not_a_question_for_a_model(self):
        for phrase in ("ok perfect", "awesome", "got it", "alright"):
            self.assertIn(self.no_tool(phrase), ("You're welcome, sir.", "Always a pleasure, sir.", "Happy to help."), phrase)


class TwoCommandsInOneBreathTests(BrainCase):
    """"Do this, then that": split only when every piece is something Jarvis understands."""

    def test_pieces_joined_by_then_are_run_one_after_the_other(self):
        self.assertEqual(L.split_commands("schedule buy bread for tomorrow then what's on my to do list for tomorrow"),
                         ["schedule buy bread for tomorrow", "what's on my to do list for tomorrow"])
        self.assertEqual(L.split_commands("what time is it and then what is the date"), ["what time is it", "what is the date"])
        self.assertEqual(L.split_commands("take a screenshot, then open the note, then go to sleep"),
                         ["take a screenshot", "open the note", "go to sleep"])
        self.assertEqual(L.split_commands("tell me a joke after that play despacito"), ["tell me a joke", "play despacito"])

    def test_a_sentence_that_only_contains_then_stays_whole(self):
        for text in ("tell me what happens then", "if it rains then what", "and then", "then", "what is the capital of france",
                     "blorp zzz then qqq yyy", "write a note then sing me a song about clouds"):
            self.assertEqual(L.split_commands(text), [text], text)

    def test_understanding_is_about_commands_not_questions(self):
        self.assertTrue(L.understands("what's on my to do list"))
        self.assertTrue(L.understands("ok take a screenshot"))
        self.assertTrue(L.understands("go to sleep"))
        self.assertTrue(L.understands("new chat"))
        self.assertFalse(L.understands("who is alan turing"))                    # that is the catch-all question pattern
        self.assertFalse(L.understands("blorp zzz"))
        self.assertFalse(L.understands(""))


class ForgivingPhrasingTests(BrainCase):
    """Phrasings people (and the speech recogniser) actually produce for things Jarvis already does."""

    def test_notes_in_every_shape(self):
        for phrase in ("show note", "show notes", "read note", "notes", "note", "my notes",
                       "jarvis notes", "what notes do i have", "do i have any notes", "see my notes", "check my notes"):
            self.routes(phrase, "read_notes", "")

    def test_the_latest_note(self):
        for phrase in ("read my last note", "show the latest note", "what was my last note", "last note"):
            self.routes(phrase, "read_notes", "", True)

    def test_jarvis_own_tools_by_bare_name_or_with_filler(self):
        for phrase in ("calculator", "jarvis calculator", "open calculator", "open the calculator app", "launch calc", "calc",
                       "show me the calculator", "start the calculator window"):
            self.routes(phrase, "open_utility_app", "calculator")
        for phrase in ("calendar", "jarvis calendar", "calender", "open the calendar app", "show my calendar"):
            self.routes(phrase, "open_utility_app", "calendar")
        for phrase in ("currency converter", "currency convertor", "open currency", "jarvis currency converter"):
            self.routes(phrase, "open_utility_app", "currency_converter")

    def test_the_windows_one_only_when_asked_for(self):
        self.routes("open the system calculator", "open_app", "calculator")
        self.routes("open windows calculator", "open_app", "calculator")
        self.routes("open default calendar app", "open_app", "calendar")

    def test_other_bare_words(self):
        self.routes("to do", "list_tasks")
        self.routes("tasks", "list_tasks")
        self.routes("weather", "weather_report", "Peshawar")
        self.routes("jarvis screenshot", "take_screenshot")

    def test_bare_words_do_not_swallow_real_commands(self):
        self.routes("open chrome", "open_app", "chrome")
        self.routes("play time of my life", "youtube", "time of my life")
        self.routes("take a note that the time is wrong", "take_note", "the time is wrong")


class PowerTests(BrainCase):
    def test_nothing_is_switched_off_without_a_clear_yes(self):
        for answers in ([], ["no"], ["yes please do not"], ["maybe"], ["cancel"]):
            self.no_tool("shut down the computer", answers)
        self.assertTrue(all("shut down" in q for q in self.questions))

    def test_a_clear_yes_does_it(self):
        self.routes("shut down the computer", "system_power_action", "shutdown", confirmed=True, answers=["yes"])
        self.routes("shutdown", "system_power_action", "shutdown", confirmed=True, answers=["yeah go ahead"])
        self.routes("restart the pc", "system_power_action", "restart", confirmed=True, answers=["sure"])
        self.routes("put the computer to sleep", "system_power_action", "sleep", confirmed=True, answers=["ok"])

    def test_the_refusal_says_what_was_not_done(self):
        self.assertEqual(self.no_tool("restart the computer", ["no"]), "Okay, I won't restart the computer.")

    def test_cancelling_a_shutdown_needs_no_confirmation(self):
        self.routes("cancel the shutdown", "system_power_action", "cancel")
        self.routes("abort restart", "system_power_action", "cancel")
        self.assertEqual(self.questions, [])


class FolderAndWindowTests(BrainCase):
    def test_drives_and_folders(self):
        self.routes("open drive d", "open_folder", "d")
        self.routes("open the c drive", "open_folder", "c")
        self.routes("open downloads", "open_folder", "downloads")
        self.routes("open my documents folder", "open_folder", "documents")
        self.routes("open music folder", "open_folder", "music")
        self.routes("show my documents", "open_folder", "documents")
        self.routes("open desktop", "open_folder", "desktop")
        self.routes("show desktop", "windows_action", "show_desktop")                    # minimise windows, not a folder
        self.routes("show desktop folder", "open_folder", "desktop")
        self.routes("open file explorer", "windows_action", "file_explorer")
        self.routes("open my files", "windows_action", "file_explorer")

    def test_music_alone_is_still_an_app_not_a_folder(self):
        self.routes("open music", "open_app", "music")

    def test_browser_downloads_are_different_from_the_downloads_folder(self):
        self.routes("show browser downloads", "browser_action", "downloads")

    def test_jarvis_own_windows(self):
        self.routes("open calculator", "open_utility_app", "calculator")
        self.routes("open the currency converter", "open_utility_app", "currency_converter")
        self.routes("open currency convertor", "open_utility_app", "currency_converter")
        self.routes("open calendar", "open_utility_app", "calendar")

    def test_windows_own_calculator_is_the_fallback(self):
        self.raises["open_utility_app"] = ToolError("The calculator window isn't installed.")
        reply = self.say("open calculator")
        self.assertEqual([call[0] for call in self.calls], ["open_utility_app", "open_app"])
        self.assertEqual(self.calls[1][1], ("calculator",))
        self.assertIn("calculator", reply)


class SpaceTests(BrainCase):
    def test_nasa_pictures(self):
        self.routes("nasa picture of the day", "nasa_picture_of_the_day")
        self.routes("show me the astronomy picture of the day", "nasa_picture_of_the_day")

    def test_mars_photos_and_the_slow_rover_gets_a_heads_up(self):
        self.routes("show me mars photos", "nasa_mars_photos", "curiosity")
        self.spoken.assert_not_called()
        self.routes("latest perseverance photo", "nasa_mars_photos", "perseverance")
        self.spoken.assert_called_once()
        self.assertIn("twenty seconds", self.spoken.call_args[0][0])

    def test_facts_about_planets_beat_weather_and_wikipedia(self):
        self.routes("tell me about jupiter", "nasa_solar_body_facts", "jupiter", "all")
        self.routes("facts about the sun", "nasa_solar_body_facts", "sun", "all")
        self.routes("how far is the moon", "nasa_solar_body_facts", "moon", "distance")
        self.routes("what is the temperature of mars", "nasa_solar_body_facts", "mars", "temperature")
        self.routes("how hot is venus", "nasa_solar_body_facts", "venus", "temperature")
        self.routes("how many moons does saturn have", "nasa_solar_body_facts", "saturn", "moons")
        self.routes("gravity on the moon", "nasa_solar_body_facts", "moon", "gravity")
        self.routes("how big is the sun", "nasa_solar_body_facts", "sun", "size")
        self.routes("how long is a day on mars", "nasa_solar_body_facts", "mars", "day")
        self.routes("how long is a year on neptune", "nasa_solar_body_facts", "neptune", "year")

    def test_other_questions_about_these_words_are_not_hijacked(self):
        self.routes("tell me about the moon landing", "search_wikipedia", "the moon landing")
        self.routes("play mars by thirty seconds to mars", "youtube", "mars by thirty seconds to mars")

    def test_asteroids(self):
        self.routes("any asteroids today", "nasa_near_earth_objects")
        self.say("asteroids this week")
        name, args, _ = self.calls[0]
        self.assertEqual(name, "nasa_near_earth_objects")
        first, last = (datetime.date.fromisoformat(day) for day in args)
        self.assertEqual((last - first).days, 6)

    def test_the_space_station_and_spacex(self):
        self.routes("where is the iss", "get_iss_location")
        self.routes("where is the international space station", "get_iss_location")
        self.routes("when is the next spacex launch", "spacex_latest_launch", "next")
        self.routes("next launch", "spacex_latest_launch", "next")
        self.routes("spacex latest launch", "spacex_latest_launch", "latest")
        self.routes("what was the last launch", "spacex_latest_launch", "latest")
        self.routes("tell me about spacex", "spacex_company_info")

    def test_starlink_count_gets_a_heads_up(self):
        self.routes("how many starlink satellites are there", "spacex_starlink_count")
        self.spoken.assert_called_once()

    def test_distance_to_a_place_that_is_not_a_planet_goes_to_the_map(self):
        self.routes("how far is islamabad", "show_on_map", "islamabad")
        self.routes("show lahore on the map", "show_on_map", "lahore")
        self.routes("Navigate to Karachi", "show_on_map", "Karachi")


class ProductivityTests(BrainCase):
    def test_looking_at_the_time_table(self):
        self.routes("what's on my time table", "get_timetable_block")
        self.routes("what should i be doing now", "get_timetable_block")
        self.routes("show my schedule", "get_timetable_block")

    def test_adding_to_the_time_table(self):
        self.routes("add study from 6 to 9 in the morning to my time table", "add_timetable_block", "06:00", "09:00", "study")
        self.routes("add gym from 6 to 8 in the evening to my schedule", "add_timetable_block", "18:00", "20:00", "gym")
        self.routes("add sleep from 10 pm to 6 am to my routine", "add_timetable_block", "22:00", "06:00", "sleep")
        self.routes("Add Maths from 14:30 to 16:00 to my time table", "add_timetable_block", "14:30", "16:00", "Maths")

    def test_impossible_times_are_refused_politely(self):
        self.assertIn("didn't catch", self.no_tool("add study from 25 to 27 to my time table"))

    def test_books(self):
        self.routes("read page 5 of the book story", "read_book_page", "story", 5)
        self.routes("read the book", "read_book_page", "", 1)
        self.routes("read the book story page 3", "read_book_page", "story", 3)

    def test_a_long_page_is_shortened_for_the_ear_but_printed_in_full(self):
        self.results["read_book_page"] = "One. Two. Three. Four. Five. Six."
        out = io.StringIO()
        with redirect_stdout(out):
            reply = L.LocalReply("read the book", lambda q: "")
        self.assertEqual(reply, "One. Two. Three. Four. The rest of the page is on the screen.")
        self.assertIn("Five. Six.", out.getvalue())

    def test_acronyms(self):
        self.routes("make an acronym for portable network graphics", "make_acronym", "portable network graphics")
        self.routes("acronym", "make_acronym", "random access memory", answers=["random access memory"])

    def test_new_folders_keep_their_capitals(self):
        self.routes("create a folder named Projects on the desktop", "create_folder", "Projects", "desktop")
        self.routes("make a new folder called my files in documents", "create_folder", "my files", "documents")
        self.routes("create a folder", "create_folder", "Taxes", "documents", answers=["Taxes"])

    def test_wolfram(self):
        self.routes("wolfram distance from earth to mars", "ask_wolfram_alpha", "distance from earth to mars")
        self.routes("convert the population of france to a number", "ask_wolfram_alpha", "the population of france to a number")


class UnitConversionTests(BrainCase):
    """Everyday conversions are worked out here, offline; Wolfram Alpha is only for what these cannot do."""

    def test_common_conversions_need_no_tool_and_no_key(self):
        for phrase, expected in (("convert 5 miles to kilometres", "5 miles is 8.0467 kilometres."),
                                 ("5 miles in kilometres", "5 miles is 8.0467 kilometres."),
                                 ("what is 100 kg in pounds", "100 kilograms is 220.46 pounds."),
                                 ("how many feet in a mile", "1 mile is 5,280 feet."),
                                 ("how many centimetres are in an inch", "1 inch is 2.54 centimetres."),
                                 ("convert 1,000 metres to miles", "1,000 metres is 0.621371 miles."),
                                 ("three gallons to litres", "3 gallons is 11.3562 litres."),
                                 ("what is 72 fahrenheit in celsius", "72 fahrenheit is 22.2222 celsius."),
                                 ("convert 0 celsius to kelvin", "0 celsius is 273.15 kelvin."),
                                 ("ten kilometres per hour to miles per hour", "10 kilometres per hour is 6.2137 miles per hour.")):
            self.assertEqual(self.no_tool(phrase), expected, phrase)

    def test_things_that_cannot_be_compared_are_explained(self):
        self.assertEqual(self.no_tool("5 kilograms to metres"), "Kilograms and metres measure different things, sir.")

    def test_money_is_still_money_and_the_rest_still_goes_to_wolfram(self):
        self.routes("convert the population of france to a number", "ask_wolfram_alpha", "the population of france to a number")
        reply = self.say("100 dollars in rupees")
        self.assertNotIn("measure different things", reply or "")


class WorldTests(BrainCase):
    def test_covid_figures_find_the_country_in_the_sentence(self):
        self.routes("covid cases in pakistan", "get_disease_outbreak_stats", "pakistan")
        self.routes("coronavirus stats", "get_disease_outbreak_stats", "")
        self.routes("how many covid cases are there in the united states today", "get_disease_outbreak_stats", "united states")
        self.routes("covid worldwide", "get_disease_outbreak_stats", "")

    def test_business_names(self):
        self.routes("business names for coffee shop", "generate_business_names", "coffee shop")
        self.routes("name ideas for my bakery", "generate_business_names", "bakery")
        self.routes("suggest some names for my startup", "generate_business_names", "startup")
        self.routes("business names", "generate_business_names", "tea", answers=["tea"])

    def test_little_things(self):
        self.routes("tell me a random fact", "get_random_fact", "any")
        self.routes("cat facts", "get_random_fact", "cat")
        self.routes("i am bored", "get_random_activity")
        self.routes("give me some advice", "get_random_advice")
        self.routes("show me a dog picture", "get_dog_image")

    def test_the_gags(self):
        self.routes("crack a password", "password_cracking_demo", 8)
        self.routes("crack a 10 character password", "password_cracking_demo", 10)
        self.routes("hack a random person", "hack_a_random_profile")
        self.routes("start hacking", "hack_a_random_profile")

    def test_instagram_pictures(self):
        self.routes("instagram profile picture of natgeo", "instagram_profile_picture", "natgeo", True)
        self.routes("show instagram profile picture of natgeo", "instagram_profile_picture", "natgeo", False)
        self.routes("download instagram dp of natgeo", "instagram_profile_picture", "natgeo", True)
        self.routes("instagram profile picture", "instagram_profile_picture", "natgeo", True, answers=["@natgeo"])

    def test_wifi_passwords_need_a_network_name(self):
        self.routes("wifi password for home net", "get_saved_wifi_password", "home net")
        self.results["get_saved_wifi_password"] = "Saved Wi-Fi networks: Cafe, Home. Tell me which one."
        self.say("what is the wifi password", answers=["Cafe"])
        self.assertEqual([c[1] for c in self.calls], [("",), ("Cafe",)])
        self.assertEqual(self.questions, ["Saved Wi-Fi networks: Cafe, Home. Tell me which one."])

    def test_the_wifi_listing_is_not_followed_by_a_guess_when_the_user_says_nothing(self):
        self.say("show saved wifi networks")
        self.assertEqual([c[1] for c in self.calls], [("",)])

    def test_youtube_downloads_keep_the_links_capital_letters(self):
        self.routes("download this youtube video https://youtu.be/AbC123xYz", "download_youtube_video",
                    "https://youtu.be/AbC123xYz", False)
        self.routes("download this song https://youtu.be/AbC123xYz", "download_youtube_video",
                    "https://youtu.be/AbC123xYz", True)
        self.spoken.assert_called()

    def test_youtube_downloads_use_the_copied_link_when_none_is_given(self):
        with mock.patch.object(L, "read_clipboard", return_value="look: https://www.youtube.com/watch?v=XyZ now"):
            self.routes("download this video", "download_youtube_video", "https://www.youtube.com/watch?v=XyZ", False)
        self.assertEqual(self.questions, [])

    def test_youtube_downloads_ask_when_there_is_no_link_anywhere(self):
        self.routes("download this video", "download_youtube_video", "https://youtu.be/q", False, answers=["https://youtu.be/q"])
        self.no_tool("download this video")                              # silence: nothing is downloaded

    def test_free_games(self):
        self.routes("free game warframe", "lookup_free_game", "warframe")
        self.routes("tell me about the free game valorant", "lookup_free_game", "valorant")
        self.routes("suggest a free game", "lookup_free_game", "")
        self.routes("free to play games", "lookup_free_game", "")

    def test_minecraft_servers(self):
        self.routes("minecraft server play dot hypixel dot net", "lookup_minecraft_server", "play.hypixel.net")
        self.routes("check minecraft server mc.example.com:25565", "lookup_minecraft_server", "mc.example.com:25565")
        self.routes("minecraft server status", "lookup_minecraft_server", "play.example.com", answers=["play dot example dot com"])


class EmailTests(BrainCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(L.config, EMAIL_ADDRESS="me@gmail.com", EMAIL_PASSWORD="app-pass")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_spoken_address_is_understood_and_nothing_is_sent_until_confirmed(self):
        self.routes("send an email", "send_email", "john.smith@gmail.com", "Hello", "See you tomorrow", confirmed=True,
                    answers=["john dot smith at gmail dot com", "Hello", "See you tomorrow", "yes"])
        self.assertEqual(len(self.questions), 4)
        self.assertIn("john.smith@gmail.com", self.questions[3])
        self.assertIn("See you tomorrow", self.questions[3])

    def test_a_typed_address_passes_through(self):
        self.routes("write an email", "send_email", "a@example.com", "Hi", "Body", confirmed=True,
                    answers=["a@example.com", "Hi", "Body", "yes please"])

    def test_declining_at_the_end_sends_nothing(self):
        reply = self.no_tool("send an email", ["a@example.com", "Hi", "Body", "no"])
        self.assertEqual(reply, "Okay, I haven't sent anything.")

    def test_giving_up_early_sends_nothing(self):
        self.assertEqual(self.no_tool("send an email", []), "Okay, no email then.")
        self.assertEqual(self.no_tool("send an email", ["a@example.com", "Hi", ""]), "Okay, no email then.")

    def test_unconfigured_email_does_not_waste_the_users_time_with_questions(self):
        with mock.patch.multiple(L.config, EMAIL_ADDRESS="", EMAIL_PASSWORD=""):
            self.assertIn("isn't set up", self.no_tool("send an email"))
        self.assertEqual(self.questions, [])


class FailureTests(BrainCase):
    def test_a_tools_own_explanation_is_what_gets_spoken(self):
        self.raises["get_weather"] = ToolError("never used")
        self.raises["weather_report"] = ToolError("I couldn't find a place called Zzz.")
        self.assertEqual(self.say("weather in zzz"), "I couldn't find a place called Zzz.")

    def test_an_unexpected_crash_is_shown_in_the_window_and_apologised_for(self):
        self.raises["get_joke"] = RuntimeError("kaboom")
        errors = io.StringIO()
        with redirect_stderr(errors):
            reply = self.say("tell me a joke")
        self.assertIn("didn't work", reply)
        self.assertIn("kaboom", errors.getvalue())


class RealSessionReviewTests(BrainCase):
    """Things that went wrong in a real morning session (2026-10-19) and are fixed."""

    def test_a_to_do_list_is_built_task_by_task_and_timed_tasks_get_a_reminder(self):
        today = L._day_from_word("today")
        reply = self.say("Make a todo list for today, add timing to it and keep reminding me",
                         answers=["buy bread", "call Ali at 5 pm", "done"])
        self.assertEqual(self.calls, [("add_task", ("buy bread", today), {}), ("add_task", ("call ali", today), {}),
                                      ("set_reminder", (), {"message": "call ali", "at_time": "17:00"})])
        self.assertIn("added 2 tasks", reply)
        self.assertIn("call ali at 17:00", reply)
        self.assertIn("first task", self.questions[0])

    def test_a_to_do_list_with_no_tasks_adds_nothing(self):
        self.assertEqual(self.no_tool("make a todo list", answers=["done"]), "Okay, no tasks added.")
        self.assertEqual(self.no_tool("create a new to do list for tomorrow", answers=[""]), "Okay, no tasks added.")

    def fill(self, folder, notes=0, tasks=()):
        (Path(folder) / "Notes").mkdir()
        for n in range(notes):
            (Path(folder) / "Notes" / f"n{n}.txt").write_text(f"note {n} about python", encoding="utf-8")
        (Path(folder) / "Tasks").mkdir()
        for day, items in tasks:
            (Path(folder) / "Tasks" / f"{day}-Task.txt").write_text("".join(i + "\n" for i in items), encoding="utf-8")

    def test_notes_are_deleted_only_after_a_yes(self):
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            self.fill(folder, notes=3)
            self.assertIn("kept them", self.no_tool("clear all notes", answers=["no"]))
            self.assertEqual(self.questions, ["This will permanently delete 3 notes. Say yes or no."])
            self.assertEqual(self.say("clear all notes", answers=["yes"]), "Deleted 3 notes, sir.")
            self.assertEqual(self.calls, [("delete_notes", ("all",), {"confirmed": True})])

    def test_clearing_notes_and_tasks_together_clears_every_day(self):
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            self.fill(folder, notes=2, tasks=[("2026-10-19", ["a", "b"]), ("2026-10-20", ["c"])])
            reply = self.say("clear all notes and tasks", answers=["yes"])
            self.assertEqual(self.questions, ["This will permanently delete 2 notes and 3 to-do items. Say yes or no."])
            self.assertEqual(reply, "Deleted 2 notes and 3 to-do items, sir.")
            self.assertEqual(self.calls, [("delete_notes", ("all",), {"confirmed": True}), ("clear_tasks", ("", True, True), {})])

    def test_clearing_one_days_list_leaves_the_other_days(self):
        from JarvisAdvancedBot.tools import _common
        today = L._day_from_word("today")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            self.fill(folder, tasks=[(today, ["a", "b"]), ("2026-12-31", ["c"])])
            self.say("clear my to do list", answers=["yes"])
            self.assertEqual(self.calls, [("clear_tasks", ("", False, True), {})])
            self.assertIn("2 to-do items", self.questions[0])

    def test_there_is_nothing_to_confirm_when_there_is_nothing_to_clear(self):
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            self.assertIn("no saved notes", self.no_tool("delete my notes"))
            self.assertIn("no to-do items", self.no_tool("clear all tasks"))
            self.assertIn("no saved notes and no to-do items", self.no_tool("clear all notes and tasks"))
        self.assertEqual(self.questions, [])

    def test_one_task_can_be_removed_by_number_or_by_its_words(self):
        self.routes("remove task 2", "remove_task", 2)
        today = L._day_from_word("today")
        self.routes("remove buy bread from my to do list", "remove_task", 0, "", "buy bread")
        self.routes("delete the task buy bread", "remove_task", 0, "", "buy bread")
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            (Path(folder) / "Tasks").mkdir()
            (Path(folder) / "Tasks" / f"{today}-Task.txt").write_text("call ali" + chr(10), encoding="utf-8")
            self.routes("mark call ali as done", "remove_task", 0, "", "call ali")        # a bare phrase acts only on a real item
            self.routes("cross off call ali", "remove_task", 0, "", "call ali")
        self.routes("remove task 3 for tomorrow", "remove_task", 3, L._day_from_word("tomorrow"))
        self.routes("remove 2 from my to do list", "remove_task", 2)
        self.assertTrue(today)

    def test_one_note_can_be_deleted_after_a_yes(self):
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            self.fill(folder, notes=2)
            self.assertIn("kept it", self.no_tool("delete the last note", answers=["no"]))
            self.routes("delete the last note", "delete_notes", "latest", "n1", True, answers=["yes"])
            self.assertIn("Several notes match", self.say("delete note about python"))          # both notes are about python
            self.routes("delete note called n1", "delete_notes", "latest", "n1", True, answers=["yes"])

    def test_a_folder_can_be_opened_by_its_full_path(self):
        path = r"C:\Users\Rohaan & Co\Downloads\My Folder\Tasks"
        self.routes(f"Open this folder, {path}", "open_folder", path)
        self.routes(f"open {path}", "open_folder", path)

    def test_play_music_presses_play_and_says_how_to_name_a_song(self):
        reply = self.routes("can you play music", "media_control", "play_pause", 1)
        self.assertIn("play despacito", reply)

    def test_another_repeats_the_last_joke_fact_or_advice(self):
        L._last_fun[0] = ""
        self.routes("tell me a joke", "get_joke")
        self.routes("oh that's not funny another", "get_joke")
        self.routes("another one", "get_joke")
        self.routes("random fact", "get_random_fact", "any")
        self.routes("one more", "get_random_fact", "any")

    def test_another_with_nothing_to_repeat_is_not_guessed(self):
        L._last_fun[0] = ""
        self.assertIsNone(self.no_tool("another"))

    def test_wifi_passwords_are_understood_even_with_a_typo(self):
        self.routes("give me saved wifi passowrds", "get_saved_wifi_password", "", answers=[""])

    def test_the_wifi_networks_in_range_are_listed(self):
        shown = SimpleNamespace(stdout="SSID 1 : Basement\nBSSID 1 : aa\nSSID 2 : Home\nSSID 3 : Basement\n")
        with mock.patch("subprocess.run", return_value=shown):
            reply = self.no_tool("show all available wifi networks")
        self.assertEqual(reply, "I can see 2 Wi-Fi networks: Basement, Home.")
        with mock.patch("subprocess.run", return_value=SimpleNamespace(stdout="")):
            self.assertIn("can't see any", self.no_tool("show all available wifi networks"))

    def test_the_tasks_folder_and_its_typos_open_the_folder_not_an_app(self):
        from JarvisAdvancedBot.tools import _common
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(_common, "DB", Path(folder)):
            for phrase in ("open task folder", "open task holder", "open tasks folder", "can you open the tasks folder"):
                self.say(phrase)
                self.assertEqual([c[0] for c in self.calls], ["open_folder"], phrase)
                self.assertTrue(self.calls[0][1][0].endswith("Tasks"))

    def test_asking_for_a_saved_wifi_password_never_generates_one(self):
        for phrase in ("give me saved wi-fi password", "show me the current connected wi-fi password"):
            self.say(phrase, answers=[""])
            self.assertNotIn("generate_password", [c[0] for c in self.calls], phrase)
        self.routes("give me a strong password", "generate_password", 16)

    def test_the_password_for_a_named_network_is_looked_up(self):
        self.routes("can you tell me the password for khalil", "get_saved_wifi_password", "khalil")
        self.assertIn("python gate.py --set-password", self.say("what's the password of jarvis"))

    def test_a_to_do_list_can_be_asked_for_in_short_forms(self):
        for phrase in ("make a to do this for today", "ok i said can you make to do just for today", "create a todo"):
            self.assertEqual(self.no_tool(phrase, answers=["done"]), "Okay, no tasks added.", phrase)
        self.routes("create a new task finish homework", "add_task", "finish homework")        # still one task

    def test_a_sentence_is_never_typed_into_the_start_menu(self):
        for phrase in ("open the task so that i can chat to do list", "open the thing that i wanted to see yesterday"):
            self.assertIsNone(self.no_tool(phrase), phrase)
        self.routes("open chrome", "open_app", "chrome")

    def test_start_taking_notes_asks_what_to_write(self):
        self.routes("start taking notes", "take_note", "buy milk", answers=["buy milk"])
        self.assertEqual(self.questions, ["Okay sir. What should the note say?"])
        self.assertEqual(self.no_tool("start taking notes", answers=[""]), "Okay, no note then.")

    def test_every_way_of_asking_for_the_networks_in_range_lists_them(self):
        shown = SimpleNamespace(stdout="SSID 1 : BASEMENT\n")
        for phrase in ("can you list all wi-fi network", "scan for wifi networks", "show wifi networks nearby"):
            with mock.patch("subprocess.run", return_value=shown):
                self.assertEqual(self.no_tool(phrase), "I can see 1 Wi-Fi network: BASEMENT.", phrase)

    def test_all_of_them_shows_every_saved_wifi_password_on_screen(self):
        with mock.patch.object(L, "_saved_wifi_names", return_value=["Home", "Office"]):
            self.say("saved wifi passwords", answers=["all of them"])
        self.assertEqual([c[1] for c in self.calls if c[0] == "get_saved_wifi_password"], [("",), ("Home",), ("Office",)])

    def test_a_network_name_with_a_typo_finds_the_saved_network(self):
        with mock.patch.object(L, "_saved_wifi_names", return_value=["Student_Wifi", "khalil", "BASEMENT"]):
            self.routes("can you tell me password for khali", "get_saved_wifi_password", "khalil")
            self.routes("what's the wifi password of basment", "get_saved_wifi_password", "BASEMENT")
            self.say("give me a strong password for gmail")
        self.assertIn("generate_password", [c[0] for c in self.calls])

    def test_an_answer_that_is_not_a_link_cancels_the_download(self):
        reply = self.no_tool("can you download a youtube video", answers=["can you give me a business name"])
        self.assertIn("cancelled the download", reply)
        self.assertNotIn("Downloading", " ".join(str(c) for c in self.spoken.call_args_list))


class SlightlyDifferentWordingTests(BrainCase):
    """The sentences from a real testing session that did nothing because the wording was a little different."""

    def setUp(self):
        super().setUp()
        from JarvisAdvancedBot.tools import _common
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(_common, "DB", Path(folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = Path(folder.name)
        (self.db / "Notes").mkdir()
        (self.db / "Tasks").mkdir()
        for n, age in enumerate((300, 200, 100)):                    # n0 is the oldest note, n2 the newest
            note = self.db / "Notes" / f"n{n}.txt"
            note.write_text(f"note {n}", encoding="utf-8")
            os.utime(note, (time.time() - age, time.time() - age))
        today = L._day_from_word("today")
        (self.db / "Tasks" / f"{today}-Task.txt").write_text("finish program\ncall hamza\ndentist visit\n", encoding="utf-8")
        self.today = today

    def test_a_numbered_task_is_removed_however_it_is_asked_for(self):
        for phrase in ("can you remove the third task i am done from the to do", "remove task 3", "delete task number three",
                       "please get rid of the third item", "can you complete task three", "tick off the 3rd task"):
            self.routes(phrase, "remove_task", 3)

    def test_the_last_task_is_removed_even_when_speech_recognition_hears_another_word(self):
        for phrase in ("remove the last task from the task folder", "delete the last tas", "can you remove the last text from the list",
                       "can you remove the last test from the recent", "remove the latest item"):
            self.routes(phrase, "remove_task", 3)
        self.routes("remove the first task", "remove_task", 1)

    def test_a_task_is_found_by_its_words_without_saying_task(self):
        self.routes("cross off dentist", "remove_task", 0, "", "dentist")
        self.routes("take hamza off my to do list", "remove_task", 0, "", "hamza")
        self.assertIsNone(self.no_tool("cross off the moon"))                   # nothing like that on the list: not a command

    def test_a_note_is_deleted_by_its_number_after_a_yes_even_when_heard_as_not_or_knot(self):
        for phrase in ("remove not number 2", "can you remove the knot number 2", "delete note two", "erase the second note"):
            self.routes(phrase, "delete_notes", "latest", "n1", True, answers=["yes"])               # the second newest
        self.assertIn("no note number 7", self.no_tool("delete note number 7"))

    def test_clear_all_with_nothing_else_asks_what_to_clear(self):
        for phrase in ("can you clear all", "can you remove all", "can you delete all 9"):
            self.say(phrase, answers=["notes", "yes"])
            self.assertEqual(self.questions[0], "Do you want me to clear your notes, your tasks, or both?", phrase)
            self.assertEqual(self.calls, [("delete_notes", ("all",), {"confirmed": True})], phrase)
        self.say("clear all", answers=["both", "yes"])
        self.assertEqual([c[0] for c in self.calls], ["delete_notes", "clear_tasks"])
        self.assertEqual(self.no_tool("clear all", answers=["never mind"]), "Okay, I haven't cleared anything.")

    def test_adding_another_item_asks_for_it(self):
        self.routes("can you add another task", "add_task", "call sana", answers=["call sana"])
        self.assertEqual(self.questions, ["What's the task?"])
        self.routes("can you add another note", "take_note", "buy tea", answers=["buy tea"])

    def test_a_yes_can_be_said_in_the_words_of_the_question(self):
        for answer in ("you can you can permanently delete all 9", "delete them", "yes proceed", "clear everything", "go ahead"):
            self.assertIn("Deleted 3 notes", self.say("clear all notes", answers=[answer]), answer)
        for answer in ("no", "not right now", "wait", "don't", "never mind", "later"):
            self.assertIn("kept them", self.no_tool("clear all notes", answers=[answer]), answer)

    def test_typos_in_command_words_are_put_right(self):
        shown = SimpleNamespace(stdout="SSID 1 : BASEMENT" + chr(10))
        with mock.patch("subprocess.run", return_value=shown):
            self.assertEqual(self.no_tool("show all available wifi networds"), "I can see 1 Wi-Fi network: BASEMENT.")
        self.say("open task holder")
        self.assertEqual(self.calls[0][0], "open_folder")

    def test_numbers_in_a_list_refer_to_the_list_that_was_just_read_out(self):
        self.say("what's on my to do list")
        self.routes("remove number 2", "remove_task", 2)
        self.say("show my notes")
        self.routes("remove number 1", "delete_notes", "latest", "n2", True, answers=["yes"])


class SecondRoundOfRecordedIssuesTests(SlightlyDifferentWordingTests):
    """What went wrong in the next real testing session."""

    def test_i_am_done_ends_the_list_instead_of_becoming_a_task(self):
        for done in ("i am done", "Done", "that's all", "i'm finished", "nothing more", "i am", "all done now", "that is it for now"):
            reply = self.say("create a to do list", answers=["bring eggs tonight", done])
            self.assertEqual([c[1][0] for c in self.calls if c[0] == "add_task"], ["bring eggs tonight"], done)
            self.assertIn("I added 1 task", reply, done)

    def test_tasks_are_tidied_and_a_time_in_them_sets_a_reminder(self):
        self.say("can you create a to do list for my all task", answers=["at call ali at 5:00 p.m.", "i will bring eggs tonight", "done"])
        self.assertEqual([c[1][0] for c in self.calls if c[0] == "add_task"], ["call ali", "bring eggs tonight"])
        self.assertIn(("set_reminder", (), {"message": "call ali", "at_time": "17:00"}), self.calls)

    def test_a_day_named_anywhere_in_the_sentence_is_used(self):
        self.say("create a new to do list for my test for tomorrow", answers=["write the program", "done"])
        self.assertEqual(self.calls[0], ("add_task", ("write the program", L._day_from_word("tomorrow")), {}))

    def test_the_last_two_tasks_are_removed_from_the_far_end(self):
        self.say("remove the last two task")
        self.assertEqual(self.calls, [("remove_task", (3,), {}), ("remove_task", (2,), {})])
        self.say("remove the first two tasks")
        self.assertEqual(self.calls, [("remove_task", (1,), {}), ("remove_task", (1,), {})])

    def test_the_last_two_notes_are_deleted_after_one_yes(self):
        self.say("delete the last two notes", answers=["yes"])
        self.assertEqual(self.questions, ["This will permanently delete these 2 notes. Say yes or no."])
        self.assertEqual(self.calls, [("delete_notes", ("latest", "n2", True), {}), ("delete_notes", ("latest", "n1", True), {})])

    def test_added_to_do_that_i_will_do_something_adds_that_task(self):
        for phrase in ("ok added to do that i will complete my homework by tonight", "at complete my homework by tonight to my to do list"):
            self.routes(phrase, "add_task", "complete my homework by tonight")

    def test_a_task_sentence_that_stopped_halfway_asks_what_the_task_is(self):
        self.routes("can you add a task to my tutori", "add_task", "write notes", answers=["write notes"])
        self.assertEqual(self.questions, ["What's the task?"])


class RewordedCommandTests(SlightlyDifferentWordingTests):
    """More ways of saying the same things (the setUp gives it three notes and three tasks)."""

    def test_deleting_the_last_note_is_not_reading_it_out(self):
        self.routes("get rid of my last note", "delete_notes", "latest", "n2", True, answers=["yes"])
        self.routes("throw away the newest note", "delete_notes", "latest", "n2", True, answers=["yes"])

    def test_the_tasks_folder_is_opened_not_read_out(self):
        for phrase in ("show me the tasks folder", "open the task folder", "go to my to do folder"):
            self.say(phrase)
            self.assertEqual(self.calls[0][0], "open_folder", phrase)

    def test_jot_down_saves_a_note(self):
        self.routes("jot down call mum", "take_note", "call mum")

    def test_alarms_and_timers_said_in_words(self):
        self.routes("set an alarm for seven in the morning", "set_reminder", message="Wake up, sir", at_time="07:00")
        self.routes("set an alarm for 7 in the evening", "set_reminder", message="Wake up, sir", at_time="19:00")
        self.routes("set a timer of five minutes", "set_reminder", message="Your timer is done", minutes_from_now=5)
        self.routes("remind me after ten minutes to check the oven", "set_reminder", message="check the oven", minutes_from_now=10)

    def test_sums_in_words(self):
        self.assertEqual(self.no_tool("what is fifteen percent of two hundred"), "That's 30.")
        self.assertEqual(self.no_tool("what is twelve times twelve"), "That's 144.")
        self.assertEqual(self.no_tool("what is two hundred and fifty plus forty five"), "That's 295.")

    def test_money_in_words(self):
        self.routes("how much is a dollar in rupees", "convert_currency", 1, "USD", "PKR")
        self.routes("how much is ten dollars in rupees", "convert_currency", 10.0, "USD", "PKR")

    def test_asking_whether_the_laptop_is_plugged_in_is_asking_about_the_battery(self):
        self.assertTrue(self.say("is the laptop plugged in"))


class ExplanationTests(BrainCase):
    def test_a_question_about_the_difference_between_things_is_left_for_the_chat_brain(self):
        for phrase in ("what is the difference between a comet and an asteroid", "what's the difference between weather and climate",
                       "what are the differences between mars and venus"):
            self.assertIsNone(self.no_tool(phrase), phrase)

    def test_asking_what_a_thing_is_or_how_it_works_does_not_run_the_command_it_is_named_after(self):
        for phrase in ("what is a screenshot", "how does a battery work", "explain how a battery works", "what is a cpu",
                       "how does ram work", "what does the ram do in a computer", "why do people get bored",
                       "how do i take a screenshot on a mac", "what is an asteroid", "how do airplanes stay in the air",
                       "why is my laptop battery draining so fast", "how can i check my battery on a phone"):
            self.assertIsNone(self.no_tool(phrase), phrase)

    def test_the_same_words_as_a_request_still_run_the_command(self):
        self.routes("take a screenshot", "take_screenshot")
        self.routes("what's on my to do list for tomorrow", "list_tasks", L._day_from_word("tomorrow"))
        self.routes("how do you say good morning in urdu", "translate_text", "good morning", "urdu")
        self.routes("weather in london", "weather_report", "london")
        self.assertIn("I'm speaking now", self.no_tool("why are you not speaking"))      # the voice check starts with "why are"

    def test_other_questions_that_mention_a_difference_still_work(self):
        self.assertIn("It's", self.no_tool("what's the time difference"))                       # "what's the time" is still the time
        self.routes("weather in london", "weather_report", "london")


class TemperatureTests(BrainCase):
    def test_asking_for_the_temperature_is_asking_for_the_weather(self):
        for phrase, place in (("temperature", "Peshawar"), ("what's the temperature", "Peshawar"),
                              ("what is the temperature outside", "Peshawar"), ("what's the temperature like", "Peshawar"),
                              ("how's the temperature", "Peshawar"), ("tell me the temperature", "Peshawar"),
                              ("current temperature", "Peshawar"), ("temperature right now", "Peshawar"),
                              ("what is the temperature here", "Peshawar"), ("what's the temperature in london", "london"),
                              ("temperature in lahore today", "lahore")):
            self.routes(phrase, "weather_report", place)

    def test_the_word_in_a_general_question_does_not_fetch_the_weather(self):
        for phrase in ("what is the difference between heat and temperature", "at what temperature does water boil",
                       "what is body temperature", "what temperature should the oven be", "what is the temperature of the human body",
                       "what is the difference between weather and climate"):
            self.say(phrase)
            self.assertNotIn("weather_report", [name for name, _, _ in self.calls], phrase)

    def test_the_temperature_of_a_planet_is_still_about_the_planet(self):
        self.routes("what is the temperature of mars", "nasa_solar_body_facts", "mars", "temperature")


class BrowserHistoryTests(BrainCase):
    def test_asking_for_the_history_of_something_is_a_question_not_a_browser_shortcut(self):
        for phrase in ("what is the history of mexico", "tell me about the history of the roman empire",
                       "history of pakistan", "why is the history of art important"):
            self.say(phrase)
            self.assertNotIn("browser_action", [name for name, _, _ in self.calls], phrase)

    def test_the_browsers_own_history_page_still_opens(self):
        for phrase in ("history", "open history", "show my browsing history", "browser history", "open the chrome history",
                       "go to my history page"):
            self.routes(phrase, "browser_action", "history")


class LanguageModelTests(BrainCase):
    """The language model trained on this PC is the second chance for a sentence no pattern understands."""

    def model_says(self, family, confidence=0.95):
        """Make the model sure that whatever is said means this kind of request."""
        wanted = L.NLU.FAMILIES[family]
        patcher = mock.patch.object(L.NLU, "interpret", return_value=L.NLU.Guess(family, wanted.command, confidence, wanted.ask))
        self.interpret = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_loosely_worded_command_runs_as_the_plain_command_it_means(self):
        self.model_says("time")
        self.assertRegex(self.no_tool("got the time"), r"^It's \d{1,2}:\d{2} [AP]M\.$")
        self.interpret.assert_called_once_with("got the time")                  # it is given the sentence as the patterns saw it

    def test_the_model_sees_the_sentence_tidied_like_the_patterns_see_it(self):
        self.model_says("time")
        self.no_tool("Jarvis, could you please give me the clock reading?")
        self.interpret.assert_called_once_with("give me the clock reading")

    def test_what_a_pattern_understands_never_reaches_the_model(self):
        self.model_says("time")
        self.routes("tell me a joke", "get_joke")
        self.interpret.assert_not_called()

    def test_when_the_model_is_not_sure_the_sentence_is_left_for_the_chat_brain(self):
        patcher = mock.patch.object(L.NLU, "interpret", return_value=None)
        interpret = patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIsNone(L.LocalReply("do you like cricket"))
        interpret.assert_called_once_with("do you like cricket")

    def test_without_a_trained_model_nothing_changes(self):
        self.assertIsNone(L.LocalReply("got the time"))
        self.assertIsNone(L.LocalReply("why is the sky blue"))

    def test_a_cut_off_sentence_never_gets_as_far_as_the_model(self):
        self.model_says("time")
        self.assertIsNone(L.LocalReply("can you"))
        self.interpret.assert_not_called()

    def test_the_weather_keeps_the_place_that_was_said(self):
        self.model_says("weather")
        self.routes("do i need an umbrella in lahore today", "weather_report", "lahore")

    def test_the_weather_without_a_place_is_for_the_home_city(self):
        self.model_says("weather")
        self.routes("do i need an umbrella", "weather_report", "Peshawar")

    def test_the_to_do_list_keeps_the_day_that_was_said(self):
        self.model_says("list_tasks")
        self.routes("do i have anything for tomorrow", "list_tasks", L._day_from_word("tomorrow"))
        self.routes("is there anything left on friday", "list_tasks", L._day_from_word("friday"))
        self.routes("is there anything left", "list_tasks")

    def test_the_command_is_printed_so_you_can_see_what_the_model_understood(self):
        self.model_says("joke", confidence=0.91)
        out = io.StringIO()
        with redirect_stdout(out):
            L.LocalReply("make me chuckle")
        self.assertIn("'make me chuckle' as 'tell me a joke', 91% sure", out.getvalue())

    def test_a_guess_that_needs_a_question_asks_it_and_stops_on_no(self):
        self.model_says("lock_screen")
        for answer in ("no", "", "maybe"):
            self.assertEqual(self.no_tool("secure the workstation", answers=[answer]), "Okay sir, I won't.")
        self.assertEqual(self.questions, ["Did you want me to lock the screen? Say yes or no."])

    def test_a_guess_that_needs_a_question_goes_ahead_on_yes(self):
        self.model_says("lock_screen")
        self.routes("secure the workstation", "windows_action", "lock_screen", answers=["yes please"])

    def test_forgetting_what_was_remembered_asks_before_it_does_anything(self):
        self.model_says("forget_facts")
        with mock.patch.object(L.ChatBrain, "forget_facts", return_value=3) as forget:
            self.assertEqual(self.no_tool("wipe my memory banks", answers=["no"]), "Okay sir, I won't.")
            forget.assert_not_called()
            self.assertIn("forgotten 3 things", self.no_tool("wipe my memory banks", answers=["yes"]))

    def test_shutting_down_from_a_guess_still_asks_are_you_sure(self):
        self.model_says("shutdown")
        reply = self.no_tool("time to call it a night for the machine", answers=["no"])
        self.assertEqual(self.questions, ["Are you sure you want me to shut down the computer? Say yes or no."])
        self.assertIn("won't shut down", reply)

    def test_a_rewrite_that_no_pattern_understands_is_not_rewritten_again(self):
        patcher = mock.patch.object(L.NLU, "interpret", return_value=L.NLU.Guess("time", "gibberish nobody handles", 0.99, ""))
        interpret = patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIsNone(L.LocalReply("something odd"))
        interpret.assert_called_once()

    def test_split_commands_only_joins_what_the_patterns_understand(self):
        self.model_says("time")
        self.assertEqual(L.split_commands("got the time then what is the date"), ["got the time then what is the date"])


class HelperTests(unittest.TestCase):
    def test_spoken_addresses(self):
        self.assertEqual(L._spoken_address("John Smith at Gmail dot com"), "johnsmith@gmail.com")
        self.assertEqual(L._spoken_address("a underscore b at example dot org"), "a_b@example.org")
        self.assertEqual(L._spoken_address("typed@example.com"), "typed@example.com")

    def test_confirmations(self):
        for yes in ("yes", "Yeah go ahead", "ok", "sure thing"):
            self.assertTrue(L._confirmed(lambda q, a=yes: a, "?"), yes)
        for no in ("", "no", "yes please do not", "cancel", "maybe later"):
            self.assertFalse(L._confirmed(lambda q, a=no: a, "?"), no)

    def test_as_typed_restores_capitals_from_the_original_command(self):
        L._context.query = "Create a folder named Projects"
        self.assertEqual(L._as_typed("projects"), "Projects")
        self.assertEqual(L._as_typed("elsewhere"), "elsewhere")
        self.assertEqual(L._as_typed(""), "")

    def test_clock_times_for_the_time_table(self):
        self.assertEqual(L._to_24h("6"), "06:00")
        self.assertEqual(L._to_24h("6", "evening"), "18:00")
        self.assertEqual(L._to_24h("12", "evening"), "12:00")
        self.assertEqual(L._to_24h("6:30 pm"), "18:30")
        self.assertEqual(L._to_24h("12 am"), "00:00")
        self.assertIsNone(L._to_24h("25"))
        self.assertIsNone(L._to_24h("soon"))


if __name__ == "__main__":
    unittest.main()
