"""Tests that what you say reaches the right tool with the right arguments:  python -m unittest tests.test_localbrain -v

Every tool is replaced by a recorder, so these tests check the ROUTING (including the order of the
patterns, which decides what wins when two could match) without doing anything real.
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
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
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
        self.assertIn("space station", self.no_tool("what can you do"))

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
        self.assertIn("written the Urdu translation on the screen", self.say("translate good morning to urdu"))

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


class ForgivingPhrasingTests(BrainCase):
    """Phrasings people (and the speech recogniser) actually produce for things Jarvis already does."""

    def test_notes_in_every_shape(self):
        for phrase in ("show note", "show notes", "open note", "open the notes", "read note", "notes", "note", "my notes",
                       "jarvis notes", "what notes do i have", "do i have any notes", "see my notes", "check my notes",
                       "open my notes app"):
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
        self.routes("convert 5 miles to kilometres", "ask_wolfram_alpha", "5 miles to kilometres")


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
