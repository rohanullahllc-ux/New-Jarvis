"""Tests for the Qt window, the unlock dialog and the animated pictures:  python -m unittest tests.test_gui -v

They run on Qt's invisible "offscreen" display, so no window ever appears, and the assistant behind
the window is a fake session.
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtCore import Qt, QTimer  # noqa: E402
from PyQt5.QtGui import QImage  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

import config  # noqa: E402
import gate  # noqa: E402
import speech  # noqa: E402
from gui import main_window, theme  # noqa: E402
from gui.login_dialog import LoginDialog  # noqa: E402
from gui.session import SessionController  # noqa: E402
from gui.sprites import RESOURCES, SpritePlayer, load_meta  # noqa: E402

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(theme.STYLESHEET)


def wait_for(condition, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        APP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def echo_session(listen, ask):
    from MainCode import SessionStopped
    try:
        while True:
            command = listen()
            if command == "ask me":
                speech.Speak(f"you said {ask('Which one?')}")
                continue
            if command == "stream":
                speech.SpeakStream(["First part.", "Second part."])
                continue
            speech.Speak(f"echo {command}")
            if command in ("sleep", "quit"):
                return command
    except SessionStopped:
        return "quit"


class SpriteTests(unittest.TestCase):
    def test_the_sheets_match_what_their_description_says(self):
        for name, meta in load_meta().items():
            sheet = QImage(str(RESOURCES / meta["file"]))
            width, height = meta["size"]
            rows = -(-meta["frames"] // meta["columns"])
            self.assertEqual((sheet.width(), sheet.height()), (meta["columns"] * width, rows * height), name)

    def test_the_animation_loops_and_draws(self):
        player = SpritePlayer("ring", animate=False)
        player.resize(120, 120)
        first = player.grab().toImage()
        for _ in range(player.frames):
            player.advance()
        self.assertEqual(player.frame, 0)                              # a full loop returns to the start
        player.advance()
        self.assertNotEqual(player.grab().toImage(), first)            # a later frame looks different
        self.assertGreater(len({first.pixel(x, 60) for x in range(0, 120, 4)}), 3)    # something was actually painted

    def test_hidden_or_still_players_do_not_use_the_cpu(self):
        player = SpritePlayer("earth", animate=True)
        player.show()
        self.assertTrue(player.is_animating())
        player.hide()
        self.assertFalse(player.is_animating())
        still = SpritePlayer("earth", animate=False)
        still.show()
        self.assertFalse(still.is_animating())
        still.set_animated(True)
        self.assertTrue(still.is_animating())
        still.set_animated(False)
        self.assertFalse(still.is_animating())

    def test_the_picture_keeps_its_proportions(self):
        player = SpritePlayer("hero", animate=False)
        player.resize(960, 300)                                         # much wider than the 480x300 picture
        image = player.grab().toImage()
        self.assertEqual(image.pixelColor(2, 150).name(), image.pixelColor(10, 20).name())    # the empty sides stay plain


class LoginDialogTests(unittest.TestCase):
    def setUp(self):
        patchers = [mock.patch.multiple(config, JARVIS_PASSWORD="open sesame", JARVIS_PASSWORD_HASH="", FACE_CHECK=False),
                    mock.patch("gui.login_dialog.QTimer.singleShot", side_effect=lambda ms, call: call())]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def dialog(self):
        dialog = LoginDialog()
        self.addCleanup(dialog.close)
        dialog.show()
        return dialog

    def type(self, dialog, text):
        dialog.password.setText(text)
        dialog.unlock_button.click()

    def test_the_right_password_unlocks(self):
        dialog = self.dialog()
        self.type(dialog, "open sesame")
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertIsNone(dialog.face_confirmed)

    def test_three_wrong_passwords_close_the_dialog_and_say_how_many_tries_are_left(self):
        dialog = self.dialog()
        self.type(dialog, "nope")
        self.assertIn("2 tries left", dialog.message.text())
        self.assertEqual(dialog.password.text(), "")                    # the wrong guess is wiped
        self.type(dialog, "still nope")
        self.assertIn("1 try left", dialog.message.text())
        self.type(dialog, "nope again")
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertFalse(dialog.unlock_button.isEnabled())

    def test_a_right_password_after_a_wrong_one_still_works(self):
        dialog = self.dialog()
        self.type(dialog, "nope")
        self.type(dialog, "open sesame")
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_cancel_closes_without_unlocking(self):
        dialog = self.dialog()
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), QDialog.Rejected)

    def test_nobody_gets_in_when_no_password_is_configured(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="", JARVIS_PASSWORD_HASH=""):
            dialog = self.dialog()
        self.assertFalse(dialog.unlock_button.isEnabled())
        self.assertIn("No unlock password is set", dialog.message.text())
        dialog.unlock_button.click()
        QTest.keyClicks(dialog.password, "anything")
        QTest.keyClick(dialog.password, Qt.Key_Return)
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_a_hashed_password_works_like_a_plain_one(self):
        with mock.patch.multiple(config, JARVIS_PASSWORD="", JARVIS_PASSWORD_HASH=gate.hash_password("s3cret", iterations=1000)):
            dialog = self.dialog()
            self.type(dialog, "wrong")
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
            self.type(dialog, "s3cret")
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_the_camera_is_consulted_after_the_password_but_never_blocks_entry(self):
        for seen, expected in ((True, True), (False, False)):
            with self.subTest(seen=seen), mock.patch.object(config, "FACE_CHECK", True), \
                    mock.patch.object(gate, "face_check", return_value=seen) as camera:
                dialog = self.dialog()
                camera.assert_not_called()                              # not before the password is right
                self.type(dialog, "open sesame")
                self.assertTrue(wait_for(lambda: dialog.result() == QDialog.Accepted))
                camera.assert_called_once()
                self.assertEqual(dialog.face_confirmed, expected)

    def test_a_camera_that_crashes_still_lets_a_correct_password_in(self):
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", side_effect=RuntimeError("no camera")):
            dialog = self.dialog()
            self.type(dialog, "open sesame")
            self.assertTrue(wait_for(lambda: dialog.result() == QDialog.Accepted))
        self.assertIs(dialog.face_confirmed, False)

    def test_the_camera_can_be_skipped(self):
        release = []
        with mock.patch.object(config, "FACE_CHECK", True), \
                mock.patch.object(gate, "face_check", side_effect=lambda cancelled=None: (time.sleep(0.5), release.append(1), False)[2]):
            dialog = self.dialog()
            self.type(dialog, "open sesame")
            self.assertFalse(dialog.skip_button.isHidden())
            dialog.skip_button.click()
            self.assertEqual(dialog.result(), QDialog.Accepted)
            wait_for(lambda: release)                                   # the late camera result must not break anything
            APP.processEvents()


class LoginDialogKeyboardTests(unittest.TestCase):
    """People press Enter and Escape. These use real key presses and look at the FIRST result the dialog reports:
    Enter used to press Cancel (the dialog's default button), and a late accept from the camera step hid that."""

    PASSWORD = "open sesame"

    def setUp(self):
        for patcher in (mock.patch.multiple(config, JARVIS_PASSWORD=self.PASSWORD, JARVIS_PASSWORD_HASH="", FACE_CHECK=False),
                        mock.patch("gui.login_dialog.QTimer.singleShot", side_effect=lambda ms, call: call())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def open(self):
        dialog = LoginDialog()
        self.addCleanup(dialog.close)
        dialog.outcomes = []
        dialog.finished.connect(dialog.outcomes.append)
        dialog.show()
        dialog.password.setFocus()
        return dialog

    def type_password(self, dialog, text=PASSWORD):
        QTest.keyClicks(dialog.password, text)

    def press(self, widget, key):
        QTest.keyClick(widget, key)
        APP.processEvents()

    def slow_camera(self, seen=True):
        """A camera check that waits until told to finish (or until the dialog asks it to stop)."""
        release, calls = threading.Event(), []

        def camera(cancelled=None):
            calls.append(cancelled)
            deadline = time.time() + 10
            while not release.is_set() and time.time() < deadline and not (cancelled and cancelled()):
                time.sleep(0.01)
            return seen

        self.addCleanup(release.set)
        return camera, release, calls

    def test_enter_is_unlock_not_cancel(self):
        dialog = self.open()
        self.assertTrue(dialog.unlock_button.isDefault())
        self.assertFalse(dialog.cancel_button.autoDefault())
        self.assertFalse(dialog.skip_button.autoDefault())

    def test_the_enter_key_unlocks_with_the_right_password(self):
        dialog = self.open()
        self.type_password(dialog)
        self.press(dialog.password, Qt.Key_Return)
        self.assertEqual(dialog.outcomes, [QDialog.Accepted])

    def test_the_enter_key_on_the_numeric_keypad_works_too(self):
        dialog = self.open()
        self.type_password(dialog)
        self.press(dialog.password, Qt.Key_Enter)
        self.assertEqual(dialog.outcomes, [QDialog.Accepted])

    def test_enter_with_the_camera_step_on_unlocks_and_never_cancels(self):
        """The reported bug: correct password, Enter, the camera recognised the face, and still nothing started."""
        camera, release, calls = self.slow_camera(seen=True)
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", camera):
            dialog = self.open()
            self.type_password(dialog)
            self.press(dialog.password, Qt.Key_Return)
            self.assertEqual(dialog.outcomes, [], "the dialog closed before the camera had even finished")
            release.set()
            self.assertTrue(wait_for(lambda: dialog.outcomes))
        self.assertEqual(dialog.outcomes, [QDialog.Accepted])
        self.assertEqual(len(calls), 1)
        self.assertIs(dialog.face_confirmed, True)

    def test_a_wrong_password_with_enter_costs_one_try_not_two(self):
        dialog = self.open()
        self.type_password(dialog, "nope")
        self.press(dialog.password, Qt.Key_Return)
        self.assertIn("2 tries left", dialog.message.text())
        self.assertEqual(dialog.outcomes, [])                           # still open
        self.press(dialog.password, Qt.Key_Return)                      # Enter on the emptied box
        self.assertIn("2 tries left", dialog.message.text())            # costs nothing

    def test_enter_on_an_empty_box_is_not_a_try(self):
        dialog = self.open()
        for _ in range(5):
            self.press(dialog.password, Qt.Key_Return)
        self.type_password(dialog, "nope")
        self.press(dialog.password, Qt.Key_Return)
        self.assertIn("2 tries left", dialog.message.text())
        self.assertEqual(dialog.outcomes, [])

    def test_three_wrong_passwords_with_enter_close_it_once(self):
        dialog = self.open()
        for guess in ("one", "two", "three"):
            self.type_password(dialog, guess)
            self.press(dialog.password, Qt.Key_Return)
        self.assertEqual(dialog.outcomes, [QDialog.Rejected])

    def test_escape_before_the_password_is_right_cancels(self):
        dialog = self.open()
        self.press(dialog, Qt.Key_Escape)
        self.assertEqual(dialog.outcomes, [QDialog.Rejected])

    def test_escape_during_the_camera_step_skips_the_camera_instead_of_throwing_the_unlock_away(self):
        camera, release, calls = self.slow_camera()
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", camera):
            dialog = self.open()
            self.type_password(dialog)
            self.press(dialog.password, Qt.Key_Return)
            self.assertFalse(dialog.skip_button.isHidden())
            self.press(dialog, Qt.Key_Escape)
            self.assertEqual(dialog.outcomes, [QDialog.Accepted])
            release.set()
            time.sleep(0.2)
            APP.processEvents()
        self.assertEqual(dialog.outcomes, [QDialog.Accepted])           # the late camera result changes nothing

    def test_enter_pressed_again_during_the_camera_step_does_not_cancel_anything(self):
        camera, release, calls = self.slow_camera()
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", camera):
            dialog = self.open()
            self.type_password(dialog)
            self.press(dialog.password, Qt.Key_Return)
            for _ in range(3):
                self.press(dialog, Qt.Key_Return)
                self.press(dialog.skip_button, Qt.Key_Return)
            self.assertEqual(dialog.outcomes, [])                       # still waiting for the camera
            release.set()
            self.assertTrue(wait_for(lambda: dialog.outcomes))
        self.assertEqual(dialog.outcomes, [QDialog.Accepted])

    def test_nothing_is_left_to_cancel_once_the_password_was_right(self):
        camera, release, calls = self.slow_camera()
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", camera):
            dialog = self.open()
            self.type_password(dialog)
            self.press(dialog.password, Qt.Key_Return)
            self.assertTrue(dialog.cancel_button.isHidden())
            self.assertFalse(dialog.skip_button.isHidden())

    def test_closing_the_dialog_tells_the_camera_to_stop(self):
        camera, release, calls = self.slow_camera()
        with mock.patch.object(config, "FACE_CHECK", True), mock.patch.object(gate, "face_check", camera):
            dialog = self.open()
            self.type_password(dialog)
            self.press(dialog.password, Qt.Key_Return)
            self.assertTrue(wait_for(lambda: calls))
            cancelled = calls[0]
            self.assertFalse(cancelled())
            self.press(dialog, Qt.Key_Escape)
            self.assertTrue(cancelled())                                # the camera loop sees this and lets go of the webcam

    def test_the_first_result_wins(self):
        dialog = self.open()
        dialog.reject()
        dialog.accept()
        self.assertEqual(dialog.outcomes, [QDialog.Rejected])
        self.assertEqual(dialog.result(), QDialog.Rejected)


class FakeDialog:
    Accepted, Rejected = QDialog.Accepted, QDialog.Rejected

    def __init__(self, result):
        self.result = result

    def exec_(self):
        return self.result


class WindowCase(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(speech, "TTS_ENABLED", False), mock.patch.object(sys, "stdout", mock.MagicMock()),
                        mock.patch.object(config, "INPUT_MODE", "text"), mock.patch.object(config, "GUI_ANIMATIONS", False),
                        mock.patch("webbrowser.open")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.controller = SessionController(run_session=echo_session, listen_voice=lambda timeout, limit: "")
        self.window = main_window.MainWindow(controller=self.controller, login=lambda parent: FakeDialog(QDialog.Accepted))
        self.addCleanup(self.close)
        self.window.show()

    def close(self):
        self.controller.stop()
        if self.controller._thread:
            self.controller._thread.join(5)
        self.window.close()

    def chat(self):
        return self.window.chat.toPlainText()

    def unlock(self):
        self.window.start_button.click()
        self.assertTrue(wait_for(lambda: self.controller.state == "ready" and "READY" in self.window.pill.text()))


class WindowTests(WindowCase):
    def test_it_starts_locked_and_nothing_can_be_sent(self):
        self.assertIn("LOCKED", self.window.pill.text())
        self.assertTrue(self.window.start_button.isEnabled())
        for widget in (self.window.input, self.window.send_button, self.window.mic_button, self.window.lock_button,
                       self.window.hands_free_button, self.window.new_chat_button):
            self.assertFalse(widget.isEnabled())
        self.assertEqual(self.window.pages.currentIndex(), 0)

    def test_a_refused_unlock_starts_nothing(self):
        window = main_window.MainWindow(controller=self.controller, login=lambda parent: FakeDialog(QDialog.Rejected))
        self.addCleanup(window.close)
        window.start_button.click()
        self.assertFalse(self.controller.running)
        self.assertEqual(window.status.text(), "Not unlocked.")
        self.assertEqual(window.pages.currentIndex(), 0)

    def test_the_password_dialog_is_shown_before_a_session_can_start(self):
        shown = []

        def login(parent):
            shown.append(self.controller.running)
            return FakeDialog(QDialog.Accepted)

        window = main_window.MainWindow(controller=self.controller, login=login)
        self.addCleanup(window.close)
        window.start_button.click()
        self.assertEqual(shown, [False])                                # asked first, while nothing was running yet

    def test_typing_the_password_and_pressing_enter_starts_the_session(self):
        """The reported bug end to end: START, password, Enter... and the window stayed locked."""
        camera = mock.patch.object(gate, "face_check", lambda cancelled=None: (time.sleep(0.2), True)[1])
        settings = mock.patch.multiple(config, JARVIS_PASSWORD="open sesame", JARVIS_PASSWORD_HASH="", FACE_CHECK=True)
        window = main_window.MainWindow(controller=self.controller)               # the REAL unlock dialog
        self.addCleanup(window.close)

        def type_it_in():
            dialog = QApplication.activeModalWidget()
            QTest.keyClicks(dialog.password, "open sesame")
            QTest.keyClick(dialog.password, Qt.Key_Return)

        with camera, settings:
            QTimer.singleShot(100, type_it_in)
            window.start_button.click()                                           # blocks until the dialog closes
        self.assertTrue(self.controller.running)
        self.assertEqual(window.pages.currentIndex(), 1)
        self.assertNotEqual(window.status.text(), "Not unlocked.")

    def test_after_unlocking_commands_are_typed_and_answered(self):
        self.unlock()
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertTrue(self.window.input.isEnabled())
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.input.setText("hello there")
        self.window.input.returnPressed.emit()
        self.assertTrue(wait_for(lambda: "echo hello there" in self.chat()))
        self.assertIn("YOU", self.chat())
        self.assertEqual(self.window.input.text(), "")

    def test_a_reply_that_arrives_in_pieces_is_shown_as_one_message(self):
        self.unlock()
        self.window.input.setText("stream")
        self.window.send_button.click()
        self.assertTrue(wait_for(lambda: "First part. Second part." in self.chat()))
        self.assertEqual(self.chat().count("JARVIS"), 1)

    def test_new_chat_clears_the_conversation_and_tells_the_session(self):
        self.unlock()
        self.assertTrue(self.window.new_chat_button.isEnabled())
        self.window.input.setText("first topic")
        self.window.send_button.click()
        self.assertTrue(wait_for(lambda: "echo first topic" in self.chat()))
        self.window.new_chat_button.click()
        self.assertTrue(wait_for(lambda: "echo new chat" in self.chat()))
        self.assertNotIn("first topic", self.chat())

    def test_new_chat_does_nothing_while_locked(self):
        self.window.new_chat_button.click()                                # disabled, so this click is ignored
        self.assertFalse(self.controller.running)
        self.assertEqual(self.chat(), "")

    def test_follow_up_questions_appear_and_the_next_message_answers_them(self):
        self.unlock()
        self.window.input.setText("ask me")
        self.window.send_button.click()
        self.assertTrue(wait_for(lambda: "Which one?" in self.chat()))
        self.window.input.setText("the red one")
        self.window.send_button.click()
        self.assertTrue(wait_for(lambda: "you said the red one" in self.chat()))

    def test_sleep_locks_the_window_again(self):
        self.unlock()
        self.window.lock_button.click()
        self.assertTrue(wait_for(lambda: "LOCKED" in self.window.pill.text() and "asleep" in self.chat()))
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertEqual(self.window.start_button.text(), "START")
        self.assertFalse(self.window.input.isEnabled())
        self.assertTrue(self.window.isVisible())

    def test_it_can_be_woken_again_after_sleeping(self):
        self.unlock()
        self.window.lock_button.click()
        wait_for(lambda: "LOCKED" in self.window.pill.text())
        self.controller._thread.join(5)
        self.unlock()
        self.assertIn("Session started", self.chat())

    def test_quit_closes_the_window(self):
        self.unlock()
        self.window.input.setText("quit")
        self.window.send_button.click()
        self.assertTrue(wait_for(lambda: not self.window.isVisible()))

    def test_closing_the_window_stops_the_session(self):
        self.unlock()
        self.window.close()
        self.assertTrue(wait_for(lambda: not self.controller.running))

    def test_what_is_said_is_shown_as_plain_text_never_as_markup(self):
        self.window._add("JARVIS", "<b>bold</b> & <script>x</script>\nnext line", theme.ACCENT)
        text = self.chat()
        self.assertIn("<b>bold</b> & <script>x</script>", text)
        self.assertIn("next line", text)

    def test_problems_are_shown_in_the_status_line_and_the_conversation(self):
        self.controller.problem.emit("I can't use the microphone: no input device")
        self.assertTrue(wait_for(lambda: "no input device" in self.window.status.text()))
        self.assertIn("no input device", self.chat())

    def test_the_status_pill_follows_the_session(self):
        for state, word in (("starting", "STARTING"), ("ready", "READY"), ("listening", "LISTENING"),
                            ("working", "WORKING"), ("locked", "LOCKED")):
            self.window._on_state(state)
            self.assertIn(word, self.window.pill.text())

    def test_the_microphone_button_asks_for_one_spoken_command(self):
        with mock.patch.object(self.controller, "talk") as talk:
            self.window._on_state("ready")
            self.window.mic_button.click()
        talk.assert_called_once()

    def test_the_hands_free_switch_drives_the_session_and_follows_it(self):
        self.window._on_state("ready")
        self.window.hands_free_button.click()
        self.assertTrue(self.controller.hands_free)
        self.assertEqual(self.window.system_values["Input"].text(), "Hands-free voice")
        self.controller.set_hands_free(False)                           # e.g. the microphone failed
        self.assertFalse(self.window.hands_free_button.isChecked())
        self.assertEqual(self.window.system_values["Input"].text(), "Typed, or push to talk")

    def test_voice_mode_starts_hands_free(self):
        with mock.patch.object(config, "INPUT_MODE", "voice"):
            self.unlock()
        self.assertTrue(wait_for(lambda: self.controller.hands_free))

    def test_the_log_shows_what_the_session_printed(self):
        self.assertTrue(self.window.log_view.isHidden())
        self.window.log_button.click()
        self.assertFalse(self.window.log_view.isHidden())
        self.controller.log.emit(": Brain: free local commands")
        self.assertTrue(wait_for(lambda: "free local commands" in self.window.log_view.toPlainText()))

    def test_quick_links_open_their_websites(self):
        with mock.patch("webbrowser.open") as opened:
            self.window.link_buttons["YouTube"].click()
            self.window.link_buttons["Maps"].click()
        self.assertEqual([call.args[0] for call in opened.call_args_list], ["https://www.youtube.com", "https://maps.google.com"])

    def test_every_link_is_https(self):
        self.assertEqual(len(self.window.link_buttons), len(main_window.QUICK_LINKS))
        self.assertTrue(all(url.startswith("https://") for _, url in main_window.QUICK_LINKS))

    def test_the_tool_buttons_open_jarvis_own_windows(self):
        with mock.patch("gui.utils.launcher.launch") as launch:
            self.window.utility_buttons["calculator"].click()
            self.window.utility_buttons["currency_converter"].click()
        self.assertEqual([call.args[0] for call in launch.call_args_list], ["calculator", "currency_converter"])

    def test_a_missing_tool_window_is_reported_not_crashed(self):
        with mock.patch("gui.utils.launcher.launch", side_effect=FileNotFoundError("The calendar window isn't installed.")):
            self.window.utility_buttons["calendar"].click()
        self.assertIn("isn't installed", self.window.status.text())

    def test_the_theme_music_can_be_played_stopped_and_reports_failure(self):
        music = mock.Mock()
        with mock.patch.dict(sys.modules, {"sound_player": mock.Mock(playsound=music), "pygame": mock.Mock()}):
            self.window.music_button.click()
            music.assert_called_once_with(main_window.MUSIC, block=False)
            self.assertIn("Stop", self.window.music_button.text())
            self.window.music_button.click()
            self.assertIn("Play", self.window.music_button.text())
        with mock.patch.dict(sys.modules, {"sound_player": mock.Mock(playsound=mock.Mock(side_effect=OSError("no sound device")))}):
            self.window.music_button.click()
        self.assertIn("no sound device", self.window.status.text())
        self.assertFalse(self.window.music_button.isChecked())

    def test_the_system_panel_describes_this_setup(self):
        with mock.patch.multiple(config, ANTHROPIC_API_KEY="", TTS_ENABLED=False, USER_NAME="Mr Khan"):
            self.window._refresh_system()
        values = {name: label.text() for name, label in self.window.system_values.items()}
        self.assertEqual(values, {"Brain": "Free local commands", "Input": "Typed, or push to talk", "Voice": "Off (text only)",
                                  "User": "Mr Khan"})
        with mock.patch.object(config, "ANTHROPIC_API_KEY", "key"):
            self.window._refresh_system()
        self.assertEqual(self.window.system_values["Brain"].text(), "Claude, with tools")

    def test_the_clock_shows_the_time(self):
        self.window._tick()
        self.assertRegex(self.window.clock.text(), r"^\d\d:\d\d:\d\d$")
        self.assertRegex(self.window.date.text(), r"\d{4}$")

    def test_animations_can_be_switched_off(self):
        self.assertFalse(self.window.ring.is_animating())
        self.assertFalse(self.window.earth.is_animating())
        with mock.patch.object(config, "GUI_ANIMATIONS", True):
            self.window._on_state("ready")
        self.assertTrue(self.window.ring.is_animating())

    def test_the_window_draws_something_in_every_state(self):
        for state in ("locked", "ready"):
            self.window._on_state(state)
            image = self.window.grab().toImage()
            self.assertGreater(image.width(), 900)
            colours = {image.pixel(x, y) for x in range(0, image.width(), 40) for y in range(0, image.height(), 40)}
            self.assertGreater(len(colours), 5)


if __name__ == "__main__":
    unittest.main()
