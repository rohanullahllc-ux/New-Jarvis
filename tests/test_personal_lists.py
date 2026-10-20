"""Tests for your own shortcuts and contacts, and for opening the admin panel by voice:  python -m unittest tests.test_personal_lists -v"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contacts  # noqa: E402
import shortcuts  # noqa: E402
import ui_bridge  # noqa: E402
from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import LocalBrain as L  # noqa: E402
from tests.test_localbrain import BrainCase  # noqa: E402


class Folder(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)


class ShortcutDataTests(Folder):
    def test_a_name_is_compared_without_my_the_punctuation_and_trailing_nouns(self):
        for said in ("college portal", "my college portal", "the College Portal!", "my college portal website", "college-portal folder"):
            self.assertEqual(shortcuts.clean_name(said), "college portal", said)
        self.assertEqual(shortcuts.clean_name("Tom & Jerry"), "tom and jerry")

    def test_a_good_shortcut_is_tidied(self):
        ok, tidy, message = shortcuts.check({"name": "  College   portal ", "kind": "website", "target": "www.cecos.edu.pk"})
        self.assertTrue(ok, message)
        self.assertEqual(tidy, {"name": "College portal", "kind": "website", "target": "https://www.cecos.edu.pk"})
        ok, tidy, _ = shortcuts.check({"name": "docs", "kind": "folder", "target": '"~/Documents"'})
        self.assertTrue(ok)
        self.assertNotIn('"', tidy["target"])
        self.assertNotIn("~", tidy["target"])

    def test_a_bad_shortcut_says_what_is_wrong_in_plain_words(self):
        cases = [({"name": "", "kind": "website", "target": "a.com"}, "name"), ({"name": "x" * 50, "kind": "website", "target": "a.com"}, "too long"),
                 ({"name": "my folder", "kind": "website", "target": "a.com"}, "letters or numbers"), ({"name": "a", "kind": "banana", "target": "x"}, "Choose what it opens"),
                 ({"name": "a", "kind": "website", "target": ""}, "Say where"), ({"name": "a", "kind": "website", "target": "not an address"}, "needs an address"),
                 ({"name": "a", "kind": "website", "target": "ftp://files.example.com"}, "http")]
        for item, words in cases:
            ok, _, message = shortcuts.check(item)
            self.assertFalse(ok, item)
            self.assertIn(words, message, item)

    def test_saving_and_loading_round_trip_and_a_damaged_file_is_no_shortcuts(self):
        path = self.folder / "shortcuts.json"
        items = [{"name": "college portal", "kind": "website", "target": "https://example.com"}, {"name": "projects", "kind": "folder", "target": str(self.folder)}]
        shortcuts.save(items, path)
        self.assertEqual(shortcuts.load(path), items)
        path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(shortcuts.load(path), [])
        self.assertEqual(shortcuts.load(self.folder / "missing.json"), [])

    def test_the_cache_notices_that_the_file_changed(self):
        path = self.folder / "shortcuts.json"
        shortcuts.save([{"name": "one", "kind": "website", "target": "https://a.com"}], path)
        self.assertEqual(len(shortcuts.load(path)), 1)
        shortcuts.save([{"name": "one", "kind": "website", "target": "https://a.com"}, {"name": "two", "kind": "website", "target": "https://b.com"}], path)
        self.assertEqual(len(shortcuts.load(path)), 2)

    def test_find_is_loose_about_the_words_and_about_a_slip_of_the_ear(self):
        items = [{"name": "College portal", "kind": "website", "target": "https://a.com"}, {"name": "Budget sheet", "kind": "file", "target": "x"}]
        for said in ("college portal", "my college portal", "the college portal website", "collage portal"):
            self.assertEqual(shortcuts.find(said, items)["name"], "College portal", said)
        self.assertIsNone(shortcuts.find("calculator", items))
        self.assertIsNone(shortcuts.find("college", items))                    # part of a name is not the name
        self.assertIsNone(shortcuts.find("", items))
        self.assertIsNone(shortcuts.find("anything", []))

    def test_problems_are_found_without_being_fixed(self):
        self.assertEqual(shortcuts.problems({"name": "a", "kind": "folder", "target": str(self.folder / "gone")}), "that folder does not exist")
        self.assertEqual(shortcuts.problems({"name": "a", "kind": "folder", "target": str(self.folder)}), "")
        self.assertEqual(shortcuts.problems({"name": "a", "kind": "website", "target": "https://a.com"}), "")

    def test_opening_each_kind(self):
        with mock.patch("os.startfile", create=True) as startfile, mock.patch("JarvisAdvancedBot.tools.open_website") as site, \
                mock.patch("JarvisAdvancedBot.tools.open_app") as app:
            shortcuts.open_it({"name": "n", "kind": "website", "target": "https://a.com"})
            site.assert_called_once_with("https://a.com")
            shortcuts.open_it({"name": "n", "kind": "folder", "target": str(self.folder)})
            startfile.assert_called_with(str(self.folder))
            document = self.folder / "budget.xlsx"
            document.write_text("x")
            shortcuts.open_it({"name": "n", "kind": "file", "target": str(document)})
            startfile.assert_called_with(str(document))
            shortcuts.open_it({"name": "n", "kind": "app", "target": "spotify"})
            app.assert_called_once_with("spotify")

    def test_a_shortcut_to_something_that_is_gone_says_so(self):
        with mock.patch("os.startfile", create=True) as startfile:
            with self.assertRaises(ToolError) as caught:
                shortcuts.open_it({"name": "old stuff", "kind": "folder", "target": str(self.folder / "gone")})
            self.assertIn("does not exist any more", str(caught.exception))
            with self.assertRaises(ToolError):
                shortcuts.open_it({"name": "old", "kind": "file", "target": str(self.folder / "gone.txt")})
            with self.assertRaises(ToolError):
                shortcuts.open_it({"name": "prog", "kind": "app", "target": str(self.folder / "gone.exe")})
            startfile.assert_not_called()


class ContactDataTests(Folder):
    def test_a_good_contact_is_tidied_and_a_bad_one_explained(self):
        ok, tidy, _ = contacts.check({"name": " Ali  Khan ", "email": "ALI@Example.com", "phone": "+92 300 1234567", "note": "brother"})
        self.assertTrue(ok)
        self.assertEqual((tidy["name"], tidy["email"]), ("Ali Khan", "ali@example.com"))
        for item, words in (({"name": "", "email": "a@b.com"}, "name"), ({"name": "Ali", "email": "not an address"}, "name@example.com"),
                            ({"name": "Ali", "phone": "abc"}, "phone"), ({"name": "Ali"}, "email address or a phone")):
            ok, _, message = contacts.check(item)
            self.assertFalse(ok, item)
            self.assertIn(words, message)

    def test_names_are_found_loosely(self):
        people = [{"name": "Ali", "email": "ali@example.com"}, {"name": "My boss", "email": "boss@example.com"}]
        self.assertEqual(contacts.find("to ali", people)["email"], "ali@example.com")
        self.assertEqual(contacts.find("Ali", people)["email"], "ali@example.com")
        self.assertEqual(contacts.find("my boss", people)["email"], "boss@example.com")
        self.assertEqual(contacts.find("boss", people)["email"], "boss@example.com")
        self.assertIsNone(contacts.find("zubair", people))

    def test_email_for_ignores_addresses_that_were_spoken_or_typed(self):
        path = self.folder / "contacts.json"
        contacts.save([{"name": "Ali", "email": "ali@example.com", "phone": "", "note": ""}], path)
        with mock.patch.object(contacts, "file", return_value=path):
            self.assertEqual(contacts.email_for("Ali"), "ali@example.com")
            self.assertIsNone(contacts.email_for("ali at gmail dot com"))
            self.assertIsNone(contacts.email_for("ali@gmail.com"))
            self.assertIsNone(contacts.email_for("Zubair"))

    def test_a_contact_without_an_email_gives_none(self):
        with mock.patch.object(contacts, "load", return_value=[{"name": "Ali", "phone": "+92 300 1234567"}]):
            self.assertIsNone(contacts.email_for("Ali"))

    def test_save_and_load_round_trip(self):
        path = self.folder / "contacts.json"
        contacts.save([{"name": "Ali", "email": "ali@example.com", "phone": "", "note": ""}], path)
        self.assertEqual(contacts.load(path)[0]["email"], "ali@example.com")
        path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(contacts.load(path), [])


class ShortcutCommandTests(BrainCase, Folder):
    def setUp(self):
        BrainCase.setUp(self)
        Folder.setUp(self)
        path = self.folder / "shortcuts.json"
        shortcuts.save([{"name": "college portal", "kind": "website", "target": "https://portal.example.edu"},
                        {"name": "calculator", "kind": "website", "target": "https://calc.example.com"}], path)
        patcher = mock.patch.object(shortcuts, "file", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_shortcut_is_opened_by_its_name_however_it_is_asked_for(self):
        for phrase in ("open college portal", "open my college portal", "launch the college portal", "go to college portal", "open college portal shortcut",
                       "ok could you please open the college portal for me"):
            reply = self.routes(phrase, "open_website", "https://portal.example.edu")
            self.assertEqual(reply, "Opening college portal, sir.", phrase)

    def test_a_shortcut_beats_the_built_in_meaning_of_the_same_words(self):
        self.routes("open calculator", "open_website", "https://calc.example.com")

    def test_words_that_are_not_a_shortcut_still_do_what_they_always_did(self):
        self.routes("open chrome", "open_app", "chrome")
        self.routes("open downloads", "open_folder", "downloads")

    def test_a_shortcut_to_something_missing_says_so_instead_of_crashing(self):
        shortcuts.save([{"name": "old stuff", "kind": "folder", "target": str(self.folder / "gone")}], self.folder / "shortcuts.json")
        self.assertIn("does not exist any more", self.no_tool("open old stuff"))

    def test_listing_the_shortcuts(self):
        reply = self.no_tool("what are my shortcuts")
        self.assertIn("college portal", reply)
        shortcuts.save([], self.folder / "shortcuts.json")
        self.assertIn("no shortcuts yet", self.no_tool("list my shortcuts"))

    def test_a_shortcut_name_counts_as_a_command_for_picking_what_was_heard(self):
        self.assertTrue(L.is_command("open college portal"))
        self.assertFalse(L.is_command("open the pod bay doors for the whole crew tonight"))


class EmailToAContactTests(BrainCase, Folder):
    def setUp(self):
        BrainCase.setUp(self)
        Folder.setUp(self)
        path = self.folder / "contacts.json"
        contacts.save([{"name": "Ali", "email": "ali@example.com", "phone": "", "note": ""}], path)
        for patcher in (mock.patch.object(contacts, "file", return_value=path), mock.patch.multiple(L.config, EMAIL_ADDRESS="me@gmail.com", EMAIL_PASSWORD="app-pass")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_name_from_the_contacts_is_enough(self):
        self.routes("send an email", "send_email", "ali@example.com", "Hello", "See you tomorrow", confirmed=True, answers=["Ali", "Hello", "See you tomorrow", "yes"])
        self.assertIn("ali@example.com", self.questions[3])

    def test_a_spoken_address_still_works_beside_the_contacts(self):
        self.routes("send an email", "send_email", "john.smith@gmail.com", "Hi", "Body", confirmed=True,
                    answers=["john dot smith at gmail dot com", "Hi", "Body", "yes"])

    def test_a_name_that_is_not_a_contact_is_read_as_before(self):
        reply = self.no_tool("send an email", ["zubair", "Hi", "Body", "no"])
        self.assertEqual(reply, "Okay, I haven't sent anything.")
        self.assertIn("zubair", self.questions[3])


class AdminCommandTests(BrainCase):
    PHRASES = ("open the admin panel", "open admin", "show the administrator panel", "launch my admin window", "open jarvis settings", "change jarvis's settings",
               "edit my settings", "change my preferences", "open the jarvis preferences")

    def test_the_window_is_asked_to_open_the_panel_when_there_is_one(self):
        for phrase in self.PHRASES:
            with mock.patch.object(ui_bridge, "request", return_value=True) as request:
                reply = self.no_tool(phrase)
            request.assert_called_once_with("admin")
            self.assertIn("admin panel", reply, phrase)
            self.assertIn("password", reply, phrase)

    def test_with_no_window_the_panel_opens_on_its_own(self):
        with mock.patch.object(ui_bridge, "request", return_value=False), mock.patch("subprocess.Popen") as popen:
            reply = self.no_tool("open the admin panel")
        command = popen.call_args[0][0]
        self.assertTrue(command[-1].endswith("JarvisAdmin.py"), command)
        self.assertIn("own window", reply)

    def test_if_it_cannot_start_the_reply_says_how_to_do_it_by_hand(self):
        with mock.patch.object(ui_bridge, "request", return_value=False), mock.patch("subprocess.Popen", side_effect=OSError("no")):
            self.assertIn("Admin-Panel", self.no_tool("open the admin panel"))

    def test_windows_own_settings_are_still_windows_settings(self):
        self.routes("open settings", "windows_action", "open_settings")


class UiBridgeTests(unittest.TestCase):
    def tearDown(self):
        ui_bridge.unregister("test")

    def test_a_request_reaches_the_registered_handler(self):
        calls = []
        ui_bridge.register("test", lambda *a: calls.append(a))
        self.assertTrue(ui_bridge.request("test", 1, 2))
        self.assertEqual(calls, [(1, 2)])

    def test_with_no_handler_or_a_handler_that_fails_the_answer_is_false(self):
        self.assertFalse(ui_bridge.request("test"))
        ui_bridge.register("test", lambda: 1 / 0)
        self.assertFalse(ui_bridge.request("test"))

    def test_unregistering_only_removes_your_own_handler(self):
        mine, theirs = (lambda: None), (lambda: None)
        ui_bridge.register("test", theirs)
        ui_bridge.unregister("test", mine)
        self.assertTrue(ui_bridge.request("test"))
        ui_bridge.unregister("test", theirs)
        self.assertFalse(ui_bridge.request("test"))


if __name__ == "__main__":
    unittest.main()
