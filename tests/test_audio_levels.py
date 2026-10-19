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


class StartupVolumeTests(unittest.TestCase):
    """At start-up Jarvis puts a muted or very quiet Windows microphone right (MIC_VOLUME percent), or only warns (MIC_VOLUME=0).
    Windows is stood in for here: the real volume is never touched."""

    def setUp(self):
        microphone.last_note = ""
        microphone._volume_checked[0] = False
        self.addCleanup(lambda: (setattr(microphone, "last_note", ""), microphone._volume_checked.__setitem__(0, True),
                                 microphone._volume_done.set()))

    def run_check(self, state, setting=80, new_volume=80, change_fails=False):
        """The start-up check. Returns what it printed and the stand-ins for 'set the volume' and 'unmute'."""
        read = {"side_effect": state} if isinstance(state, Exception) else {"return_value": state}
        change = {"side_effect": A.AudioError("Windows said no")} if change_fails else {"return_value": new_volume}
        with mock.patch.object(microphone, "MIC_VOLUME", setting), mock.patch("audio_levels.state", **read), \
                mock.patch("audio_levels.set_volume", **change) as set_volume, mock.patch("audio_levels.set_muted") as set_muted, \
                mock.patch("builtins.print") as printed:
            microphone.check_windows_volume()
            self.assertTrue(microphone._volume_done.wait(5), "the check never finished")
            for thread in threading.enumerate():
                if thread.name == "mic-volume-check":
                    thread.join(5)
        shown = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        return shown, set_volume, set_muted

    def test_a_very_quiet_microphone_is_raised_to_the_setting_and_the_user_is_told(self):
        shown, set_volume, set_muted = self.run_check((28, False))
        set_volume.assert_called_once_with(80)
        set_muted.assert_not_called()
        self.assertIn("only at 28 percent", shown)
        self.assertIn("set it to 80 percent", shown)
        self.assertNotIn("words go missing", shown)                        # nothing is left to warn about
        self.assertEqual(microphone.take_note(), "")

    def test_a_muted_microphone_is_switched_on_and_its_volume_left_alone(self):
        shown, set_volume, set_muted = self.run_check((70, True))
        set_muted.assert_called_once_with(False)
        set_volume.assert_not_called()
        self.assertIn("muted", shown)
        self.assertIn("switched it on", shown)

    def test_muted_and_quiet_are_both_put_right(self):
        shown, set_volume, set_muted = self.run_check((28, True))
        set_muted.assert_called_once_with(False)
        set_volume.assert_called_once_with(80)
        self.assertIn("muted and only at 28 percent", shown)
        self.assertIn("switched it on and set it to 80 percent", shown)

    def test_a_microphone_that_is_not_too_quiet_is_left_exactly_as_it_is(self):
        for volume in (50, 60, 80, 100):                                   # (someone may have chosen 60 on purpose; none is ever turned down)
            microphone._volume_checked[0] = False
            shown, set_volume, set_muted = self.run_check((volume, False))
            set_volume.assert_not_called()
            set_muted.assert_not_called()
            self.assertEqual(shown.strip(), "", volume)

    def test_with_the_setting_at_zero_windows_is_left_alone_and_the_user_is_only_warned(self):
        shown, set_volume, set_muted = self.run_check((28, False), setting=0)
        set_volume.assert_not_called()
        self.assertIn("only 28 percent", shown)
        self.assertIn("only 28 percent", microphone.take_note())
        microphone._volume_checked[0] = False
        shown, set_volume, set_muted = self.run_check((90, True), setting=0)
        set_muted.assert_not_called()
        self.assertIn("muted", shown)

    def test_a_setting_below_the_warning_level_is_obeyed_and_still_warned_about(self):
        shown, set_volume, _ = self.run_check((30, False), setting=40, new_volume=40)
        set_volume.assert_called_once_with(40)
        self.assertIn("only 40 percent", shown)                            # (that is the user's choice, but it is still low)

    def test_when_windows_refuses_the_change_the_user_is_told_what_to_do_by_hand(self):
        shown, set_volume, _ = self.run_check((28, False), change_fails=True)
        set_volume.assert_called_once_with(80)
        self.assertNotIn("so I", shown)                                    # (nothing was done, so none is claimed)
        self.assertIn("only 28 percent", shown)
        self.assertIn("only 28 percent", microphone.take_note())

    def test_a_failure_to_read_the_volume_is_silent_and_still_ends_the_wait(self):
        shown, set_volume, set_muted = self.run_check(A.AudioError("no"))
        self.assertEqual(shown.strip(), "")
        self.assertEqual(microphone.take_note(), "")
        set_volume.assert_not_called()
        set_muted.assert_not_called()

    def test_it_looks_only_once_per_run(self):
        self.run_check((90, False))
        with mock.patch("audio_levels.state", side_effect=AssertionError("looked twice")):
            microphone.check_windows_volume()
            time.sleep(0.1)

    def test_the_first_listen_can_tell_when_the_check_is_still_running(self):
        release = threading.Event()
        with mock.patch("audio_levels.state", side_effect=lambda *a: (release.wait(5), (90, False))[1]), mock.patch("builtins.print"):
            microphone.check_windows_volume()
            self.assertFalse(microphone._volume_done.is_set())
            release.set()
            self.assertTrue(microphone._volume_done.wait(5))


class SelfCheckTests(unittest.TestCase):
    def test_the_self_check_names_a_command_that_fixes_a_quiet_microphone(self):
        """`python microphone.py` runs without Jarvis, so "say: set the microphone volume" would be no help there."""
        with mock.patch("audio_levels.state", return_value=(28, False)), mock.patch.object(microphone.winmm_mic, "list_devices", return_value=[]), \
                mock.patch.object(microphone, "_load_sounddevice", side_effect=microphone.MicrophoneError("none")), \
                mock.patch.dict(microphone.BACKENDS, clear=True), mock.patch("builtins.print") as printed:
            self.assertFalse(microphone.diagnose(speak_test=False))
        output = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("only 28 percent", output)
        self.assertIn("python audio_levels.py --mic 80", output)


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
