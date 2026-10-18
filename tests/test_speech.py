"""Tests for speech.py:  python -m unittest tests.test_speech -v

Most use a stand-in Windows voice. The last class speaks through the real Windows voice at volume 0 (silent,
but it still takes as long as the speech would) to prove that EVERY sentence is spoken, not just the first.
"""
import io
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech  # noqa: E402


class FakeToken:
    def __init__(self, description):
        self.description = description

    def GetDescription(self):
        return self.description


class FakeVoice:
    """Enough of Windows' SpVoice for speech.py."""
    created = 0

    def __init__(self):
        type(self).created += 1
        self.spoken = []
        self.Rate, self.Volume = 0, 100
        self.Voice = FakeToken("Microsoft David Desktop - English (United States)")
        self.tokens = [self.Voice, FakeToken("Microsoft Zira Desktop - English (United States)")]

    def GetVoices(self):
        return self.tokens

    def Speak(self, text, flags):
        self.spoken.append((text, flags, self.Rate))


class SpeakTests(unittest.TestCase):
    def setUp(self):
        speech._local = threading.local()
        speech._listeners.clear()
        speech._reported.clear()
        FakeVoice.created = 0

    def speak(self, text, enabled=True, voice_class=FakeVoice):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", enabled), mock.patch.object(speech, "_create_voice", voice_class), \
                redirect_stdout(out):
            speech.Speak(text)
        return out.getvalue()

    def test_text_is_always_printed(self):
        self.assertIn("A.I : Hello sir", self.speak("Hello sir"))

    def test_voice_off_never_creates_a_voice(self):
        self.speak("Hello", enabled=False)
        self.assertEqual(FakeVoice.created, 0)

    def test_empty_text_is_ignored(self):
        self.assertEqual(self.speak("   ").strip(), "")
        self.assertEqual(FakeVoice.created, 0)

    def test_every_sentence_is_spoken_not_just_the_first(self):
        """pyttsx3 spoke the greeting and then stayed silent for the rest of the session."""
        for sentence in ("First.", "Second sentence.", "Third one, a little longer than the others, so it speeds up."):
            self.speak(sentence)
        voice = speech._local.voice
        self.assertEqual([text for text, _, _ in voice.spoken], ["First.", "Second sentence.",
                                                                 "Third one, a little longer than the others, so it speeds up."])
        self.assertEqual({flags for _, flags, _ in voice.spoken}, {0})           # 0 = wait until it has been said
        self.assertEqual(FakeVoice.created, 1)                                   # one voice, reused

    def test_long_sentences_are_spoken_faster_than_short_ones(self):
        self.speak("Hi")
        self.speak("This is a much longer sentence that goes well past thirty characters.")
        rates = [rate for _, _, rate in speech._local.voice.spoken]
        self.assertEqual(rates, [0, 2])

    def test_the_rate_setting_adjusts_the_speed_within_limits(self):
        with mock.patch.object(speech, "TTS_RATE", 3):
            self.speak("Hi")
        self.assertEqual(speech._local.voice.spoken[0][2], 3)
        with mock.patch.object(speech, "TTS_RATE", 50):
            self.speak("Hi again")
        with mock.patch.object(speech, "TTS_RATE", -50):
            self.speak("Hi once more")
        self.assertEqual([rate for _, _, rate in speech._local.voice.spoken[1:]], [10, -10])

    def test_the_volume_setting_is_applied_within_limits(self):
        for setting, expected in ((40, 40), (150, 100), (-5, 0)):
            speech._local = threading.local()
            with mock.patch.object(speech, "TTS_VOLUME", setting):
                self.speak("Hi")
            self.assertEqual(speech._local.voice.Volume, expected)

    def test_the_voice_is_created_once_per_thread_and_reused(self):
        self.speak("one")
        self.speak("two")
        self.assertEqual(FakeVoice.created, 1)

    def test_each_thread_gets_its_own_voice(self):
        voices = []

        def work():
            self.speak("from a worker thread")
            voices.append(speech._local.voice)

        self.speak("from the main thread")
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertEqual(FakeVoice.created, 2)
        self.assertIsNot(voices[0], speech._local.voice)

    def test_a_broken_voice_does_not_crash_is_reported_once_and_is_retried_fresh(self):
        class Broken(FakeVoice):
            def Speak(self, text, flags):
                raise OSError("SAPI exploded")

        output = self.speak("still shown", voice_class=Broken)                  # must not raise
        self.assertIn("still shown", output)
        self.assertIn("voice is unavailable - SAPI exploded", output)
        self.assertFalse(hasattr(speech._local, "voice") and speech._local.voice)   # the broken voice is dropped
        second = self.speak("shown again", voice_class=Broken)
        self.assertIn("shown again", second)
        self.assertNotIn("voice is unavailable", second)                        # the same problem is not repeated
        self.speak("recovered")                                                 # a healthy voice works afterwards
        self.assertEqual(speech._local.voice.spoken[-1][0], "recovered")

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
        self.assertEqual(speech._local.voice.spoken[0][0], "Reply for the GUI")
        speech.remove_listener(seen.append)
        speech.remove_listener(faulty)
        self.speak("Not seen")
        self.assertEqual(seen, ["Reply for the GUI"])

    def test_the_configured_voice_is_chosen_by_name_fragment(self):
        with mock.patch.object(speech, "TTS_VOICE", "zira"), mock.patch.object(speech, "_create_voice", FakeVoice):
            voice = speech._voice()
        self.assertIn("Zira", voice.Voice.GetDescription())

    def test_an_unknown_voice_name_keeps_the_windows_default(self):
        with mock.patch.object(speech, "TTS_VOICE", "no such voice"), mock.patch.object(speech, "_create_voice", FakeVoice):
            voice = speech._voice()
        self.assertIn("David", voice.Voice.GetDescription())

    def test_text_the_console_cannot_display_is_degraded_not_fatal(self):
        raw = io.BytesIO()
        narrow_console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        with mock.patch.object(speech, "TTS_ENABLED", False), redirect_stdout(narrow_console):
            speech.Speak("In Urdu that is صبح بخیر")     # must not raise
        narrow_console.flush()
        shown = raw.getvalue().decode("cp1252")
        self.assertIn("In Urdu that is", shown)
        self.assertIn("?", shown)


