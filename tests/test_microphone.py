"""Regression tests for the voice-input chain.

Each test reproduces a real failure this project has had (or could have), so it cannot
silently come back:  python -m unittest tests.test_microphone -v

Tests marked "hardware" need a working microphone and are skipped without one.
"""
import builtins
import importlib.abc
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech_recognition as sr  # noqa: E402

import microphone  # noqa: E402
import winmm_mic  # noqa: E402

try:
    HAS_MIC = sys.platform == "win32" and bool(winmm_mic.list_devices())
except Exception:
    HAS_MIC = False


def reset():
    """Put the microphone module back to a clean slate between tests (always in voice mode,
    whatever INPUT_MODE the developer's .env happens to say)."""
    microphone.INPUT_MODE = "voice"
    microphone.reset_microphone()
    microphone._sd = None
    microphone._sd_error = None
    microphone.MIC_BACKEND = "auto"
    microphone.MIC_DEVICE = ""
    microphone._typed_hint_shown = False


class DeadBackend:
    """A backend whose microphone opens but never delivers audio (a dead / unplugged device)."""

    backend = "dead"

    def __init__(self, device_index=None, **kwargs):
        self.device_name = "dead mic"
        self.SAMPLE_RATE, self.SAMPLE_WIDTH, self.CHUNK = 16000, 2, 1024
        self.stream = None

    def __enter__(self):
        raise winmm_mic.MicrophoneError("the microphone delivered no audio")

    def __exit__(self, *exc):
        return False


class PyAudioIsGone(unittest.TestCase):
    """PyAudio has no wheel for Python 3.14. Even a broken copy must never be touched."""

    def test_a_broken_pyaudio_is_never_used(self):
        class Poison(types.ModuleType):
            def __getattr__(self, name):
                raise AssertionError(f"PyAudio was used ({name})")

        with mock.patch.dict(sys.modules, {"pyaudio": Poison("pyaudio")}):
            reset()
            self.assertNotIn("pyaudio", [m.__name__ for m in (microphone, winmm_mic)])
            if HAS_MIC:
                microphone._select_backend()
                self.assertIn(microphone._active, microphone.BACKENDS)

    def test_requirements_do_not_ask_for_pyaudio(self):
        lines = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8").splitlines()
        requirements = [line.split("#")[0].strip().lower() for line in lines]          # comments may mention it
        self.assertFalse([line for line in requirements if "pyaudio" in line.replace("pyaudiowpatch", "")], requirements)


@unittest.skipUnless(HAS_MIC, "hardware: needs a microphone")
class BackendsOnRealHardware(unittest.TestCase):
    def setUp(self):
        reset()

    def test_each_backend_delivers_exactly_the_requested_audio(self):
        for name in microphone.BACKENDS:
            with self.subTest(backend=name):
                with microphone._make(name, read_timeout=3) as source:
                    data = source.stream.read(source.CHUNK)
                self.assertEqual(len(data), source.CHUNK * source.SAMPLE_WIDTH)

    def test_open_and_close_many_times_leaks_nothing(self):
        import threading
        before = threading.active_count()
        for _ in range(10):
            with microphone._make("winmm", read_timeout=3) as source:
                source.stream.read(source.CHUNK)
        self.assertLessEqual(threading.active_count(), before)

    def test_close_is_safe_twice(self):
        stream = winmm_mic.WinMMStream(winmm_mic.WAVE_MAPPER, 16000, 1024, 3)
        stream.close()
        stream.close()

    def test_unknown_device_gives_a_clear_error(self):
        with self.assertRaises(winmm_mic.MicrophoneError) as ctx:
            winmm_mic.resolve_device("no-such-microphone")
        self.assertIn("available", str(ctx.exception))

    def test_device_can_be_chosen_by_name_fragment(self):
        index, name = winmm_mic.list_devices()[0]
        self.assertEqual(winmm_mic.resolve_device(name[:6])[0], index)


