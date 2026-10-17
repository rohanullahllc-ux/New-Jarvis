"""Tests for the tools package core: shared helpers, registry, info, web, windows and productivity tools.

    python -m unittest tests.test_tools_core -v
"""
import datetime
import json
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

from tests.tools_support import FakeResponse, ToolCase

from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import tools as T  # noqa: E402
from JarvisAdvancedBot.tools import _common, info, productivity, space, web, windows, world  # noqa: E402


def make_pdf(path, lines):
    """Write a small valid PDF with one line of text per page."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(len(lines)))}] /Count {len(lines)} >>".encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, line in enumerate(lines):
        stream = f"BT /F1 18 Tf 72 720 Td ({line}) Tj ET".encode()
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    table = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))


class HelperTests(ToolCase):
    def test_http_failures_are_told_apart_so_each_tool_can_explain_itself(self):
        for status, kind in ((404, _common.NotFoundError), (429, _common.RateLimitedError),
                             (403, _common.RefusedError), (500, ToolError)):
            self.http.routes = [("example.org", FakeResponse({}, status))]
            with self.assertRaises(ToolError) as caught:
                _common.get_json("https://example.org/data")
            self.assertIs(type(caught.exception), kind, status)
            self.assertIn("example.org", str(caught.exception))

    def test_network_trouble_names_the_service_in_plain_words(self):
        for error, words in ((requests.Timeout(), "too long"), (requests.ConnectionError(), "couldn't reach")):
            self.http.routes = [("example.org", error)]
            self.fails(lambda: _common.get_json("https://www.example.org/data"), "example.org", words)
        self.http.routes = [("example.org", FakeResponse(None, text="<html>not json</html>"))]
        self.fails(lambda: _common.get_json("https://example.org/data"), "couldn't read")

    def test_cached_answers_spare_the_service(self):
        self.http.on("example.org", FakeResponse({"n": 1}))
        for _ in range(3):
            self.assertEqual(_common.get_json("https://example.org/a", cache_seconds=60, q="x"), {"n": 1})
        self.assertEqual(len(self.http.calls), 1)
        _common.get_json("https://example.org/a", q="x")                    # no cache requested: asks again
        self.assertEqual(len(self.http.calls), 2)

    def test_text_from_websites_is_made_fit_to_read_aloud(self):
        self.assertEqual(_common.plain("Hello &amp; welcome \u25c0 to   CubeCraft \u2726"), "Hello & welcome to CubeCraft")
        self.assertEqual(_common.plain(None), "")

    def test_amounts_are_spoken_with_currency_names(self):
        self.assertEqual(_common.money(2770, "pkr"), "2,770 Pakistani rupees")
        self.assertEqual(_common.money(10, "USD"), "10.00 US dollars")
        self.assertEqual(_common.money(0.5, "XYZ"), "0.5 XYZ")

    def test_summaries_are_cut_at_sentence_boundaries(self):
        self.assertEqual(_common.first_sentences("One. Two! Three? Four.", 2), "One. Two!")

    def test_filenames_lose_characters_windows_forbids(self):
        self.assertEqual(_common.safe_filename('a<b>:"c"/d?'), "abcd")

    def test_folder_is_created_inside_the_database(self):
        made = _common.folder("Downloads/Instagram")
        self.assertTrue(made.is_dir())
        self.assertEqual(made.parent.parent, self.db)


class RegistryTests(unittest.TestCase):
    def test_every_tool_has_a_unique_name_a_description_and_documented_parameters(self):
        names = [tool.name for tool in T.TOOLS]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 55)
        for tool in T.TOOLS:
            spec = tool.to_dict()
            self.assertTrue(spec["description"], tool.name)
            for parameter, schema in spec["input_schema"].get("properties", {}).items():
                self.assertTrue(schema.get("description"), f"{tool.name}.{parameter} has no description")

    def test_tools_can_be_reached_by_name_from_the_package(self):
        self.assertIs(T.get_weather, info.get_weather)
        self.assertIs(T.send_email, world.send_email)
        self.assertTrue(callable(T.weather_report))

    def test_no_tool_is_defined_but_left_out_of_its_modules_list(self):
        tool_type = type(T.get_weather)
        for module in (info, web, windows, productivity, space, world):
            defined = {name for name, value in vars(module).items() if isinstance(value, tool_type)}
            listed = {tool.name for tool in module.TOOLS}
            self.assertEqual(defined, listed, module.__name__)


class InfoTests(ToolCase):
    def test_weather_is_a_sentence_ready_to_speak(self):
        self.http.on("geocoding-api.open-meteo.com", FakeResponse(
            {"results": [{"name": "Peshawar", "country": "Pakistan", "latitude": 34.0, "longitude": 71.5}]}))
        self.http.on("api.open-meteo.com/v1/forecast", FakeResponse(
            {"current": {"temperature_2m": 27.3, "apparent_temperature": 28.9, "relative_humidity_2m": 45,
                         "wind_speed_10m": 2.7, "weather_code": 0},
             "daily": {"temperature_2m_max": [27.8], "temperature_2m_min": [15.7], "precipitation_probability_max": [10]}}))
        text = T.get_weather(city="Peshawar")
        for piece in ("Peshawar, Pakistan", "clear sky", "27.3 degrees Celsius", "humidity 45 percent", "10 percent chance of rain"):
            self.assertIn(piece, text)

    def test_unknown_city_is_reported(self):
        self.http.on("geocoding-api.open-meteo.com", FakeResponse({}))
        self.fails(lambda: T.get_weather(city="Nowhereville"), "Nowhereville")

    def test_currency_conversion_speaks_amounts_with_names(self):
        self.http.on("open.er-api.com/v6/latest/USD", FakeResponse({"result": "success", "rates": {"PKR": 277.0}}))
        self.assertEqual(T.convert_currency(amount=10, from_currency="usd", to_currency="pkr"),
                         "10.00 US dollars is 2,770 Pakistani rupees.")

    def test_currency_conversion_with_an_unknown_code_is_an_error(self):
        self.http.on("open.er-api.com", FakeResponse({"result": "success", "rates": {}}))
        self.fails(lambda: T.convert_currency(amount=1, from_currency="USD", to_currency="ZZZ"), "ZZZ")

    def test_crypto_price_includes_the_daily_move(self):
        self.http.on("coingecko.com/api/v3/search", FakeResponse({"coins": [{"id": "bitcoin", "name": "Bitcoin"}]}))
        self.http.on("simple/price", FakeResponse({"bitcoin": {"usd": 81624, "usd_24h_change": -0.8}}))
        self.assertEqual(T.get_crypto_price(coin="btc"), "Bitcoin is 81,624 US dollars, down 0.8 percent in the last 24 hours.")

    def test_wikipedia_summary_and_disambiguation(self):
        self.http.on("w/api.php", FakeResponse({"query": {"search": [{"title": "Mercury"}]}}))
        self.http.on("page/summary/Mercury", FakeResponse({"type": "disambiguation"}))
        self.assertIn("several different things", T.search_wikipedia(topic="mercury"))
        self.http.routes[1] = ("page/summary/Mercury", FakeResponse({"type": "standard", "extract": "Mercury is a planet."}))
        self.assertEqual(T.search_wikipedia(topic="mercury"), "Mercury is a planet.")

    def test_wikipedia_with_no_results_is_an_error(self):
        self.http.on("w/api.php", FakeResponse({"query": {"search": []}}))
        self.fails(lambda: T.search_wikipedia(topic="zzzzqq"), "Nothing found")

    def test_distance_on_the_map_is_measured_from_the_pcs_location(self):
        self.http.on("nominatim", FakeResponse([{"lat": "33.68", "lon": "73.05", "display_name": "Islamabad, Pakistan"}]))
        self.http.on("geojs.io", FakeResponse({"city": "Peshawar", "region": "KP", "country": "Pakistan",
                                               "latitude": "34.01", "longitude": "71.58"}))
        text = T.show_on_map(place="Islamabad")
        self.assertIn("Islamabad", text)
        self.assertRegex(text, r"about 1\d\d kilometres from Peshawar")
        self.assertIn("google.com/maps", self.opened[0])

    def test_system_details_covers_every_topic(self):
        for topic in ("cpu", "memory", "disks", "system"):
            self.assertTrue(T.get_system_details(topic=topic))


class WebTests(ToolCase):
    def test_bare_names_become_websites(self):
        T.open_website(url="github")
        T.open_website(url="github.com/anthropics")
        T.open_website(url="http://example.org/page")
        self.assertEqual(self.opened, ["https://www.github.com", "https://github.com/anthropics", "http://example.org/page"])

    def test_only_web_addresses_can_be_opened(self):
        self.fails(lambda: T.open_website(url="file:///C:/Windows/system.ini"), "web addresses")
        self.assertEqual(self.opened, [])

    def test_google_searches_are_url_encoded(self):
        T.search_google(query="rock & roll")
        self.assertEqual(self.opened, ["https://www.google.com/search?q=rock+%26+roll"])

    def test_youtube_shows_results_or_plays_the_best_match(self):
        T.youtube(query="lo fi beats", play=False)
        self.assertEqual(self.opened, ["https://www.youtube.com/results?search_query=lo+fi+beats"])
        played = []
        with mock.patch.dict(sys.modules, {"pywhatkit": SimpleNamespace(playonyt=played.append)}):
            self.assertEqual(T.youtube(query="lo fi beats"), "Playing lo fi beats on YouTube")
        self.assertEqual(played, ["lo fi beats"])

    def test_youtube_falls_back_to_results_when_playing_fails(self):
        def broken(query):
            raise RuntimeError("no internet")

        with mock.patch.dict(sys.modules, {"pywhatkit": SimpleNamespace(playonyt=broken)}):
            self.assertIn("results", T.youtube(query="song"))
        self.assertEqual(self.opened, ["https://www.youtube.com/results?search_query=song"])

    def test_media_keys_are_pressed_the_requested_number_of_times(self):
        from pynput.keyboard import Key
        with mock.patch("pynput.keyboard.Controller") as controller, mock.patch.object(web.time, "sleep"):
            T.media_control(action="volume_up", times=5)
            T.media_control(action="mute", times=0)             # at least one press
            T.media_control(action="volume_down", times=500)    # at most fifty
        keys = controller.return_value
        self.assertEqual(keys.press.call_args_list[:5], [mock.call(Key.media_volume_up)] * 5)
        self.assertEqual(keys.press.call_args_list[5], mock.call(Key.media_volume_mute))
        self.assertEqual(keys.press.call_count, 5 + 1 + 50)

    def test_keyboard_shortcuts_are_sent_as_chords(self):
        with mock.patch("keyboard.send") as send:
            T.youtube_control(action="fullscreen")
            T.youtube_control(action="faster")
        self.assertEqual(send.call_args_list, [mock.call("f"), mock.call("shift+.")])


class WindowsTests(ToolCase):
    def test_every_windows_and_browser_action_has_a_shortcut(self):
        for action in T.windows_action.to_dict()["input_schema"]["properties"]["action"]["enum"]:
            self.assertIn(action, windows.WINDOWS_SHORTCUTS)
        for action in T.browser_action.to_dict()["input_schema"]["properties"]["action"]["enum"]:
            self.assertIn(action, windows.BROWSER_SHORTCUTS)

    def test_windows_actions_send_their_shortcut(self):
        with mock.patch("keyboard.send") as send:
            T.windows_action(action="show_desktop")
            T.browser_action(action="new_tab")
        self.assertEqual(send.call_args_list, [mock.call("windows+d"), mock.call("ctrl+t")])

    def test_power_actions_never_run_without_confirmation(self):
        with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(windows.ctypes, "windll") as windll:
            for action in ("shutdown", "restart", "sleep", "lock"):
                self.fails(lambda: T.system_power_action(action=action), "confirm")
        run.assert_not_called()
        popen.assert_not_called()
        windll.user32.LockWorkStation.assert_not_called()

    def test_a_confirmed_shutdown_waits_so_it_can_be_cancelled(self):
        with mock.patch("subprocess.run") as run:
            text = T.system_power_action(action="shutdown", confirmed=True, delay_seconds=1)
            self.assertEqual(run.call_args[0][0], ["shutdown", "/s", "/t", "5"])          # at least five seconds
            self.assertIn("cancel", text)
            T.system_power_action(action="restart", confirmed=True, delay_seconds=999)
            self.assertEqual(run.call_args[0][0], ["shutdown", "/r", "/t", "120"])        # at most two minutes

    def test_cancelling_a_shutdown(self):
        with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertIn("Cancelled", T.system_power_action(action="cancel"))
            self.assertEqual(run.call_args[0][0], ["shutdown", "/a"])
        with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=1)):
            self.fails(lambda: T.system_power_action(action="cancel"), "no shutdown")

    def test_lock_and_sleep_when_confirmed(self):
        with mock.patch.object(windows.ctypes, "windll") as windll:
            T.system_power_action(action="lock", confirmed=True)
        windll.user32.LockWorkStation.assert_called_once()
        with mock.patch("subprocess.Popen") as popen:
            T.system_power_action(action="sleep", confirmed=True)
        self.assertIn("SetSuspendState", " ".join(popen.call_args[0][0]))

    def test_open_app_uses_windows_own_lookup_first(self):
        with mock.patch.object(windows.os, "startfile") as startfile:
            self.assertEqual(T.open_app(name="notepad"), "Opened notepad")
        startfile.assert_called_once_with("notepad")

    def test_open_app_falls_back_to_the_start_menu_for_store_apps(self):
        with mock.patch.object(windows.os, "startfile", side_effect=OSError), mock.patch("keyboard.send") as send, \
                mock.patch("keyboard.write") as write, mock.patch.object(windows.time, "sleep"):
            self.assertIn("Start menu", T.open_app(name="whatsapp"))
        write.assert_called_once_with("whatsapp", delay=0.02)
        self.assertEqual(send.call_args_list, [mock.call("windows"), mock.call("enter")])

    def test_open_app_rejects_odd_names_and_never_opens_documents(self):
        self.fails(lambda: T.open_app(name="calc & del *"), "App names")
        with mock.patch.object(windows.os, "startfile") as startfile, mock.patch("keyboard.send"), \
                mock.patch("keyboard.write"), mock.patch.object(windows.time, "sleep"):
            T.open_app(name="notes.txt")
        startfile.assert_not_called()                         # a name with an extension is typed, never opened as a file

    def test_close_app_only_touches_matching_programs(self):
        def process(name):
            return SimpleNamespace(info={"name": name}, terminate=mock.Mock())

        chrome1, chrome2, notepad = process("chrome.exe"), process("Chrome.exe"), process("notepad.exe")
        with mock.patch.object(windows.psutil, "process_iter", return_value=[chrome1, notepad, chrome2]):
            self.assertEqual(T.close_app(name="Chrome"), "Closed Chrome (2 processes)")
        chrome1.terminate.assert_called_once()
        chrome2.terminate.assert_called_once()
        notepad.terminate.assert_not_called()
        with mock.patch.object(windows.psutil, "process_iter", return_value=[notepad]):
            self.fails(lambda: T.close_app(name="spotify"), "No running program")

    def test_close_app_refuses_windows_and_jarvis_itself(self):
        for name in ("explorer", "svchost.exe", "python", "Code"):
            self.fails(lambda: T.close_app(name=name), "won't close")

    def test_open_folder_understands_paths_and_refuses_missing_ones(self):
        with mock.patch.object(windows.os, "startfile") as startfile:
            T.open_folder(location=str(self.db))
            startfile.assert_called_once_with(str(self.db))
            self.fails(lambda: T.open_folder(location=str(self.db / "nothing here")), "can't find")

    def test_screenshots_are_saved_under_a_safe_name(self):
        image = mock.Mock()
        with mock.patch("pyautogui.screenshot", return_value=image):
            self.assertEqual(T.take_screenshot(name="my:shot?"), "Saved the screenshot as myshot.png")
        image.save.assert_called_once_with(self.db / "ScreenShot" / "myshot.png")

    def test_utility_windows_open_through_the_shared_launcher(self):
        with mock.patch("subprocess.Popen") as popen:
            self.assertEqual(T.open_utility_app(name="currency_converter"), "Opened the currency converter.")
        command = popen.call_args[0][0]
        self.assertTrue(command[1].endswith("currency_converter.py"))
        self.assertEqual(popen.call_args[1]["env"]["PYTHONPATH"], str(windows.launcher.BASE_DIR))

    def test_utility_windows_report_when_they_are_missing(self):
        with mock.patch.dict(windows.launcher.UTILITIES, {"calculator": "no_such_window.py"}):
            self.fails(lambda: T.open_utility_app(name="calculator"), "isn't installed")


class NotesAndTasksTests(ToolCase):
    def test_notes_round_trip(self):
        self.assertEqual(T.read_notes(), "There are no saved notes.")
        self.assertEqual(T.take_note(text="milk, eggs", title="Shopping list!"), "Saved note 'Shopping list'")
        self.assertEqual(T.take_note(text="call the bank about the loan on Monday morning"), "Saved your note")
        listing = T.read_notes()
        self.assertIn("Shopping list", listing)
        self.assertIn("call the bank about the loan and so on", listing)       # untitled notes are named by what they say
        self.assertNotIn("note-2026", listing)
        self.assertIn("milk, eggs", T.read_notes(title="shopping"))
        self.assertIn("Monday morning", T.read_notes(title="bank"))             # found by what it says, not just its title
        self.fails(lambda: T.read_notes(title="holiday"), "No note matching")

    def test_tasks_are_numbered_and_removable(self):
        self.assertIn("empty", T.list_tasks())
        T.add_task(task="Buy bread")
        T.add_task(task="Call mum")
        self.assertIn("1. Buy bread; 2. Call mum", T.list_tasks())
        self.assertEqual(T.remove_task(number=1), "Removed: Buy bread")
        self.assertIn("1. Call mum", T.list_tasks())
        self.fails(lambda: T.remove_task(number=5), "no item 5")

    def test_tasks_belong_to_a_day(self):
        T.add_task(task="Dentist", date="2026-12-01")
        self.assertIn("Dentist", T.list_tasks(date="2026-12-01"))
        self.assertIn("empty", T.list_tasks(date="2026-12-02"))
        self.assertTrue((self.db / "Tasks" / "2026-12-01-Task.txt").exists())
        self.fails(lambda: T.add_task(task="x", date="tomorrow"), "YYYY-MM-DD")

    def test_reminders_are_timed_from_now_or_for_a_clock_time(self):
        with mock.patch.object(productivity.threading, "Timer") as timer:
            text = T.set_reminder(message="tea", minutes_from_now=10)
            delay = timer.call_args[0][0]
            self.assertAlmostEqual(delay, 600, delta=2)
            timer.return_value.start.assert_called_once()
            self.assertIn("tea", text)
            self.assertIn("only goes off while Jarvis is running", text)
            earlier = (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime("%H:%M")
            self.assertIn("tomorrow", T.set_reminder(message="late", at_time=earlier))   # already past today
            self.assertGreater(timer.call_args[0][0], 23 * 3600)

    def test_reminders_need_a_valid_time(self):
        self.fails(lambda: T.set_reminder(message="x"), "how many minutes")
        self.fails(lambda: T.set_reminder(message="x", at_time="7pm"), "HH:MM")
        self.fails(lambda: T.set_reminder(message="x", at_time="25:00"), "HH:MM")


class ReminderRingTests(ToolCase):
    def ring(self, message, notification_fails=False, sound_fails=False):
        notify = mock.Mock(side_effect=RuntimeError("no desktop") if notification_fails else None)
        play = mock.Mock(side_effect=OSError("no sound device") if sound_fails else None)
        modules = {"plyer": SimpleNamespace(notification=SimpleNamespace(notify=notify)),
                   "sound_player": SimpleNamespace(playsound=play)}
        with mock.patch.dict(sys.modules, modules), mock.patch("speech.Speak") as speak:
            productivity._ring(message)
        return notify, play, speak

    def test_a_reminder_shows_a_notification_plays_the_alarm_and_says_what_it_is_for(self):
        notify, play, speak = self.ring("drink water")
        self.assertEqual(notify.call_args.kwargs["message"], "drink water")
        self.assertTrue(str(play.call_args[0][0]).endswith("1.mp3"))
        speak.assert_called_once_with("Reminder: drink water")

    def test_messages_that_are_already_sentences_are_spoken_as_they_are(self):
        for message in ("Your timer is done", "Wake up, sir", "Reminder"):
            _, _, speak = self.ring(message)
            speak.assert_called_once_with(message)

    def test_a_missing_notification_or_alarm_never_stops_it_being_said(self):
        _, _, speak = self.ring("call mum", notification_fails=True, sound_fails=True)
        speak.assert_called_once_with("Reminder: call mum")


class TimeTableTests(ToolCase):
    def test_the_time_table_starts_empty_with_instructions(self):
        text = T.get_timetable_block()
        self.assertIn("empty", text)
        saved = json.loads((self.db / "TimeTable" / "timetable.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["blocks"], [])
        self.assertIn("_help", saved)

    def test_now_and_next(self):
        T.add_timetable_block(start="06:00", end="09:00", activity="Study")
        T.add_timetable_block(start="09:00", end="10:00", activity="Breakfast")
        self.assertEqual(T.get_timetable_block(at_time="07:30"), "Right now: Study until 09:00. Next: Breakfast at 09:00.")
        self.assertEqual(T.get_timetable_block(at_time="12:00"), "Nothing is scheduled right now. Next: Study at 06:00.")

    def test_the_current_block_is_never_also_reported_as_next(self):
        T.add_timetable_block(start="06:00", end="09:00", activity="Study")
        self.assertEqual(T.get_timetable_block(at_time="07:30"), "Right now: Study until 09:00.")

    def test_blocks_can_cross_midnight(self):
        T.add_timetable_block(start="22:00", end="06:00", activity="Sleep")
        T.add_timetable_block(start="07:00", end="08:00", activity="Gym")
        self.assertIn("Right now: Sleep until 06:00", T.get_timetable_block(at_time="23:30"))
        self.assertIn("Right now: Sleep until 06:00", T.get_timetable_block(at_time="03:00"))
        self.assertIn("Next: Gym at 07:00", T.get_timetable_block(at_time="06:30"))

    def test_bad_blocks_and_files_are_explained(self):
        self.fails(lambda: T.add_timetable_block(start="25:00", end="26:00", activity="x"), "not a time")
        self.fails(lambda: T.add_timetable_block(start="08:00", end="08:00", activity="x"), "different")
        self.fails(lambda: T.add_timetable_block(start="08:00", end="09:00", activity="  "), "what the block is for")
        (self.db / "TimeTable").mkdir(exist_ok=True)
        (self.db / "TimeTable" / "timetable.json").write_text("{ nope", encoding="utf-8")
        self.fails(lambda: T.get_timetable_block(), "isn't valid JSON")


class BooksTests(ToolCase):
    def books(self):
        folder = self.db / "Books"
        folder.mkdir(exist_ok=True)
        return folder

    def test_no_books_is_explained(self):
        self.fails(lambda: T.read_book_page(), "no books")

    def test_a_page_is_read_by_fuzzy_title(self):
        make_pdf(self.books() / "Short Story.pdf", ["Once upon a time", "The end"])
        text = T.read_book_page(title="stroy", page=2)
        self.assertIn("Short Story, page 2 of 2", text)
        self.assertIn("The end", text)
        self.assertIn("Once upon a time", T.read_book_page(page=1))            # a single book needs no title

    def test_page_numbers_are_checked(self):
        make_pdf(self.books() / "Short Story.pdf", ["Once upon a time", "The end"])
        self.fails(lambda: T.read_book_page(page=3), "2 pages")
        self.fails(lambda: T.read_book_page(page=0), "2 pages")

    def test_several_books_need_a_title(self):
        make_pdf(self.books() / "First.pdf", ["a"])
        make_pdf(self.books() / "Second.pdf", ["b"])
        self.assertIn("Which book?", T.read_book_page())
        self.fails(lambda: T.read_book_page(title="zebra"), "couldn't find that book")

    def test_a_broken_pdf_does_not_crash(self):
        (self.books() / "Broken.pdf").write_bytes(b"this is not a pdf")
        logging.disable(logging.CRITICAL)                                            # pypdf logs the damage itself
        self.addCleanup(logging.disable, logging.NOTSET)
        self.fails(lambda: T.read_book_page(), "couldn't open Broken")


class LanguageAndHelperToolTests(ToolCase):
    def test_translation_uses_google_then_the_backup(self):
        google = mock.Mock()
        google.return_value.translate.return_value = "Bonjour"
        with mock.patch("deep_translator.GoogleTranslator", google):
            self.assertEqual(T.translate_text(text="Hello", target_language="French"), "Bonjour")
        google.assert_called_once_with(source="auto", target="fr")
        google.return_value.translate.side_effect = RuntimeError("rate limited")
        backup = mock.Mock()
        backup.return_value.translate.return_value = "Hola"
        with mock.patch("deep_translator.GoogleTranslator", google), mock.patch("deep_translator.MyMemoryTranslator", backup):
            self.assertEqual(T.translate_text(text="Hello", target_language="es"), "Hola")
        backup.return_value.translate.side_effect = RuntimeError("down")
        with mock.patch("deep_translator.GoogleTranslator", google), mock.patch("deep_translator.MyMemoryTranslator", backup):
            self.fails(lambda: T.translate_text(text="Hello", target_language="es"), "aren't answering")

    def test_translation_into_an_unknown_language_lists_the_choices(self):
        self.fails(lambda: T.translate_text(text="Hello", target_language="Klingon"), "Klingon", "urdu")

    def test_acronyms_skip_filler_words(self):
        self.assertEqual(T.make_acronym(phrase="portable network graphics"), "PNG (P, N, G) stands for portable network graphics.")
        self.assertTrue(T.make_acronym(phrase="the Bank of England").startswith("BE "))
        self.fails(lambda: T.make_acronym(phrase="   "), "phrase")

    def test_folders_are_created_once(self):
        self.assertIn("Created the folder", T.create_folder(name="Projects", location=str(self.db)))
        self.assertTrue((self.db / "Projects").is_dir())
        self.fails(lambda: T.create_folder(name="Projects", location=str(self.db)), "already a folder")
        self.fails(lambda: T.create_folder(name="bad:name", location=str(self.db)), "can't contain")
        self.fails(lambda: T.create_folder(name="x", location=str(self.db / "missing")), "can't find the place")

    def test_generated_passwords_go_to_the_clipboard_and_never_into_the_reply(self):
        with mock.patch.object(productivity, "copy_to_clipboard") as clipboard:
            text = T.generate_password(length=20)
            password = clipboard.call_args[0][0]
            self.assertEqual(len(password), 20)
            self.assertNotIn(password, text)
            self.assertIn("20-character", text)
            T.generate_password(length=2)
            self.assertEqual(len(clipboard.call_args[0][0]), 8)
            T.generate_password(length=500)
            self.assertEqual(len(clipboard.call_args[0][0]), 64)


class WolframTests(ToolCase):
    def test_it_needs_an_app_id(self):
        with mock.patch.object(productivity.config, "WOLFRAM_APP_ID", ""):
            self.fails(lambda: T.ask_wolfram_alpha(question="2+2"), "WOLFRAM_APP_ID")

    def test_answers_and_refusals(self):
        with mock.patch.object(productivity.config, "WOLFRAM_APP_ID", "secret-id-123"):
            self.http.on("wolframalpha.com", FakeResponse(text="1.548 au (astronomical units)\n"))
            self.assertEqual(T.ask_wolfram_alpha(question="distance to mars"), "1.548 au (astronomical units)")
            self.assertEqual(self.http.params_for("wolframalpha")["appid"], "secret-id-123")
            self.http.routes[0] = ("wolframalpha.com", FakeResponse(text="no", status=501))
            self.fails(lambda: T.ask_wolfram_alpha(question="gibberish"), "couldn't answer")
            self.http.routes[0] = ("wolframalpha.com", FakeResponse(text="bad", status=403))
            self.fails(lambda: T.ask_wolfram_alpha(question="x"), "App ID")

    def test_errors_never_reveal_the_app_id(self):
        with mock.patch.object(productivity.config, "WOLFRAM_APP_ID", "secret-id-123"):
            self.http.on("wolframalpha.com", requests.ConnectionError("GET /v1/result?appid=secret-id-123 failed"))
            message = self.fails(lambda: T.ask_wolfram_alpha(question="x"), "couldn't reach")
            self.assertNotIn("secret-id-123", message)


if __name__ == "__main__":
    unittest.main()
