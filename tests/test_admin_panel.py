"""Tests for the admin panel:  python -m unittest tests.test_admin_panel -v

They run on Qt's invisible "offscreen" display, on a temporary copy of the Jarvis folder, so nothing real is read or changed."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

import backup_jarvis  # noqa: E402
import config  # noqa: E402
import contacts  # noqa: E402
import gate  # noqa: E402
import settings_registry as registry  # noqa: E402
import shortcuts  # noqa: E402
import ui_bridge  # noqa: E402
from envfile import EnvFile  # noqa: E402
from gui import admin_panel, admin_widgets, main_window, theme  # noqa: E402
from jarvis_setup import system  # noqa: E402
from jarvis_setup.effects import RunResult, Signature  # noqa: E402
from tests.isolation import no_personal_lists  # noqa: E402

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(theme.STYLESHEET)

ENV_TEXT = "# my settings\nUSER_NAME=Mr Khan\nSTARTUP_GREETING=long\nMIC_VOLUME=80\nTTS_RATE=0\nRAPIDAPI_KEY=abc123\nJARVIS_PASSWORD=plain-one\nNASA_API_KEY=secretkey1234\n"


def setUpModule():
    no_personal_lists()


class FakeEffects:
    """Nothing real: no internet, no Ollama, no PowerShell."""

    def http_json(self, url, timeout=3):
        return None

    def reachable(self, url, timeout=6):
        return False

    def powershell(self, script, timeout=60):
        raise RuntimeError("no PowerShell in tests")

    def signature(self, path):
        return Signature("Valid", "")

    def run(self, command, **kwargs):
        return RunResult(0, "")


def wait_for(condition, seconds=8):
    deadline = time.time() + seconds
    while time.time() < deadline:
        APP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


class PanelCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / ".env").write_text(ENV_TEXT, encoding="utf-8")
        (self.root / "DataBase" / "Notes").mkdir(parents=True)
        (self.root / "DataBase" / "Notes" / "n.txt").write_text("buy milk")
        (self.root / "models" / "piper").mkdir(parents=True)
        for name in ("en_GB-alan-medium", "en_US-ryan-medium"):
            (self.root / "models" / "piper" / f"{name}.onnx").write_text("x")
            (self.root / "models" / "piper" / f"{name}.onnx.json").write_text("{}")
        self.shortcut_file, self.contact_file = self.root / "DataBase" / "shortcuts.json", self.root / "DataBase" / "contacts.json"
        self.told, self.asked = [], []
        self.answer = True
        patchers = [mock.patch.object(shortcuts, "file", return_value=self.shortcut_file), mock.patch.object(contacts, "file", return_value=self.contact_file),
                    mock.patch.object(system, "audio_facts", return_value={"microphones": ["Test Microphone", "USB Headset"], "speakers": 1, "privacy": {}}),
                    mock.patch.object(config, "OLLAMA_URL", "http://127.0.0.1:9")]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def panel(self, **kwargs):
        def confirm(title, text, detail=""):
            self.asked.append((title, text, detail))
            return self.answer
        panel = admin_panel.AdminPanel(root=self.root, effects=FakeEffects(), confirm=confirm, tell=lambda title, text, detail="": self.told.append((title, text)), **kwargs)
        self.addCleanup(panel.close)
        self.addCleanup(lambda: wait_for(lambda: panel.check_button.isEnabled(), 6))          # (the health look-around ends before the panel goes)
        panel.show()
        APP.processEvents()
        return panel

    def env(self):
        return EnvFile(self.root / ".env")


class BuildTests(PanelCase):
    def test_every_visible_setting_has_a_row_with_the_value_it_has_now(self):
        panel = self.panel()
        visible = [s for s in registry.SETTINGS if not s.hidden]
        self.assertEqual(sorted(panel.rows), sorted(s.key for s in visible))
        self.assertEqual(panel.rows["USER_NAME"].value(), "Mr Khan")
        self.assertEqual(panel.rows["MIC_VOLUME"].value(), "80")
        self.assertEqual(panel.rows["TTS_ENABLED"].value(), "true")                  # not in .env: the usual value
        self.assertEqual(panel.rows["WAKE_SENSITIVITY"].value(), "0.5")
        self.assertEqual(panel.rows["CLAP_SENSITIVITY"].value(), "1")

    def test_there_is_a_page_for_each_group_and_the_extra_pages(self):
        panel = self.panel()
        titles = [panel.nav.item(i).text() for i in range(panel.nav.count())]
        self.assertEqual(titles[0], "Overview")
        for group in registry.GROUPS:
            self.assertIn(group.title, titles)
        for extra in ("Your shortcuts", "Your contacts", "Backup and restore", "Advanced"):
            self.assertIn(extra, titles)

    def test_nothing_is_changed_or_saveable_when_nothing_was_touched(self):
        panel = self.panel()
        self.assertEqual(panel.changed_rows(), {})
        self.assertFalse(panel.save_button.isEnabled())
        self.assertFalse(panel.revert_button.isEnabled())
        self.assertEqual(panel.save(), [])

    def test_the_voice_and_microphone_lists_are_made_on_this_pc(self):
        panel = self.panel()
        voices = [panel.rows["PIPER_VOICE"].editor.itemData(i) for i in range(panel.rows["PIPER_VOICE"].editor.count())]
        self.assertIn("en_GB-alan-medium", voices)
        self.assertIn("en_US-ryan-medium", voices)
        mics = [panel.rows["MIC_DEVICE"].editor.itemData(i) for i in range(panel.rows["MIC_DEVICE"].editor.count())]
        self.assertEqual(mics[0], "")
        self.assertIn("USB Headset", mics)

    def test_the_restart_button_only_exists_when_there_is_a_jarvis_to_restart(self):
        self.assertFalse(self.panel().restart_button.isVisible())
        self.assertTrue(self.panel(restart=lambda: None).restart_button.isVisible())

    def test_a_wrong_value_already_in_env_is_shown_and_has_to_be_corrected(self):
        panel = self.panel()
        row = panel.rows["STARTUP_GREETING"]
        self.assertIn("not a valid choice", row.editor.currentText())
        self.assertTrue(row.problem.isVisible() or not row.check().ok)
        self.assertFalse(row.check().ok)
        self.assertIn("Settings Jarvis would not understand", panel.problems_label.text())
        self.assertIn("STARTUP_GREETING", panel.problems_label.text())

    def test_the_advanced_settings_are_hidden_until_asked_for(self):
        panel = self.panel()
        advanced = [k for k, r in panel.rows.items() if r.setting.advanced]
        plain = [k for k, r in panel.rows.items() if not r.setting.advanced]
        self.assertTrue(advanced and plain)
        self.assertTrue(all(not panel.rows[k].isVisibleTo(panel) or panel.rows[k].isHidden() for k in advanced))
        panel.advanced_box.setChecked(True)
        panel.show_page("brain")
        APP.processEvents()
        self.assertTrue(all(not panel.rows[k].isHidden() for k in advanced))
        panel.advanced_box.setChecked(False)
        self.assertTrue(all(panel.rows[k].isHidden() for k in advanced))


class ChangingSettingsTests(PanelCase):
    def test_changing_a_number_marks_it_and_saving_writes_only_that_line(self):
        panel = self.panel()
        row = panel.rows["TTS_RATE"]
        row.editor.setValue(3)
        self.assertEqual(list(panel.changed_rows()), ["TTS_RATE"])
        self.assertTrue(panel.dirty_label.text().startswith("1 change"))
        panel.rows["STARTUP_GREETING"].set_value("short", from_user=True)               # the wrong value is put right in the same save
        written = panel.save()
        self.assertEqual(sorted(k for k, _, _ in written), ["STARTUP_GREETING", "TTS_RATE"])
        text = (self.root / ".env").read_text(encoding="utf-8")
        self.assertIn("TTS_RATE=3\n", text)
        self.assertIn("STARTUP_GREETING=short\n", text)
        self.assertIn("# my settings\n", text)                                        # comments, other lines and unknown keys are kept
        self.assertIn("RAPIDAPI_KEY=abc123\n", text)
        self.assertEqual(panel.changed_rows(), {})
        self.assertFalse(panel.save_button.isEnabled())

    def test_a_copy_of_the_old_file_is_kept_so_the_save_can_be_undone(self):
        panel = self.panel()
        panel.rows["USER_NAME"].editor.setText("Ali")
        panel.rows["STARTUP_GREETING"].set_value("full", from_user=True)
        panel.save()
        self.assertEqual(len(self.env().backups()), 1)
        panel.undo_last_save()
        self.assertEqual(self.env().get("USER_NAME"), "Mr Khan")
        self.assertEqual(panel.rows["USER_NAME"].value(), "Mr Khan")

    def test_the_confirmation_lists_the_changes_and_hides_passwords_and_keys(self):
        panel = self.panel()
        panel.rows["NASA_API_KEY"].editor.setText("another-secret-key")
        panel.rows["USER_NAME"].editor.setText("Ali")
        panel.rows["STARTUP_GREETING"].set_value("full", from_user=True)
        panel.save()
        detail = self.asked[-1][2]
        self.assertIn("Your name: Mr Khan  ->  Ali", detail)
        self.assertNotIn("another-secret-key", detail)
        self.assertNotIn("secretkey1234", detail)
        self.assertIn("*", detail)

    def test_saying_no_to_the_confirmation_writes_nothing(self):
        panel = self.panel()
        panel.rows["USER_NAME"].editor.setText("Ali")
        panel.rows["STARTUP_GREETING"].set_value("full", from_user=True)
        self.answer = False
        self.assertIsNone(panel.save())
        self.assertEqual(self.env().get("USER_NAME"), "Mr Khan")
        self.assertTrue(panel.changed_rows())

    def test_a_value_that_is_not_acceptable_stops_the_save_and_says_why(self):
        panel = self.panel()
        panel.rows["EMAIL_ADDRESS"].editor.setText("not an address")
        self.assertFalse(panel.rows["EMAIL_ADDRESS"].check().ok)
        self.assertTrue(panel.rows["EMAIL_ADDRESS"].problem.text())
        self.assertFalse(panel.save_button.isEnabled())
        self.assertIsNone(panel.save())
        self.assertIn("name@example.com", self.told[-1][1])
        self.assertEqual(self.env().get("EMAIL_ADDRESS", ""), "")                 # nothing was written

    def test_revert_puts_every_box_back(self):
        panel = self.panel()
        panel.rows["USER_NAME"].editor.setText("Ali")
        panel.rows["TTS_RATE"].editor.setValue(5)
        panel.revert()
        self.assertEqual(panel.rows["USER_NAME"].value(), "Mr Khan")
        self.assertEqual(panel.rows["TTS_RATE"].value(), "0")
        self.assertEqual(panel.changed_rows(), {})

    def test_the_usual_button_puts_the_usual_value_back(self):
        panel = self.panel()
        row = panel.rows["MIC_VOLUME"]
        row.editor.setValue(30)
        self.assertTrue(row.usual_button.isEnabled())
        row.usual_button.click()
        self.assertEqual(row.value(), "80")
        self.assertFalse(row.usual_button.isEnabled())

    def test_each_kind_of_control_reads_and_writes_its_value(self):
        panel = self.panel()
        checks = [("TTS_ENABLED", "false"), ("MIC_PAUSE", "2.5"), ("CLAP_COUNT", "3"), ("STT_MODEL", "small.en"), ("PIPER_VOICE", "en_US-ryan-medium"),
                  ("MIC_DEVICE", "USB Headset"), ("USER_NAME", "Ali"), ("HOME_CURRENCY", "USD"), ("ADDRESS_AS", "boss"), ("EMAIL_PASSWORD", "app-pass")]
        for key, value in checks:
            row = panel.rows[key]
            row.set_value(value, from_user=True)
            self.assertEqual(row.value(), value, key)
        panel.rows["STARTUP_GREETING"].set_value("short", from_user=True)
        panel.save()
        saved = self.env().values()
        for key, value in checks:
            self.assertEqual(saved[key], value, key)

    def test_a_secret_is_hidden_in_its_box_until_show_is_pressed(self):
        panel = self.panel()
        row = panel.rows["NASA_API_KEY"]
        from PyQt5.QtWidgets import QLineEdit
        self.assertEqual(row.editor.echoMode(), QLineEdit.Password)
        row.show_button.setChecked(True)
        self.assertEqual(row.editor.echoMode(), QLineEdit.Normal)

    def test_save_and_restart_saves_then_calls_the_restart(self):
        restarted = []
        panel = self.panel(restart=lambda: restarted.append(True))
        panel.rows["USER_NAME"].editor.setText("Ali")
        panel.rows["STARTUP_GREETING"].set_value("short", from_user=True)
        panel.save_and_restart()
        self.assertEqual(restarted, [True])
        self.assertEqual(self.env().get("USER_NAME"), "Ali")

    def test_a_refused_save_does_not_restart(self):
        restarted = []
        panel = self.panel(restart=lambda: restarted.append(True))
        panel.rows["USER_NAME"].editor.setText("Ali")
        self.answer = False
        panel.save_and_restart()
        self.assertEqual(restarted, [])

    def test_closing_with_unsaved_changes_asks_first(self):
        panel = self.panel()
        panel.rows["USER_NAME"].editor.setText("Ali")
        self.answer = False
        panel.close_panel()
        self.assertTrue(panel.isVisible())
        self.answer = True
        panel.close_panel()
        self.assertFalse(panel.isVisible())

    def test_reloading_after_the_file_changed_elsewhere_updates_the_boxes(self):
        panel = self.panel()
        self.env().set("USER_NAME", "Zubair")
        panel.reload_from_env()
        self.assertEqual(panel.rows["USER_NAME"].value(), "Zubair")
        self.assertEqual(panel.changed_rows(), {})


class SearchTests(PanelCase):
    def test_searching_hides_the_rows_that_do_not_match_and_goes_to_the_page_that_does(self):
        panel = self.panel()
        panel.search.setText("clap")
        APP.processEvents()
        shown = sorted(k for k, r in panel.rows.items() if not r.isHidden())
        self.assertEqual(shown, ["CLAP_COUNT", "CLAP_SENSITIVITY", "CLAP_WAKE"])
        waking = [page_id for page_id, _ in admin_panel.PAGES].index("waking")
        self.assertEqual(panel.nav.currentRow(), waking)
        self.assertIn("(3)", panel.nav.item(waking).text())

    def test_clearing_the_search_shows_everything_again(self):
        panel = self.panel()
        panel.search.setText("clap")
        panel.search.setText("")
        self.assertTrue(all(not r.isHidden() for r in panel.rows.values() if not r.setting.advanced))

    def test_a_search_with_no_match_says_so(self):
        panel = self.panel()
        panel.search.setText("zzzzzz")
        APP.processEvents()
        self.assertTrue(all(r.isHidden() for r in panel.rows.values()))

    def test_a_search_finds_advanced_settings_without_ticking_the_box(self):
        panel = self.panel()
        panel.search.setText("mail server")
        shown = [k for k, r in panel.rows.items() if not r.isHidden()]
        self.assertIn("EMAIL_SMTP_HOST", shown)


class ShortcutPageTests(PanelCase):
    def page(self, panel):
        return panel.nav_pages["shortcuts"][1]

    def test_adding_a_shortcut_saves_it_straight_away(self):
        item = {"name": "college portal", "kind": "website", "target": "https://portal.example.edu"}
        with mock.patch.object(admin_panel, "edit_shortcut", return_value=item):
            panel = self.panel()
            self.page(panel).add()
        self.assertEqual(shortcuts.load(self.shortcut_file), [item])
        table = self.page(panel).table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "college portal")
        self.assertEqual(table.item(0, 1).text(), "A website")

    def test_a_second_shortcut_with_the_same_name_is_refused(self):
        item = {"name": "College Portal", "kind": "website", "target": "https://a.example.com"}
        shortcuts.save([{"name": "college portal", "kind": "website", "target": "https://b.example.com"}], self.shortcut_file)
        with mock.patch.object(admin_panel, "edit_shortcut", return_value=item):
            panel = self.panel()
            self.page(panel).add()
        self.assertEqual(len(shortcuts.load(self.shortcut_file)), 1)
        self.assertIn("already a shortcut", self.told[-1][1])

    def test_cancelling_the_editor_changes_nothing(self):
        with mock.patch.object(admin_panel, "edit_shortcut", return_value=None):
            panel = self.panel()
            self.page(panel).add()
        self.assertEqual(shortcuts.load(self.shortcut_file), [])

    def test_changing_and_removing(self):
        shortcuts.save([{"name": "one", "kind": "website", "target": "https://a.example.com"}, {"name": "two", "kind": "website", "target": "https://b.example.com"}], self.shortcut_file)
        changed = {"name": "uno", "kind": "website", "target": "https://c.example.com"}
        with mock.patch.object(admin_panel, "edit_shortcut", return_value=changed):
            panel = self.panel()
            page = self.page(panel)
            page.table.selectRow(0)
            page.change()
            self.assertEqual(shortcuts.load(self.shortcut_file)[0]["name"], "uno")
            page.table.selectRow(1)
            page.remove()
        self.assertEqual([i["name"] for i in shortcuts.load(self.shortcut_file)], ["uno"])
        self.assertIn("two", self.asked[-1][1])

    def test_removing_needs_a_yes_and_a_selection(self):
        shortcuts.save([{"name": "one", "kind": "website", "target": "https://a.example.com"}], self.shortcut_file)
        panel = self.panel()
        page = self.page(panel)
        page.table.clearSelection()
        page.table.setCurrentCell(-1, -1)
        page.remove()
        self.assertIn("Click a shortcut", self.told[-1][1])
        page.table.selectRow(0)
        self.answer = False
        page.remove()
        self.assertEqual(len(shortcuts.load(self.shortcut_file)), 1)

    def test_a_shortcut_that_points_at_nothing_is_marked(self):
        shortcuts.save([{"name": "old", "kind": "folder", "target": str(self.root / "gone")}], self.shortcut_file)
        panel = self.panel()
        self.assertEqual(self.page(panel).table.item(0, 3).text(), "that folder does not exist")

    def test_try_it_opens_the_selected_one_and_reports_a_failure(self):
        shortcuts.save([{"name": "one", "kind": "website", "target": "https://a.example.com"}], self.shortcut_file)
        panel = self.panel()
        page = self.page(panel)
        page.table.selectRow(0)
        buttons = [b for b in page.findChildren(admin_panel.QPushButton) if b.text() == "Try it"]
        with mock.patch.object(shortcuts, "open_it") as opened:
            buttons[0].click()
        opened.assert_called_once()
        with mock.patch.object(shortcuts, "open_it", side_effect=RuntimeError("it broke")):
            buttons[0].click()
        self.assertIn("it broke", self.told[-1][1])


class ContactPageTests(PanelCase):
    def test_adding_a_contact_saves_it_straight_away(self):
        item = {"name": "Ali", "email": "ali@example.com", "phone": "", "note": "brother"}
        with mock.patch.object(admin_panel, "edit_contact", return_value=item):
            panel = self.panel()
            panel.nav_pages["contacts"][1].add()
        self.assertEqual(contacts.load(self.contact_file)[0]["email"], "ali@example.com")
        self.assertEqual(panel.nav_pages["contacts"][1].table.item(0, 3).text(), "brother")


class ItemDialogTests(unittest.TestCase):
    def test_the_shortcut_editor_checks_before_it_accepts(self):
        dialog = admin_widgets.ItemDialog("A shortcut", [("name", "Name", "text", ""), ("kind", "Opens", "choice", [("website", "A website"), ("folder", "A folder")]),
                                                         ("target", "Where", "path", "")], {"kind": "website"}, shortcuts.check)
        dialog.editors["name"].setText("portal")
        dialog.editors["target"].setText("nonsense")
        dialog.accept_item()
        self.assertIsNone(dialog.item)
        self.assertIn("address", dialog.message.text())
        dialog.editors["target"].setText("www.example.com")
        dialog.accept_item()
        self.assertEqual(dialog.item["target"], "https://www.example.com")

    def test_editing_starts_from_the_values_it_is_given(self):
        dialog = admin_widgets.ItemDialog("A contact", [("name", "Name", "text", ""), ("email", "Email", "text", "")], {"name": "Ali", "email": "ali@example.com"}, contacts.check)
        self.assertEqual(dialog.current(), {"name": "Ali", "email": "ali@example.com"})


class PasswordTests(PanelCase):
    def test_the_prompt_lets_the_right_password_in_and_stops_after_three_wrong_ones(self):
        dialog = admin_widgets.PasswordPrompt(check=lambda text: text == "open sesame")
        dialog.field.setText("open sesame")
        dialog.submit()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        tries = admin_widgets.PasswordPrompt(check=lambda text: text == "open sesame")
        for number in range(3):
            tries.field.setText("wrong")
            tries.submit()
        self.assertEqual(tries.result(), QDialog.Rejected)

    def test_the_prompt_counts_the_tries_left_and_ignores_an_empty_box(self):
        dialog = admin_widgets.PasswordPrompt(check=lambda text: False)
        dialog.submit()
        self.assertEqual(dialog.tries, 0)
        dialog.field.setText("x")
        dialog.submit()
        self.assertIn("2 tries left", dialog.message.text())

    def test_changing_the_password_stores_only_a_hash_and_works_at_once(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="plain-one", JARVIS_PASSWORD_HASH=""):
            dialog = admin_widgets.ChangePasswordDialog(env_path=self.root / ".env", require_current=True)
            dialog.current.setText("plain-one")
            dialog.first.setText("a brand new one")
            dialog.second.setText("a brand new one")
            dialog.save()
            self.assertEqual(dialog.result(), QDialog.Accepted)
            text = (self.root / ".env").read_text(encoding="utf-8")
            self.assertNotIn("a brand new one", text)
            self.assertIn("JARVIS_PASSWORD_HASH=pbkdf2_sha256$", text)
            self.assertRegex(text, r"(?m)^JARVIS_PASSWORD=$")
            self.assertTrue(gate.check_password("a brand new one"))                 # the running Jarvis already uses it
            self.assertFalse(gate.check_password("plain-one"))

    def test_the_dialog_refuses_a_wrong_current_password_a_short_one_and_two_that_differ(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="plain-one", JARVIS_PASSWORD_HASH=""):
            dialog = admin_widgets.ChangePasswordDialog(env_path=self.root / ".env", require_current=True)
            dialog.current.setText("wrong")
            dialog.save()
            self.assertIn("current password", dialog.message.text())
            dialog.current.setText("plain-one")
            dialog.first.setText("abc")
            dialog.second.setText("abc")
            dialog.save()
            self.assertIn("at least 4", dialog.message.text())
            dialog.first.setText("abcdef")
            dialog.second.setText("abcxyz")
            dialog.save()
            self.assertIn("different", dialog.message.text())
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertIn("JARVIS_PASSWORD=plain-one", (self.root / ".env").read_text(encoding="utf-8"))

    def test_open_admin_asks_for_the_password_only_when_there_is_one(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="", JARVIS_PASSWORD_HASH=""), mock.patch.object(admin_panel.AdminPanel, "exec_", return_value=0) as opened, \
                mock.patch.object(admin_panel, "PasswordPrompt") as prompt:
            self.assertTrue(admin_panel.open_admin(root=self.root, effects=FakeEffects()))
        opened.assert_called_once()
        prompt.assert_not_called()

    def test_open_admin_stays_shut_when_the_password_is_not_given(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="secret1", JARVIS_PASSWORD_HASH=""), mock.patch.object(admin_panel, "PasswordPrompt") as prompt, \
                mock.patch.object(admin_panel.AdminPanel, "exec_", return_value=0) as opened:
            prompt.return_value.exec_.return_value = QDialog.Rejected
            self.assertFalse(admin_panel.open_admin(root=self.root, effects=FakeEffects()))
        opened.assert_not_called()


class BackupPageTests(PanelCase):
    def test_the_parts_show_what_exists_and_models_start_unticked(self):
        panel = self.panel()
        self.assertTrue(panel.backup_parts["settings"].isChecked())
        self.assertTrue(panel.backup_parts["notes"].isChecked())
        self.assertFalse(panel.backup_parts["shortcuts"].isEnabled())                # nothing there to back up
        self.assertFalse(panel.backup_parts["models"].isEnabled() and panel.backup_parts["models"].isChecked())

    def test_backing_up_makes_a_verified_folder(self):
        drive = self.root / "drive"
        drive.mkdir()
        panel = self.panel()
        panel.backup_target.setText(str(drive))
        panel.back_up()
        self.assertTrue(wait_for(lambda: panel.backup_button.isEnabled()))
        self.assertIn("every file checked", panel.backup_status.text())
        made = [p for p in drive.iterdir() if p.name.startswith("Jarvis-Backup-")]
        self.assertEqual(len(made), 1)
        self.assertEqual(backup_jarvis.verify_backup(made[0]), [])

    def test_it_asks_for_a_folder_that_exists_and_something_to_back_up(self):
        panel = self.panel()
        panel.back_up()
        self.assertIn("folder that exists", self.told[-1][1])
        panel.backup_target.setText(str(self.root))
        for check in panel.backup_parts.values():
            check.setChecked(False)
        panel.back_up()
        self.assertIn("at least one", self.told[-1][1])

    def test_finding_and_restoring_a_backup(self):
        drive = self.root / "drive"
        drive.mkdir()
        made = backup_jarvis.make_backup(drive, root=self.root)
        (self.root / "DataBase" / "Notes" / "n.txt").unlink()
        panel = self.panel()
        with mock.patch.object(backup_jarvis, "find_backups", return_value=[backup_jarvis.Backup(made, "package", None, "my backup")]):
            panel.find_backups()
        self.assertEqual(panel.found.count(), 1)
        panel.found.setCurrentRow(0)
        panel.restore_selected()
        self.assertEqual((self.root / "DataBase" / "Notes" / "n.txt").read_text(), "buy milk")
        self.assertIn("Restored", self.told[-1][1])

    def test_restoring_needs_a_choice_first(self):
        panel = self.panel()
        panel.restore_selected()
        self.assertIn("Look for backups", self.told[-1][1])


class AdvancedPageTests(PanelCase):
    def test_every_line_of_env_is_listed_with_secrets_hidden_and_own_settings_marked(self):
        panel = self.panel()
        rows = {panel.env_table.item(r, 0).text(): (panel.env_table.item(r, 1).text(), panel.env_table.item(r, 2).text()) for r in range(panel.env_table.rowCount())}
        self.assertEqual(rows["USER_NAME"], ("Mr Khan", "Your name"))
        self.assertEqual(rows["RAPIDAPI_KEY"][1], "your own setting")
        self.assertNotIn("abc123", rows["RAPIDAPI_KEY"][0])
        self.assertNotIn("secretkey1234", rows["NASA_API_KEY"][0])
        self.assertNotIn("plain-one", rows["JARVIS_PASSWORD"][0])

    def test_adding_and_removing_a_setting_of_your_own(self):
        panel = self.panel()
        with mock.patch.object(admin_panel.QInputDialog, "getText", side_effect=[("my setting", True), ("hello", True)]):
            panel.add_own_setting()
        self.assertEqual(self.env().get("MY_SETTING"), "hello")
        keys = [panel.env_table.item(r, 0).text() for r in range(panel.env_table.rowCount())]
        panel.env_table.selectRow(keys.index("MY_SETTING"))
        panel.remove_selected_setting()
        self.assertNotIn("MY_SETTING", self.env().values())

    def test_a_bad_name_is_refused(self):
        panel = self.panel()
        with mock.patch.object(admin_panel.QInputDialog, "getText", side_effect=[("1 bad", True), ("x", True)]):
            panel.add_own_setting()
        self.assertEqual(self.told[-1][0], "Not accepted")

    def test_undo_with_nothing_to_undo_says_so(self):
        panel = self.panel()
        panel.undo_last_save()
        self.assertIn("no earlier copy", self.told[-1][1])


class OverviewTests(PanelCase):
    def test_start_over_asks_first_then_opens_the_wizard_in_reset_mode(self):
        panel = self.panel()
        self.answer = False
        with mock.patch.object(admin_panel, "run_in_console") as console:
            panel.start_over()
        console.assert_not_called()
        self.answer = True
        with mock.patch.object(admin_panel, "run_in_console") as console:
            panel.start_over()
        console.assert_called_once_with(self.root, ["setup_jarvis.py", "--mode", "reset"])
        self.assertIn("saves a copy", self.asked[-1][1])

    def test_the_health_table_fills_in_from_the_same_checks_the_wizard_makes(self):
        panel = self.panel()
        self.assertTrue(wait_for(lambda: panel.health_table.rowCount() > 0, 20))
        titles = [panel.health_table.item(r, 1).text() for r in range(panel.health_table.rowCount())]
        for expected in ("The Visual C++ runtime", "Installing the Python packages", "The password"):
            self.assertIn(expected, titles)
        self.assertEqual(panel.check_button.text(), "Check again")

    def test_it_says_where_jarvis_lives_and_how_many_settings_differ(self):
        panel = self.panel()
        self.assertIn(str(self.root), panel.facts_label.text())
        self.assertIn("differ from the usual", panel.facts_label.text())


class MainWindowTests(unittest.TestCase):
    def window(self, **kwargs):
        from gui.session import SessionController
        window = main_window.MainWindow(controller=SessionController(run_session=lambda listen, ask: "sleep"), **kwargs)
        self.addCleanup(window.close)
        return window

    def test_the_admin_button_opens_the_panel(self):
        opened = []
        window = self.window(admin=lambda parent: opened.append(parent))
        window.admin_button.click()
        self.assertEqual(opened, [window])

    def test_saying_open_the_admin_panel_reaches_the_window(self):
        opened = []
        window = self.window(admin=lambda parent: opened.append(parent))
        self.assertTrue(ui_bridge.request("admin"))                    # (what the command does, on the session's thread)
        wait_for(lambda: opened)
        self.assertEqual(opened, [window])

    def test_a_closed_window_no_longer_takes_the_request(self):
        window = self.window(admin=lambda parent: None)
        window.close()
        self.assertFalse(ui_bridge.request("admin"))

    def test_the_request_from_another_thread_is_handled_on_the_window_thread(self):
        seen = []
        window = self.window(admin=lambda parent: seen.append(threading.current_thread().name))
        threading.Thread(target=lambda: ui_bridge.request("admin"), name="session").start()
        wait_for(lambda: seen)
        self.assertEqual(seen, [threading.main_thread().name])
        window.close()

    def test_restarting_starts_a_helper_and_closes_the_window(self):
        window = self.window(admin=lambda parent: None)
        with mock.patch("subprocess.Popen") as popen:
            window.restart_jarvis()
        command = popen.call_args[0][0]
        self.assertEqual(command[1], "-c")
        self.assertTrue(command[-2].endswith("JarvisGUI.py"))
        wait_for(lambda: not window.isVisible(), 2)


if __name__ == "__main__":
    unittest.main()
