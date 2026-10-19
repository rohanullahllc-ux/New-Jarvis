"""Tests for reading and setting the Windows microphone volume:  python -m unittest tests.test_audio_levels -v

PowerShell is never run: subprocess.run is replaced.
"""
import base64
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_levels as A  # noqa: E402
import microphone  # noqa: E402


def powershell(stdout="", code=0, stderr=""):
    return mock.patch("subprocess.run", return_value=SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code))


class StateTests(unittest.TestCase):
    def test_the_volume_and_mute_switch_are_read_from_windows_answer(self):
        with powershell("28|False\n"):
            self.assertEqual(A.state(), (28, False))
        with powershell("100|True"):
            self.assertEqual(A.state(A.OUTPUT), (100, True))

    def test_the_script_is_sent_encoded_so_quotes_cannot_break_it(self):
        with powershell("28|False") as run:
            A.state()
        arguments = run.call_args[0][0]
        self.assertEqual(arguments[:4], ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"])
        script = base64.b64decode(arguments[4]).decode("utf-16-le")
        self.assertIn("AudioInfo", script)
        self.assertIn("[AudioInfo]::State(1)", script)

    def test_setting_the_volume_is_clamped_and_reported_back(self):
        with powershell("80|False") as run:
            self.assertEqual(A.set_volume(250), 80)
        scripts = [base64.b64decode(call[0][0][4]).decode("utf-16-le") for call in run.call_args_list]
        self.assertIn("SetVolume(1, 1.00)", scripts[0])
        with powershell("1|False") as run:
            A.set_volume(-5)
        self.assertIn("SetVolume(1, 0.01)", base64.b64decode(run.call_args_list[0][0][0][4]).decode("utf-16-le"))

    def test_unmuting_asks_windows_to_unmute(self):
        with powershell("") as run:
            A.set_muted(False)
        self.assertIn("SetMute(1, $false)", base64.b64decode(run.call_args[0][0][4]).decode("utf-16-le"))

    def test_trouble_is_an_audio_error_in_plain_words(self):
        with powershell("", code=1, stderr="Exception calling Describe: COM failed\nmore"):
            with self.assertRaises(A.AudioError) as caught:
                A.state()
        self.assertIn("COM failed", str(caught.exception))
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("powershell", 40)):
            with self.assertRaises(A.AudioError):
                A.state()
        with powershell("gibberish"):
            with self.assertRaises(A.AudioError):
                A.state()

    def test_advice_names_the_problem_only_when_there_is_one(self):
        self.assertIn("muted", A.advice(80, True))
        self.assertIn("only 28 percent", A.advice(28, False))
        self.assertEqual(A.advice(80, False), "")
        self.assertEqual(A.advice(A.LOW_VOLUME, False), "")


class StartupWarningTests(unittest.TestCase):
    def setUp(self):
        microphone.last_note = ""
        microphone._volume_checked[0] = False
        self.addCleanup(lambda: (setattr(microphone, "last_note", ""), microphone._volume_checked.__setitem__(0, False)))

    def check(self, state):
        with mock.patch("audio_levels.state", return_value=state) if not isinstance(state, Exception) else mock.patch("audio_levels.state", side_effect=state), \
                mock.patch("builtins.print") as printed:
            microphone._check_windows_volume()
            for thread in threading.enumerate():
                if thread.name == "mic-volume-check":
                    thread.join(5)
        return " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)

    def test_a_turned_down_microphone_is_reported_in_the_log_and_to_the_window(self):
        shown = self.check((28, False))
        self.assertIn("only 28 percent", shown)
        self.assertIn("only 28 percent", microphone.take_note())

    def test_a_muted_microphone_is_reported(self):
        self.assertIn("muted", self.check((90, True)))

    def test_a_fine_microphone_says_nothing_and_a_failure_is_silent(self):
        self.assertEqual(self.check((90, False)).strip(), "")
        microphone._volume_checked[0] = False
        self.assertEqual(self.check(A.AudioError("no")).strip(), "")
        self.assertEqual(microphone.take_note(), "")

    def test_it_looks_only_once_per_run(self):
        self.check((28, False))
        with mock.patch("audio_levels.state", side_effect=AssertionError("looked twice")):
            microphone._check_windows_volume()
            time.sleep(0.1)


class MicrophoneToolTests(unittest.TestCase):
    def test_the_tool_reports_sets_changes_and_unmutes(self):
        from JarvisAdvancedBot.tools import windows
        with mock.patch("audio_levels.state", return_value=(28, True)), mock.patch("audio_levels.set_muted") as unmute, \
                mock.patch("audio_levels.set_volume", return_value=80) as setter:
            report = windows.microphone_level()
            self.assertIn("28 percent, muted", report)
            self.assertIn("muted in Windows", report)
            setter.assert_not_called()
            windows.microphone_level(unmute=True)
            unmute.assert_called_once_with(False)
            self.assertIn("80 percent", windows.microphone_level(percent=80))
            setter.assert_called_with(80)
            windows.microphone_level(change=25)
            setter.assert_called_with(53)                                      # 28 + 25

    def test_a_windows_error_becomes_a_message(self):
        from anthropic.lib.tools import ToolError
        from JarvisAdvancedBot.tools import windows
        with mock.patch("audio_levels.state", side_effect=A.AudioError("Windows would not say")):
            with self.assertRaises(ToolError) as caught:
                windows.microphone_level()
        self.assertIn("Windows would not say", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
