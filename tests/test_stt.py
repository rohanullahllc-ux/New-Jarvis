"""Tests for the offline speech recognition:  python -m unittest tests.test_stt -v

Whisper itself is replaced by a stand-in: no model is loaded and nothing is heard.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech_recognition as sr  # noqa: E402

import stt  # noqa: E402


def recording(seconds=1.5, rate=16000):
    samples = (np.sin(np.arange(int(seconds * rate)) * 0.3) * 3000).astype(np.int16)
    return sr.AudioData(samples.tobytes(), rate, 2)


def segment(text, no_speech=0.01, logprob=-0.3):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


class FakeWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, samples, **options):
        self.calls.append((len(samples), options))
        return iter(self.segments), SimpleNamespace()


class WhisperCase(unittest.TestCase):
    def setUp(self):
        stt._model = None
        self.addCleanup(setattr, stt, "_model", None)

    def hear(self, segments, audio=None):
        fake = FakeWhisper(segments)
        stt._model = fake
        self.fake = fake
        return stt.transcribe(audio or recording())


class TidyTests(unittest.TestCase):
    def test_whisper_text_becomes_the_plain_lower_case_words_the_rest_of_jarvis_reads(self):
        for written, plain in (("Okay, now open the notes folder.", "okay now open the notes folder"),
                               ("What time is it?", "what time is it"),
                               ("Set an alarm for 5:30 p.m.", "set an alarm for 5:30 p.m."),
                               ("Set an alarm for 7 A.M.", "set an alarm for 7 a.m."),
                               ("It costs 3.5 dollars.", "it costs 3.5 dollars"),
                               ("[MUSIC] Open Chrome (laughs)", "open chrome"),
                               ("Add a task - buy milk!", "add a task buy milk"),
                               ('He said "stop".', "he said stop"),
                               ("  lots   of   space  ", "lots of space")):
            self.assertEqual(stt.tidy(written), plain, written)


class TranscribeTests(WhisperCase):
    def test_the_words_come_back_plain_and_whisper_is_told_what_jarvis_is_about(self):
        self.assertEqual(self.hear([segment(" Add a task, buy milk."), segment(" And call Ali.")]), "add a task buy milk and call ali")
        length, options = self.fake.calls[0]
        self.assertEqual(length, int(1.5 * 16000))
        self.assertEqual((options["language"], options["beam_size"], options["vad_filter"]), ("en", 1, True))
        self.assertIn("task", options["initial_prompt"])
        self.assertFalse(options["condition_on_previous_text"])

    def test_a_recording_at_another_sample_rate_is_converted_to_16_khz(self):
        self.hear([segment("hello")], recording(1.0, rate=44100))
        self.assertEqual(self.fake.calls[0][0], 16000)

    def test_segments_that_are_probably_not_speech_are_dropped(self):
        self.assertEqual(self.hear([segment("real words", 0.02, -0.4), segment("thanks", 0.9, -1.4), segment("garbage", 0.1, -2.0)]),
                         "real words")

    def test_the_things_whisper_invents_from_silence_are_not_words(self):
        for invented in ("Thanks for watching!", "Thank you for watching.", "you", stt.VOCABULARY):
            self.assertEqual(self.hear([segment(invented)]), "", invented)
        self.assertEqual(self.hear([segment("Thank you.")]), "thank you")            # (a real thank-you to Jarvis is kept)

    def test_nothing_said_is_an_empty_string_not_an_error(self):
        self.assertEqual(self.hear([]), "")

    def test_a_click_is_too_short_to_send_to_whisper_at_all(self):
        self.assertEqual(self.hear([segment("x")], recording(0.1)), "")
        self.assertEqual(self.fake.calls, [])

    def test_when_whisper_cannot_be_used_the_caller_is_told_so_it_can_ask_google(self):
        stt._model = SimpleNamespace(transcribe=mock.Mock(side_effect=RuntimeError("out of memory")))
        with self.assertRaises(stt.SpeechRecognitionFailed):
            stt.transcribe(recording())
        self.assertIn("out of memory", stt.last_error)
        stt._model = FakeWhisper([segment("fine now")])
        self.assertEqual(stt.transcribe(recording()), "fine now")
        self.assertEqual(stt.last_error, "")


class AvailabilityTests(unittest.TestCase):
    def folder_with_model(self, name="base.en"):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        snapshot = Path(folder.name) / f"models--Systran--faster-whisper-{name}" / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "model.bin").write_bytes(b"x")
        return Path(folder.name), snapshot

    def test_the_model_folder_is_found_only_when_the_model_file_is_there(self):
        root, snapshot = self.folder_with_model()
        with mock.patch.object(stt, "MODEL_DIR", root), mock.patch.object(stt, "STT_MODEL", "base.en"):
            self.assertEqual(stt._model_folder(), snapshot)
            self.assertIsNone(stt._model_folder("small.en"))
        with mock.patch.object(stt, "MODEL_DIR", Path("no such folder")):
            self.assertIsNone(stt._model_folder())

    def test_it_is_used_only_when_switched_on_installed_and_downloaded(self):
        root, _ = self.folder_with_model()
        with mock.patch.object(stt, "MODEL_DIR", root), mock.patch.object(stt, "STT_MODEL", "base.en"), \
                mock.patch.object(stt.native_libs, "safe", return_value=True):
            for engine, expected in (("auto", True), ("whisper", True), ("google", False)):
                with mock.patch.object(stt, "STT_ENGINE", engine):
                    self.assertEqual(stt.available(), expected, engine)
            with mock.patch.object(stt, "STT_MODEL", "small.en"):
                self.assertFalse(stt.available())                                # (not downloaded)
            with mock.patch("importlib.util.find_spec", return_value=None):
                self.assertFalse(stt.available())                                # (library missing)

    def test_loading_without_the_model_says_how_to_get_it(self):
        stt._model = None
        with mock.patch.object(stt, "MODEL_DIR", Path("no such folder")):
            with self.assertRaises(stt.SpeechRecognitionFailed) as caught:
                stt.load()
        self.assertIn("--download", str(caught.exception))

    def test_warming_up_does_nothing_when_whisper_will_not_be_used(self):
        with mock.patch.object(stt, "available", return_value=False), mock.patch.object(stt.threading, "Thread") as thread:
            stt.warm_up()
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