class FailoverAndFallback(unittest.TestCase):
    def setUp(self):
        reset()

    @unittest.skipUnless(HAS_MIC, "hardware: needs a microphone")
    def test_missing_sounddevice_falls_back_to_winmm(self):
        with mock.patch.dict(sys.modules, {"sounddevice": None}):
            microphone._select_backend()
        self.assertEqual(microphone._active, "winmm")

    @unittest.skipUnless(HAS_MIC, "hardware: needs a microphone")
    def test_a_hung_sounddevice_import_is_abandoned_by_the_watchdog(self):
        """The one hang this project hit: PortAudio's start-up scan blocking the importing thread."""
        class Hang(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "sounddevice":
                    time.sleep(3)           # simulate a driver that never answers
                return None

        saved = sys.modules.pop("sounddevice", None)
        finder = Hang()
        sys.meta_path.insert(0, finder)
        try:
            started = time.time()
            with self.assertRaises(winmm_mic.MicrophoneError) as ctx:
                microphone._load_sounddevice(timeout=0.5)
            self.assertLess(time.time() - started, 2.0, "the watchdog must not wait for the hung import")
            self.assertIn("did not start", str(ctx.exception))
            microphone._select_backend()      # and the program still gets a working microphone
            self.assertEqual(microphone._active, "winmm")
            time.sleep(3)                     # let the abandoned thread finish before cleaning up
        finally:
            sys.meta_path.remove(finder)
            if saved is not None:
                sys.modules["sounddevice"] = saved

    @unittest.skipUnless(HAS_MIC, "hardware: needs a microphone")
    def test_a_microphone_that_dies_mid_session_fails_over_and_keeps_listening(self):
        class DiesOnRead(microphone.WinMMMicrophone):
            def __enter__(self):
                super().__enter__()
                self.stream.read = mock.Mock(side_effect=winmm_mic.MicrophoneError("no audio"))
                return self

        with mock.patch.dict(microphone.BACKENDS, {"sounddevice": DiesOnRead}):
            microphone._active = "sounddevice"
            microphone._recognizer = sr.Recognizer()
            result = microphone.listen(timeout=1, phrase_time_limit=1)
        self.assertIsInstance(result, str)                 # whatever was heard (usually nothing): it did not crash or type
        self.assertEqual(microphone._active, "winmm")
        self.assertIn("sounddevice", microphone._failed)
        self.assertFalse(microphone._text_mode)

    def test_total_failure_switches_to_typed_input_with_advice(self):
        with mock.patch.dict(microphone.BACKENDS, {"sounddevice": DeadBackend, "winmm": DeadBackend}), \
                mock.patch.object(builtins, "input", return_value="Hey Jarvis"), \
                mock.patch.object(microphone, "_typed_hint_shown", True), \
                mock.patch("builtins.print") as printed:
            result = microphone.listen()
        self.assertEqual(result, "Hey Jarvis")                 # typed words keep their capitals
        self.assertTrue(microphone._text_mode)
        output = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("python microphone.py", output)      # the user is told how to diagnose it

    def test_voice_only_listening_never_falls_back_to_the_keyboard(self):
        """The GUI has no console: a dead microphone must be an error it can show, not input()."""
        with mock.patch.dict(microphone.BACKENDS, {"sounddevice": DeadBackend, "winmm": DeadBackend}),                 mock.patch.object(builtins, "input", side_effect=AssertionError("asked the keyboard")),                 mock.patch.object(microphone, "_type_prompt", side_effect=AssertionError("asked the keyboard")),                 mock.patch("builtins.print"):
            with self.assertRaises(microphone.MicrophoneError) as caught:
                microphone.listen_voice()
        self.assertIn("microphone", str(caught.exception))
        self.assertFalse(microphone._text_mode)

    def test_voice_only_listening_works_even_when_typed_mode_is_on(self):
        """The GUI's push-to-talk button must still hear you when INPUT_MODE=text."""
        with mock.patch.object(microphone, "_text_mode", True),                 mock.patch.object(microphone, "_hear", return_value="open chrome") as hear:
            self.assertEqual(microphone.listen_voice(timeout=3), "open chrome")
        hear.assert_called_once_with(microphone.LANGUAGE, 3, 8)

    def test_voice_only_listening_reports_silence_as_an_empty_string(self):
        with mock.patch.object(microphone, "_hear", return_value=None):
            self.assertEqual(microphone.listen_voice(), "")

    def test_text_mode_never_touches_audio_hardware(self):
        with mock.patch.object(microphone, "_text_mode", True), \
                mock.patch.object(microphone, "_typed_hint_shown", True), \
                mock.patch.object(builtins, "input", return_value="  Time  "), \
                mock.patch.object(microphone, "_select_backend", side_effect=AssertionError("touched audio")):
            self.assertEqual(microphone.listen(), "Time")


class PauseSetting(unittest.TestCase):
    """A pause to think must not end the sentence: "can you tell me the square root of ... 6000" was cut after "of"."""

    def setUp(self):
        reset()
        self.addCleanup(reset)

    def test_the_recogniser_waits_as_long_as_the_setting_says_before_calling_it_the_end(self):
        class Quiet(DeadBackend):
            def __enter__(self):
                return self

        recognizer = mock.Mock()
        with mock.patch.object(microphone.sr, "Recognizer", return_value=recognizer), \
                mock.patch.object(microphone, "Microphone", Quiet), mock.patch.object(microphone, "MIC_PAUSE", 2.5), \
                mock.patch("builtins.print"):
            self.assertTrue(microphone._ensure_ready())
        self.assertEqual(recognizer.pause_threshold, 2.5)

    def test_the_default_is_longer_than_the_one_second_that_used_to_cut_sentences_off(self):
        self.assertGreater(microphone.MIC_PAUSE, 1.0)

    def test_the_setting_reads_fractions_and_ignores_nonsense(self):
        import config
        with mock.patch.dict("os.environ", {"JARVIS_TEST_PAUSE": "1.75", "JARVIS_TEST_BAD": "slow"}):
            self.assertEqual(config.decimal("JARVIS_TEST_PAUSE", 1.3), 1.75)
            self.assertEqual(config.decimal("JARVIS_TEST_BAD", 1.3), 1.3)
            self.assertEqual(config.decimal("JARVIS_TEST_MISSING", 1.3), 1.3)


if __name__ == "__main__":
    unittest.main()
