"""Tests for speech.py:  python -m unittest tests.test_speech -v"""
import io
import sys
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech  # noqa: E402


class FakeEngine:
    created = 0

    def __init__(self, *args, **kwargs):
        type(self).created += 1
        self.said, self.props = [], {}

    def getProperty(self, name):
        return [mock.Mock(id="voice-1", name="Voice One"), mock.Mock(id="voice-2", name="Voice Two")]

    def setProperty(self, name, value):
        self.props[name] = value

    def say(self, text):
        self.said.append(text)

    def runAndWait(self):
        pass


class SpeakTests(unittest.TestCase):
    def setUp(self):
        speech._local = threading.local()
        speech._listeners.clear()
        FakeEngine.created = 0

    def speak(self, text, enabled=True):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", enabled), \
                mock.patch("pyttsx3.engine.Engine", FakeEngine), redirect_stdout(out):
            speech.Speak(text)
        return out.getvalue()

    def test_text_is_always_printed(self):
        self.assertIn("A.I : Hello sir", self.speak("Hello sir"))

    def test_voice_off_never_creates_a_speech_engine(self):
        self.speak("Hello", enabled=False)
        self.assertEqual(FakeEngine.created, 0)

    def test_empty_text_is_ignored(self):
        self.assertEqual(self.speak("   ").strip(), "")
        self.assertEqual(FakeEngine.created, 0)

    def test_long_sentences_are_spoken_faster_than_short_ones(self):
        self.speak("Hi")
        engine = speech._local.engine
        self.assertEqual(engine.props["rate"], 170)
        self.speak("This is a much longer sentence that goes well past thirty characters.")
        self.assertEqual(engine.props["rate"], 200)
        self.assertEqual(engine.said[0], "Hi")

    def test_the_engine_is_created_once_per_thread_and_reused(self):
        self.speak("one")
        self.speak("two")
        self.assertEqual(FakeEngine.created, 1)

    def test_each_thread_gets_its_own_engine(self):
        engines = []

        def work():
            self.speak("from a worker thread")
            engines.append(speech._local.engine)

        self.speak("from the main thread")
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertEqual(FakeEngine.created, 2)
        self.assertIsNot(engines[0], speech._local.engine)

    def test_a_broken_voice_does_not_crash_and_is_retried_fresh_next_time(self):
        class Broken(FakeEngine):
            def runAndWait(self):
                raise RuntimeError("SAPI exploded")

        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", True), mock.patch("pyttsx3.engine.Engine", Broken), \
                redirect_stdout(out):
            speech.Speak("still shown")                    # must not raise
        self.assertIn("still shown", out.getvalue())
        self.assertIn("voice is unavailable", out.getvalue())
        self.assertIsNone(speech._local.engine)            # the broken engine is dropped

    def test_listeners_see_every_line_and_a_faulty_one_cannot_stop_speech(self):
        seen = []

        def faulty(text):
            raise ValueError("boom")

        speech.add_listener(faulty)
        speech.add_listener(seen.append)
        speech.add_listener(seen.append)                   # adding twice registers once
        output = self.speak("Reply for the GUI")
        self.assertEqual(seen, ["Reply for the GUI"])
        self.assertIn("listener failed", output)
        speech.remove_listener(seen.append)
        speech.remove_listener(faulty)
        self.speak("Not seen")
        self.assertEqual(seen, ["Reply for the GUI"])

    def test_text_the_console_cannot_display_is_degraded_not_fatal(self):
        raw = io.BytesIO()
        narrow_console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(speech, "TTS_ENABLED", False), redirect_stdout(narrow_console):
            speech.Speak("In Urdu that is صبح بخیر")     # must not raise
        narrow_console.flush()
        shown = raw.getvalue().decode("cp1252")
        self.assertIn("In Urdu that is", shown)
        self.assertIn("?", shown)

    def test_the_configured_voice_is_chosen_by_name_fragment(self):
        voices = [mock.Mock(id="a", **{"name": "Microsoft David"}), mock.Mock(id="b", **{"name": "Microsoft Zira"})]
        # Mock(name=...) sets the mock's repr name, so assign the attribute explicitly
        for voice, label in zip(voices, ("Microsoft David", "Microsoft Zira")):
            voice.name = label

        class WithVoices(FakeEngine):
            def getProperty(self, name):
                return voices

        with mock.patch.object(speech, "TTS_VOICE", "zira"), mock.patch("pyttsx3.engine.Engine", WithVoices):
            engine = speech._engine()
        self.assertEqual(engine.props["voice"], "b")


if __name__ == "__main__":
    unittest.main()