class SpeakStreamTests(unittest.TestCase):
    """A reply that is still being written is spoken sentence by sentence, starting with the first."""

    def setUp(self):
        speech._local = threading.local()
        speech._listeners.clear()
        speech._streaming.clear()
        speech._reported.clear()
        FakeVoice.created = 0
        self.addCleanup(speech._listeners.clear)
        self.addCleanup(speech._streaming.clear)

    def stream(self, sentences, voice_class=FakeVoice, enabled=True, **options):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", enabled), mock.patch.object(speech, "_create_voice", voice_class), \
                redirect_stdout(out):
            result = speech.SpeakStream(sentences, **options)
        self.output = out.getvalue()
        return result

    def spoken(self):
        return [text for text, _, _ in speech._local.voice.spoken]

    def test_every_sentence_is_spoken_in_order(self):
        self.assertTrue(self.stream(iter(["First.", "Second one.", "Third."])))
        self.assertEqual(self.spoken(), ["First.", "Second one.", "Third."])
        self.assertEqual(FakeVoice.created, 1)                                   # on the calling thread, with one voice

    def test_the_text_is_shown_as_one_reply(self):
        self.stream(["First.", "Second."])
        self.assertEqual(self.output.count("A.I :"), 1)
        self.assertIn("A.I : First.", self.output)
        self.assertIn("      Second.", self.output)

    def test_an_empty_reply_says_nothing_and_reports_it(self):
        self.assertFalse(self.stream(iter([])))
        self.assertFalse(self.stream(["", "   "]))
        self.assertFalse(hasattr(speech._local, "voice") and speech._local.voice and speech._local.voice.spoken)

    def test_with_the_voice_off_it_is_shown_but_not_spoken(self):
        self.assertTrue(self.stream(["Quiet."], enabled=False))
        self.assertIn("Quiet.", self.output)
        self.assertEqual(FakeVoice.created, 0)

    def test_window_listeners_are_told_which_sentence_starts_the_reply(self):
        plain, windowed = [], []
        speech.add_listener(plain.append)
        speech.add_listener(lambda text, first: windowed.append((text, first)), streaming=True)
        self.stream(["One.", "Two.", "Three."])
        self.assertEqual(plain, ["One.", "Two.", "Three."])
        self.assertEqual(windowed, [("One.", True), ("Two.", False), ("Three.", False)])

    def test_an_ordinary_line_is_always_a_new_message_for_a_window_listener(self):
        windowed = []
        speech.add_listener(lambda text, first: windowed.append((text, first)), streaming=True)
        self.stream(["One.", "Two."])
        with mock.patch.object(speech, "_create_voice", FakeVoice), mock.patch.object(speech, "TTS_ENABLED", True), \
                redirect_stdout(io.StringIO()):
            speech.Speak("A separate line")
        self.assertEqual(windowed[-1], ("A separate line", True))

    def test_removing_a_window_listener_forgets_that_it_wanted_to_stream(self):
        def listener(text, first):
            pass

        speech.add_listener(listener, streaming=True)
        speech.remove_listener(listener)
        self.assertNotIn(listener, speech._streaming)

    def test_the_next_sentence_is_produced_while_the_last_is_still_being_spoken(self):
        events = []

        class SlowVoice(FakeVoice):
            def Speak(self, text, flags):
                events.append(("starts speaking", text))
                time.sleep(0.3)
                events.append(("finished speaking", text))

        def sentences():
            yield "First."
            time.sleep(0.05)
            events.append(("produced", "Second."))
            yield "Second."

        self.stream(sentences(), voice_class=SlowVoice)
        self.assertEqual(events[:3], [("starts speaking", "First."), ("produced", "Second."), ("finished speaking", "First.")])

    def test_trouble_while_writing_the_reply_keeps_what_was_said_and_is_then_raised(self):
        def sentences():
            yield "A good start."
            raise ConnectionError("dropped")

        with self.assertRaises(ConnectionError):
            self.stream(sentences())
        self.assertEqual(self.spoken(), ["A good start."])

    def test_a_slow_start_gets_one_polite_word_and_then_the_reply(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def sentences():
            release.wait(5)
            yield "Worth the wait."

        timer = threading.Timer(0.5, release.set)
        timer.start()
        self.addCleanup(timer.cancel)
        self.assertTrue(self.stream(sentences(), if_slow="One moment, sir.", after=0.1))
        self.assertEqual(self.spoken(), ["One moment, sir.", "Worth the wait."])

    def test_a_quick_start_gets_no_polite_word(self):
        self.stream(iter(["Quick."]), if_slow="One moment, sir.", after=2)
        self.assertEqual(self.spoken(), ["Quick."])

    def test_a_slow_reply_nothing_ever_comes_of_still_ends(self):
        def sentences():
            time.sleep(0.3)
            return
            yield

        self.assertFalse(self.stream(sentences(), if_slow="One moment, sir.", after=0.05))
        self.assertEqual(self.spoken(), ["One moment, sir."])


class VoiceCheckTests(unittest.TestCase):
    def setUp(self):
        speech._local = threading.local()
        speech._reported.clear()

    def run_check(self, clock):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", True), mock.patch.object(speech, "_create_voice", FakeVoice), \
                mock.patch.object(speech.time, "time", side_effect=clock), redirect_stdout(out):
            healthy = speech.check()
        return healthy, out.getvalue()

    def test_a_voice_that_takes_the_time_speech_takes_passes(self):
        healthy, output = self.run_check([0, 5, 5, 9, 9, 12])
        self.assertTrue(healthy)
        self.assertIn("Jarvis can speak, and keeps speaking", output)

    def test_a_voice_that_comes_back_at_once_is_reported_as_silent(self):
        healthy, output = self.run_check([0, 4, 4, 4.01, 4.01, 4.02])          # the 2nd and 3rd "return" instantly
        self.assertFalse(healthy)
        self.assertEqual(output.count("came back too fast"), 2)
        self.assertIn("Something is wrong with speech", output)

    def test_a_voice_that_cannot_start_is_reported(self):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", True), mock.patch.object(speech, "_create_voice", side_effect=OSError("no SAPI")), \
                redirect_stdout(out):
            self.assertFalse(speech.check())
        self.assertIn("can't be started: no SAPI", out.getvalue())

    def test_a_voice_that_is_switched_off_is_not_a_failure(self):
        out = io.StringIO()
        with mock.patch.object(speech, "TTS_ENABLED", False), redirect_stdout(out):
            self.assertTrue(speech.check())
        self.assertIn("stay silent", out.getvalue())


def sapi_available():
    try:
        speech._create_voice()
        return sys.platform == "win32"
    except Exception:
        return False


@unittest.skipUnless(sapi_available(), "hardware: needs Windows speech")
class RealWindowsVoice(unittest.TestCase):
    """Uses the real voice at volume 0: silent, but each sentence still takes as long as speaking it would."""

    SENTENCES = ("Testing, one, two, three.", "A second sentence, to prove the voice keeps going.", "And a third.")

    def setUp(self):
        speech._local = threading.local()
        speech._reported.clear()
        patch = mock.patch.object(speech, "TTS_VOLUME", 0)
        patch.start()
        self.addCleanup(patch.stop)

    def durations(self):
        times = []
        for sentence in self.SENTENCES:
            started = time.time()
            self.assertTrue(speech._say(sentence), "the voice reported a failure")
            times.append(time.time() - started)
        return times

    def assert_all_spoken(self, times):
        for sentence, took in zip(self.SENTENCES, times):
            self.assertGreaterEqual(took, len(sentence) / speech.CHECK_CHARACTERS_PER_SECOND,
                                    f"{sentence!r} came back after {took:.2f}s: it was not spoken")

    def test_every_sentence_is_spoken_on_the_main_thread(self):
        self.assert_all_spoken(self.durations())

    def test_every_sentence_is_spoken_from_a_worker_thread(self):
        result = {}

        def work():
            speech._local = threading.local()
            result["times"] = self.durations()

        thread = threading.Thread(target=work)
        thread.start()
        thread.join(60)
        self.assertIn("times", result, "the worker thread never finished speaking")
        self.assert_all_spoken(result["times"])


if __name__ == "__main__":
    unittest.main()
