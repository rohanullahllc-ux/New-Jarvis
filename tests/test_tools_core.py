"""Tests for the tools package core: shared helpers, registry, info, web, windows and productivity tools.

    python -m unittest tests.test_tools_core -v
"""
import datetime
import json
import logging
import os
import sys
import time
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
    def setUp(self):
        super().setUp()
        info._home_country.cache_clear()                    # (the user's home country is remembered between lookups)
        self.addCleanup(info._home_country.cache_clear)

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

    # ---- finding a place from what was said. The real geocoder only knows whole names, so the fake does too.

    def geocoder(self, **places_by_name):
        def answer(url, params):
            found = places_by_name.get(params["name"].lower())
            return FakeResponse({"results": found} if found else {})
        self.http.on("geocoding-api.open-meteo.com", answer)

    @staticmethod
    def place(name, country, code, admin1=""):
        return {"name": name, "country": country, "country_code": code, "admin1": admin1, "latitude": 1.0, "longitude": 2.0}

    def test_a_country_after_the_place_chooses_between_places_of_the_same_name(self):
        other, pakistan = self.place("Murree", "Nowhere", "NW"), self.place("Murree", "Pakistan", "PK", "Punjab")
        self.geocoder(murree=[other, pakistan])
        self.assertEqual(info.find_place("Murree in Pakistan")["country_code"], "PK")
        self.assertEqual(info.find_place("Murree, Pakistan")["country_code"], "PK")
        self.assertEqual(info.find_place("murree in PK")["country_code"], "PK")
        self.assertEqual(info.find_place("Murree")["country_code"], "NW")               # no country said: the geocoder's first choice

    def test_common_country_abbreviations_are_understood(self):
        self.geocoder(springfield=[self.place("Springfield", "United Kingdom", "GB"), self.place("Springfield", "United States", "US")])
        self.assertEqual(info.find_place("Springfield in the usa" .replace("the ", ""))["country_code"], "US")
        self.assertEqual(info.find_place("springfield, uk")["country_code"], "GB")

    def test_a_name_the_geocoder_only_half_knows_is_found_by_its_words_longest_first(self):
        kaghan = self.place("Kaghan", "Pakistan", "PK", "Khyber Pakhtunkhwa")
        self.geocoder(kaghan=[kaghan], narran=[self.place("Narran", "Australia", "AU")])
        self.assertEqual(info.find_place("narran kaghan")["name"], "Kaghan")              # (the words "narran" and "kaghan")
        self.assertEqual(info.find_place("narran kaghan in pakistan")["name"], "Kaghan")

    def test_with_no_country_said_a_place_in_the_users_own_country_wins(self):
        india, pakistan = self.place("Murree", "India", "IN"), self.place("Murree", "Pakistan", "PK")
        self.geocoder(peshawar=[self.place("Peshawar", "Pakistan", "PK")], murree=[india, pakistan])
        self.assertEqual(info.find_place("Murree")["country_code"], "PK")                  # (Peshawar is the default city)

    def test_if_the_home_city_cannot_be_found_the_geocoders_first_choice_is_used(self):
        self.geocoder(murree=[self.place("Murree", "India", "IN"), self.place("Murree", "Pakistan", "PK")])
        self.assertEqual(info.find_place("Murree")["country_code"], "IN")

    def test_a_half_known_name_prefers_the_word_that_is_in_the_users_country(self):
        """"narayan kagan" is Kagan in Pakistan for someone in Peshawar, not Narayan in India."""
        self.geocoder(peshawar=[self.place("Peshawar", "Pakistan", "PK")],
                      narayan=[self.place("Narayan", "India", "IN")],
                      kagan=[self.place("Kagan", "Turkey", "TR"), self.place("Kagan", "Pakistan", "PK", "Khyber Pakhtunkhwa")])
        found = info.find_place("narayan kagan")
        self.assertEqual((found["name"], found["country_code"]), ("Kagan", "PK"))

    def test_a_half_known_name_with_nothing_at_home_uses_the_first_word_that_finds_anything(self):
        self.geocoder(peshawar=[self.place("Peshawar", "Pakistan", "PK")], narayan=[self.place("Narayan", "India", "IN")])
        self.assertEqual(info.find_place("narayan kagan")["name"], "Narayan")

    def test_a_country_that_matches_nothing_is_an_honest_failure_not_a_place_in_the_wrong_country(self):
        self.geocoder(narayan=[self.place("Narayan", "India", "IN", "Himachal Pradesh")])
        self.assertIsNone(info.find_place("narayan khan in pakistan"))                    # India is not what was asked for
        self.fails(lambda: T.get_weather(city="narayan khan in pakistan"), "couldn't find a place called narayan khan in pakistan")

    def test_looking_for_a_place_never_asks_the_geocoder_more_than_five_times(self):
        self.geocoder()
        self.assertIsNone(info.find_place("alpha beta gamma delta epsilon zeta"))
        self.assertLessEqual(len(self.http.calls), 5)                       # the name, three of its words, and the home city

    def test_weather_for_a_half_known_place_names_the_place_it_used(self):
        self.geocoder(kaghan=[self.place("Kaghan", "Pakistan", "PK")])
        self.http.on("api.open-meteo.com/v1/forecast", FakeResponse(
            {"current": {"temperature_2m": 12.0, "apparent_temperature": 10.0, "relative_humidity_2m": 60,
                         "wind_speed_10m": 5.0, "weather_code": 3},
             "daily": {"temperature_2m_max": [15.0], "temperature_2m_min": [4.0], "precipitation_probability_max": [20]}}))
        self.assertTrue(T.get_weather(city="narran kaghan in pakistan").startswith("Kaghan, Pakistan: overcast"))

    def test_uptime_is_said_the_way_it_is_spoken(self):
        for seconds, spoken in ((3 * 86400 + 20 * 3600 + 48 * 60 + 58, "3 days and 20 hours"), (86400 + 60, "1 day"),
                                (5 * 3600 + 12 * 60, "5 hours and 12 minutes"), (3600, "1 hour"), (125, "2 minutes"), (20, "under a minute")):
            self.assertEqual(info.spoken_duration(seconds), spoken)

    def test_the_pc_status_says_how_long_it_has_been_running_in_words(self):
        with mock.patch.object(info.psutil, "boot_time", return_value=info.time.time() - (2 * 86400 + 3 * 3600)):
            self.assertIn("running for 2 days and 3 hours", T.get_system_status())

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
        self.assertEqual(self.http.calls, [])                               # only looking at results: nothing to look up
        page = '{"contents":[{"videoRenderer":{"videoId":"kJQP7kiw5Fk","title":"x"}},{"videoRenderer":{"videoId":"TfkP5ubz1z4"}}]}'
        self.http.on("youtube.com", FakeResponse(None, text=page))
        del self.opened[:]
        self.assertEqual(T.youtube(query="lo fi beats"), "Playing lo fi beats on YouTube")
        self.assertEqual(self.opened, ["https://www.youtube.com/watch?v=kJQP7kiw5Fk"])
        self.assertEqual(self.http.params_for("youtube.com")["search_query"], "lo fi beats")

    def test_youtube_falls_back_to_results_when_the_best_match_cannot_be_found(self):
        self.http.on("youtube.com", requests.ConnectionError("no internet"))
        self.assertIn("results", T.youtube(query="song"))
        self.http.routes = [("youtube.com", FakeResponse(None, text="<html>nothing we can read</html>"))]
        self.assertIn("results", T.youtube(query="song"))
        self.assertEqual(self.opened, ["https://www.youtube.com/results?search_query=song"] * 2)

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

    def test_the_windows_calendar_is_opened_by_its_address_since_it_has_no_program_name(self):
        with mock.patch.object(windows.os, "startfile") as startfile:
            self.assertEqual(T.open_app(name="calendar"), "Opened calendar")
        startfile.assert_called_once_with("outlookcal:")

    def test_the_calendar_falls_back_to_the_start_menu_if_its_address_does_not_work(self):
        with mock.patch.object(windows.os, "startfile", side_effect=OSError), mock.patch("keyboard.send"),                 mock.patch("keyboard.write") as write, mock.patch.object(windows.time, "sleep"):
            self.assertIn("Start menu", T.open_app(name="calendar"))
        write.assert_called_once_with("calendar", delay=0.02)

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

    def test_open_folder_finds_a_folder_by_its_name_in_the_usual_places(self):
        home = self.db / "home"
        (home / "Documents" / "Python Projects").mkdir(parents=True)
        (home / "Downloads" / "stuff" / "Deep One").mkdir(parents=True)
        with mock.patch.object(windows, "_folder_roots", return_value=[home / "Documents", home / "Downloads"]), \
                mock.patch.object(windows.os, "startfile") as startfile:
            self.assertEqual(T.open_folder(location="python projects"), f"Opened {home / 'Documents' / 'Python Projects'}")
            startfile.assert_called_once_with(str(home / "Documents" / "Python Projects"))
            T.open_folder(location="deep-one")                       # one level deeper; capitals, dashes and spaces do not matter
            self.assertEqual(startfile.call_args[0][0], str(home / "Downloads" / "stuff" / "Deep One"))
            self.fails(lambda: T.open_folder(location="zebra"), "can't find")

    def test_a_folder_name_is_never_looked_for_in_the_folder_jarvis_happens_to_run_in(self):
        (self.db / "only_here").mkdir()
        before = os.getcwd()
        os.chdir(self.db)
        self.addCleanup(os.chdir, before)
        with mock.patch.object(windows, "_folder_roots", return_value=[]), mock.patch.object(windows.os, "startfile") as startfile:
            self.fails(lambda: T.open_folder(location="only_here"), "can't find")
            self.fails(lambda: T.open_folder(location=""), "can't find")
        startfile.assert_not_called()

    def test_two_folders_with_the_same_name_open_the_first_and_say_there_is_another(self):
        first, second = self.db / "a" / "Docs", self.db / "b" / "Docs"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        with mock.patch.object(windows, "_folder_roots", return_value=[self.db / "a", self.db / "b"]), \
                mock.patch.object(windows.os, "startfile") as startfile:
            self.assertEqual(T.open_folder(location="docs"), f"Opened {first} (there is 1 more with that name)")
        startfile.assert_called_once_with(str(first))

    def test_the_usual_places_are_windows_own_folders_then_the_home_folder(self):
        roots = windows._folder_roots()
        self.assertEqual(roots[-1], Path.home())
        self.assertTrue(all(root.is_dir() for root in roots))

    def test_first_sentences_do_not_end_at_the_numbers_of_a_list(self):
        listing = "Recent notes: 1. buy milk, 2. call ali, 3. pay rent, 4. plan the trip, 5. gym"
        self.assertEqual(_common.first_sentences(listing, 2), listing)
        self.assertEqual(_common.first_sentences("Your notes: 1. a; 2. b; 3. c; 10. d; 11. e", 1), "Your notes: 1. a; 2. b; 3. c; 10. d; 11. e")
        self.assertEqual(_common.first_sentences("It ended in 1945. Then it began. Next", 2), "It ended in 1945. Then it began.")
        self.assertEqual(_common.first_sentences("", 2), "")

    def test_open_folder_asks_windows_where_its_own_folders_are(self):
        moved = self.db / "OneDrive" / "Desktop"                            # where OneDrive keeps it on many PCs
        moved.mkdir(parents=True)
        with mock.patch.object(windows.os, "startfile") as startfile, mock.patch.object(windows, "known_folder", return_value=moved) as where:
            T.open_folder(location="Desktop")
        where.assert_called_once_with("Desktop")
        startfile.assert_called_once_with(str(moved))

    def test_windows_knows_where_every_one_of_its_folders_is(self):
        for name in _common.KNOWN_FOLDERS:
            self.assertTrue(_common.known_folder(name).is_absolute(), name)
        self.assertTrue(_common.known_folder("Desktop").is_dir())
        self.assertEqual(_common.known_folder(" DOWNLOADS "), _common.known_folder("downloads"))

    def test_when_windows_cannot_say_the_folder_in_the_home_directory_is_used(self):
        with mock.patch.object(_common.ctypes, "windll", create=True, new=SimpleNamespace()):       # no shell32 at all
            self.assertEqual(_common.known_folder("music"), Path.home() / "Music")

    def test_screenshots_are_saved_under_a_safe_name(self):
        image = mock.Mock()
        with mock.patch("pyautogui.screenshot", return_value=image):
            self.assertEqual(T.take_screenshot(name="my:shot?"), "Saved the screenshot as myshot.png")
        image.save.assert_called_once_with(self.db / "ScreenShot" / "myshot.png")

    def test_screenshots_can_be_opened_as_a_folder_or_as_the_newest_picture(self):
        self.fails(lambda: T.open_screenshots(which="latest"), "no screenshots")
        shots = self.db / "ScreenShot"
        (shots / "old.png").write_bytes(b"1")
        time.sleep(0.02)
        (shots / "new.png").write_bytes(b"2")
        with mock.patch.object(windows.os, "startfile") as startfile:
            self.assertEqual(T.open_screenshots(which="latest"), "Opened new.png")
            self.assertEqual(startfile.call_args[0][0], shots / "new.png")
            self.assertEqual(T.open_screenshots(), "Opened the screenshots folder")
            self.assertEqual(startfile.call_args[0][0], shots)

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
        self.assertEqual(listing, "Your notes: 1. call the bank about the loan on Monday morning; 2. Shopping list: milk, eggs")
        self.assertNotIn("note-2026", listing)                                  # a short list is read in full, untitled notes as they are
        self.assertIn("milk, eggs", T.read_notes(title="shopping"))
        self.assertIn("Monday morning", T.read_notes(title="bank"))             # found by what it says, not just its title
        self.fails(lambda: T.read_notes(title="holiday"), "No note matching")

    def test_a_long_list_of_notes_is_shortened_to_what_each_starts_with(self):
        notes = self.db / "Notes"
        notes.mkdir(parents=True, exist_ok=True)
        for n in range(4):                                                       # (taken a second apart, as untitled notes are)
            (notes / f"note-20261018-10000{n}.txt").write_text(f"Sunday\n\nnote number {n} says something rather long indeed", encoding="utf-8")
        listing = T.read_notes()
        self.assertTrue(listing.startswith("Recent notes: "))
        self.assertIn("and so on", listing)

    def test_opening_a_note_opens_the_newest_file_or_the_folder(self):
        self.fails(lambda: T.open_notes(), "no saved notes")
        T.take_note(text="older")
        time.sleep(0.02)
        T.take_note(text="newer", title="Plan")
        with mock.patch.object(productivity.os, "startfile", create=True) as start:
            self.assertEqual(T.open_notes(), "Opened your latest note: newer")
            self.assertEqual(Path(start.call_args[0][0]).name, "Plan.txt")
            self.assertEqual(T.open_notes(which="folder"), "Opened the notes folder")
            self.assertEqual(Path(start.call_args[0][0]).name, "Notes")

    def test_tasks_are_numbered_and_removable(self):
        self.assertIn("empty", T.list_tasks())
        T.add_task(task="Buy bread")
        T.add_task(task="Call mum")
        self.assertIn("1. Buy bread; 2. Call mum", T.list_tasks())
        self.assertEqual(T.remove_task(number=1), "Removed: Buy bread")
        self.assertIn("1. Call mum", T.list_tasks())
        self.fails(lambda: T.remove_task(number=5), "no item 5")

    def test_a_task_can_be_removed_by_some_of_its_words_even_from_another_day(self):
        T.add_task(task="Buy bread")
        T.add_task(task="Call mum on the phone")
        T.add_task(task="Dentist visit", date="2026-12-01")
        self.assertEqual(T.remove_task(text="call mum"), "Removed: Call mum on the phone")
        self.assertEqual(T.remove_task(text="denist"), "Removed: Dentist visit")               # a typo, found on another day
        self.assertIn("1. Buy bread", T.list_tasks())
        self.fails(lambda: T.remove_task(text="water the plants"), "can't find an item like 'water the plants'")
        self.fails(lambda: T.remove_task(), "which item")
        T.add_task(task="Call Ali")
        T.add_task(task="Call Sana")
        self.fails(lambda: T.remove_task(text="call"), "Several items match", "Which number")
        self.assertFalse((self.db / "Tasks" / "2026-12-01-Task.txt").exists())                  # an emptied day leaves no file behind

    def test_clearing_tasks_needs_a_yes_and_counts_what_goes(self):
        T.add_task(task="a")
        T.add_task(task="b")
        T.add_task(task="c", date="2026-12-01")
        self.fails(lambda: T.clear_tasks(), "permanently delete 2 to-do items", "confirmed")
        self.assertEqual(T.list_tasks(), "To-do list for " + T.productivity.datetime.date.today().strftime("%A %d %B") + ": 1. a; 2. b")
        self.assertEqual(T.clear_tasks(confirmed=True), "Cleared 2 to-do items.")
        self.assertIn("c", T.list_tasks(date="2026-12-01"))               # the other day is untouched
        self.assertEqual(T.clear_tasks(every_day=True, confirmed=True), "Cleared 1 to-do item.")
        self.assertEqual(T.clear_tasks(every_day=True), "There were no to-do items to clear.")

    def test_notes_are_deleted_only_when_confirmed_and_only_the_ones_meant(self):
        notes = self.db / "Notes"
        notes.mkdir()
        for name, text, age in (("old", "buy milk", 100), ("mid", "python tonight", 200), ("new", "call the bank", 300)):
            (notes / f"{name}.txt").write_text(text, encoding="utf-8")
            os.utime(notes / f"{name}.txt", (time.time() - 1000 + age, time.time() - 1000 + age))
        self.fails(lambda: T.delete_notes(), "permanently delete 3 notes", "confirmed")
        self.assertEqual(len(list(notes.glob("*.txt"))), 3)
        self.assertEqual(T.delete_notes(which="latest", confirmed=True), "Deleted 1 note.")
        self.assertFalse((notes / "new.txt").exists())
        self.assertEqual(T.delete_notes(title="python", confirmed=True), "Deleted 1 note.")
        self.fails(lambda: T.delete_notes(title="zebra", confirmed=True), "can't find a note about 'zebra'")
        self.assertEqual(T.delete_notes(confirmed=True), "Deleted 1 note.")
        self.assertEqual(T.delete_notes(), "There are no saved notes to delete.")

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
    FREE = "translate.googleapis.com"

    def google_free_says(self, *sentences):
        """What Google's free address answers: a list of [translated, original, ...] pieces, then the language it detected."""
        self.http.on(self.FREE, FakeResponse([[[done, said, None, None, 1] for done, said in sentences], None, "en"]))

    def test_the_free_google_address_is_asked_first(self):
        self.google_free_says(("Bonjour", "Hello"))
        with mock.patch("deep_translator.GoogleTranslator") as page, mock.patch("JarvisAdvancedBot.ChatBrain.complete") as model:
            self.assertEqual(T.translate_text(text="Hello", target_language="French"), "Bonjour")
        page.assert_not_called()
        model.assert_not_called()
        params = self.http.params_for(self.FREE)
        self.assertEqual((params["tl"], params["q"], params["sl"]), ("fr", "Hello", "auto"))

    def test_a_reply_in_several_pieces_is_joined_into_one_translation(self):
        self.google_free_says(("Bonjour. ", "Hello. "), ("Comment allez-vous ?", "How are you?"))
        self.assertEqual(T.translate_text(text="Hello. How are you?", target_language="fr"), "Bonjour. Comment allez-vous ?")

    def test_when_the_free_address_refuses_the_page_google_is_asked_next(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page = mock.Mock()
        page.return_value.translate.return_value = "Hola"
        with mock.patch("deep_translator.GoogleTranslator", page):
            self.assertEqual(T.translate_text(text="Hello", target_language="es"), "Hola")
        page.assert_called_once_with(source="auto", target="es")

    def test_when_google_refuses_everywhere_the_model_on_this_pc_translates(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page, memory = mock.Mock(), mock.Mock()
        page.return_value.translate.side_effect = RuntimeError("TooManyRequests")
        with mock.patch("deep_translator.GoogleTranslator", page), mock.patch("deep_translator.MyMemoryTranslator", memory), \
                mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value="Comment allez-vous ?") as model:
            self.assertEqual(T.translate_text(text="how are you", target_language="French"), "Comment allez-vous ?")
        memory.assert_not_called()                                                # the crowd-sourced memory is not even asked
        system, user = model.call_args[0]
        self.assertIn("Translate the user's text into French", system)
        self.assertEqual(user, "how are you")

    def test_the_model_chatting_instead_of_translating_is_not_believed(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page, memory = mock.Mock(), mock.Mock()
        page.return_value.translate.side_effect = RuntimeError("TooManyRequests")
        memory.return_value.translate.return_value = "Merci"
        chatter = "Sure! I would be happy to help you with that translation, here it is with a few notes about the grammar. " * 3
        with mock.patch("deep_translator.GoogleTranslator", page), mock.patch("deep_translator.MyMemoryTranslator", memory), \
                mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value=chatter):
            self.assertEqual(T.translate_text(text="thanks", target_language="fr"), "Merci")

    def test_quotes_around_the_models_translation_are_removed(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page = mock.Mock()
        page.return_value.translate.side_effect = RuntimeError("TooManyRequests")
        with mock.patch("deep_translator.GoogleTranslator", page), mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value='"Danke"'):
            self.assertEqual(T.translate_text(text="thanks", target_language="de"), "Danke")

    def test_with_no_model_either_the_crowd_sourced_memory_is_the_last_resort_and_then_an_honest_failure(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page, memory = mock.Mock(), mock.Mock()
        page.return_value.translate.side_effect = RuntimeError("TooManyRequests")
        memory.return_value.translate.return_value = "Hola"
        with mock.patch("deep_translator.GoogleTranslator", page), mock.patch("deep_translator.MyMemoryTranslator", memory), \
                mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value=None):
            self.assertEqual(T.translate_text(text="Hello", target_language="es"), "Hola")
            memory.return_value.translate.side_effect = RuntimeError("down")
            self.fails(lambda: T.translate_text(text="Hello", target_language="es"), "aren't answering")

    def test_the_model_is_not_trusted_with_languages_it_gets_wrong(self):
        self.http.on(self.FREE, FakeResponse(status=429))
        page, memory = mock.Mock(), mock.Mock()
        page.return_value.translate.side_effect = RuntimeError("TooManyRequests")
        memory.return_value.translate.return_value = "صبح بخیر"
        with mock.patch("deep_translator.GoogleTranslator", page), mock.patch("deep_translator.MyMemoryTranslator", memory),                 mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value="nonsense") as model:
            self.assertEqual(T.translate_text(text="good morning", target_language="Urdu"), "صبح بخیر")
            self.assertEqual(T.translate_text(text="شکریہ", target_language="French"), "صبح بخیر")
        model.assert_not_called()                                   # not for Urdu, and not for reading Urdu either

    def test_language_names_for_the_model_are_the_ones_people_say(self):
        self.assertEqual((T.productivity.LANGUAGE_NAMES["ur"], T.productivity.LANGUAGE_NAMES["zh-CN"], T.productivity.LANGUAGE_NAMES["fa"]),
                         ("Urdu", "Chinese", "Persian"))

    def test_translation_uses_google_then_the_backup(self):
        self.http.on(self.FREE, FakeResponse(status=429))
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
        with mock.patch("deep_translator.GoogleTranslator", google), mock.patch("deep_translator.MyMemoryTranslator", backup), \
                mock.patch("JarvisAdvancedBot.ChatBrain.complete", return_value=None):
            self.fails(lambda: T.translate_text(text="Hello", target_language="es"), "aren't answering")

    def test_translation_into_an_unknown_language_lists_the_choices(self):
        self.fails(lambda: T.translate_text(text="Hello", target_language="Klingon"), "Klingon", "urdu")

    def test_acronyms_skip_filler_words(self):
        self.assertEqual(T.make_acronym(phrase="portable network graphics"), "PNG (P, N, G) stands for portable network graphics.")
        self.assertTrue(T.make_acronym(phrase="the Bank of England").startswith("BE "))
        self.fails(lambda: T.make_acronym(phrase="   "), "phrase")

    def test_a_folder_in_documents_goes_where_windows_keeps_documents(self):
        with mock.patch.object(productivity, "known_folder", return_value=self.db) as where:
            self.assertIn("Created the folder", T.create_folder(name="Projects", location="Documents"))
        where.assert_called_once_with("Documents")
        self.assertTrue((self.db / "Projects").is_dir())

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
