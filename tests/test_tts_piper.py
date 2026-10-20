"""Tests for the natural voice:  python -m unittest tests.test_tts_piper -v

Piper itself is replaced by a stand-in and nothing is played: the tests never load a model or make the PC speak.
"""
import sys
import threading
import time
import unittest
import wave
import io
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech  # noqa: E402
import tts_piper  # noqa: E402


class FakePiper:
    """Enough of a PiperVoice: makes 0.1 s of 'sound' per word, and records what it was asked."""
    config = SimpleNamespace(sample_rate=22050)

    def __init__(self):
        self.made = []
        self.active = 0
        self.overlap = False

    def synthesize(self, text, syn_config=None):
        self.active += 1
        if self.active > 1:
            self.overlap = True
        self.made.append((text, syn_config.length_scale, syn_config.volume))
        time.sleep(0.01)
        self.active -= 1
        words = len(text.split())
        return [SimpleNamespace(audio_int16_bytes=b"\x01\x00" * 2205) for _ in range(words)]


class NaturalVoiceCase(unittest.TestCase):
    def setUp(self):
        self.piper = FakePiper()
        self.played = []
        tts_piper._voice, tts_piper._voice_name = self.piper, "en_GB-alan-medium"
        tts_piper._cache.clear()
        for patcher in (mock.patch.object(tts_piper, "play", side_effect=lambda pcm, rate: self.played.append((len(pcm), rate))),
                        mock.patch.object(tts_piper, "_settings",          # (the real Piper is never imported here: see native_libs.py)
                                          side_effect=lambda length_scale, volume: SimpleNamespace(length_scale=length_scale, volume=volume)),
                        mock.patch.object(tts_piper, "chosen", return_value="en_GB-alan-medium"),
                        mock.patch.object(tts_piper, "available", return_value=True),
                        mock.patch.object(tts_piper, "TTS_VOLUME", 80)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, tts_piper, "_voice", None)
        self.addCleanup(setattr, tts_piper, "_voice_name", "")
        self.addCleanup(tts_piper._cache.clear)


class SayTests(NaturalVoiceCase):
    def test_a_sentence_is_made_and_played_at_the_voices_own_sample_rate(self):
        self.assertTrue(tts_piper.say("Hello sir how are you"))
        self.assertEqual(self.played, [(5 * 4410, 22050)])
        self.assertEqual(tts_piper.last_error, "")

    def test_the_volume_and_speed_settings_reach_the_voice(self):
        tts_piper.say("one two", rate=0)
        tts_piper.say("three four", rate=10)
        tts_piper.say("five six", rate=-10)
        (_, normal, volume), (_, fast, _), (_, slow, _) = self.piper.made
        self.assertEqual((normal, volume), (1.0, 0.8))
        self.assertAlmostEqual(fast, 1 / 1.5)
        self.assertAlmostEqual(slow, 1 / 0.6 if tts_piper.speed_for(-10) == 0.6 else 1 / 0.5)
        self.assertEqual((tts_piper.speed_for(100), tts_piper.speed_for(-100)), (1.6, 0.6))

    def test_a_voice_that_fails_reports_why_and_says_so_instead_of_raising(self):
        with mock.patch.object(self.piper, "synthesize", side_effect=RuntimeError("model broke")):
            self.assertFalse(tts_piper.say("anything"))
        self.assertIn("model broke", tts_piper.last_error)
        self.assertEqual(self.played, [])

    def test_a_sentence_that_makes_no_sound_counts_as_a_failure(self):
        with mock.patch.object(self.piper, "synthesize", return_value=[]):
            self.assertFalse(tts_piper.say("silence"))
        self.assertIn("no sound", tts_piper.last_error)


class PrefetchTests(NaturalVoiceCase):
    def test_a_sentence_made_ahead_of_time_is_not_made_again(self):
        tts_piper.prefetch("the next sentence", 0)
        for thread in threading.enumerate():
            if thread.name == "piper-prefetch":
                thread.join(3)
        self.assertEqual(len(self.piper.made), 1)
        tts_piper.say("the next sentence", 0)
        self.assertEqual(len(self.piper.made), 1)                       # (said from what was already made)
        self.assertEqual(len(self.played), 1)

    def test_two_sentences_are_never_made_at_the_same_moment(self):
        threads = [threading.Thread(target=tts_piper.synthesize, args=(f"sentence number {n}",)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(len(self.piper.made), 6)
        self.assertFalse(self.piper.overlap)                           # (the phonemizer inside Piper is not thread safe)

    def test_only_a_few_sentences_are_kept(self):
        for n in range(30):
            tts_piper.synthesize(f"sentence {n}")
        self.assertLessEqual(len(tts_piper._cache), tts_piper._CACHE_SIZE)

    def test_nothing_is_made_for_empty_text_or_without_a_voice(self):
        tts_piper.prefetch("   ")
        with mock.patch.object(tts_piper, "available", return_value=False):
            tts_piper.prefetch("hello")
        time.sleep(0.05)
        self.assertEqual(self.piper.made, [])


class WaveTests(unittest.TestCase):
    def test_the_sound_is_wrapped_as_a_playable_wav(self):
        data = tts_piper._wave_bytes(b"\x00\x01" * 100, 22050)
        with wave.open(io.BytesIO(data)) as handle:
            self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()), (1, 2, 22050, 100))

    def test_stopping_asks_windows_to_purge_the_sound(self):
        with mock.patch("winsound.PlaySound") as play:
            tts_piper.stop()
        play.assert_called_once_with(None, mock.ANY)


class WhichVoiceTests(unittest.TestCase):
    def test_the_chosen_voice_falls_back_to_the_first_installed_one(self):
        with mock.patch.object(tts_piper, "installed", return_value=["a-voice", "b-voice"]):
            with mock.patch.object(tts_piper, "PIPER_VOICE", "b-voice"):
                self.assertEqual(tts_piper.chosen(), "b-voice")
            with mock.patch.object(tts_piper, "PIPER_VOICE", "not-installed"):
                self.assertEqual(tts_piper.chosen(), "a-voice")
        with mock.patch.object(tts_piper, "installed", return_value=[]):
            self.assertEqual(tts_piper.chosen(), "")

    def test_a_voice_needs_both_its_files_to_count_as_installed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "good.onnx").write_bytes(b"x")
            (Path(folder) / "good.onnx.json").write_bytes(b"{}")
            (Path(folder) / "half.onnx").write_bytes(b"x")
            with mock.patch.object(tts_piper, "VOICE_DIR", Path(folder)):
                self.assertEqual(tts_piper.installed(), ["good"])
        with mock.patch.object(tts_piper, "VOICE_DIR", Path("no such folder")):
            self.assertEqual(tts_piper.installed(), [])

    def test_without_a_voice_there_is_nothing_to_load(self):
        with mock.patch.object(tts_piper, "chosen", return_value=""), mock.patch.object(tts_piper, "_voice", None):
            with self.assertRaises(RuntimeError):
                tts_piper.load()


class SpeechUsesTheNaturalVoiceTests(NaturalVoiceCase):
    """speech.py: the natural voice first, the Windows voice only when it fails, and never on a thread that waits for nothing."""

    def setUp(self):
        super().setUp()
        speech._reported.clear()
        speech._local = threading.local()
        for patcher in (mock.patch.object(speech, "TTS_ENGINE", "auto"), mock.patch.object(speech, "TTS_ENABLED", True),
                        mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_sentence_is_said_by_the_natural_voice_and_the_windows_voice_stays_silent(self):
        with mock.patch.object(speech, "_create_voice", side_effect=AssertionError("the Windows voice was used")):
            self.assertTrue(speech._say("Hello sir how are you"))
        self.assertEqual(len(self.played), 1)

    def test_while_it_speaks_jarvis_knows_he_is_speaking(self):
        seen = []
        tts_piper.play.side_effect = lambda pcm, rate: seen.append(speech.is_speaking())
        speech._say("Hello sir")
        self.assertEqual(seen, [True])
        self.assertFalse(speech.is_speaking())
        self.assertLess(speech.quiet_for(), 2)

    def test_when_the_natural_voice_fails_the_windows_voice_says_it_and_the_problem_is_reported_once(self):
        said = []
        voice = SimpleNamespace(Rate=0, Volume=100, Voice=SimpleNamespace(GetDescription=lambda: "x"), GetVoices=lambda: [],
                                Speak=lambda text, flags: said.append(text))
        with mock.patch.object(self.piper, "synthesize", side_effect=RuntimeError("model broke")), \
                mock.patch.object(speech, "_create_voice", return_value=voice), mock.patch("builtins.print") as shown:
            self.assertTrue(speech._say("first one"))
            self.assertTrue(speech._say("second one"))
        self.assertEqual(said, ["first one", "second one"])
        notices = [call.args[0] for call in shown.call_args_list if call.args and "natural voice failed" in str(call.args[0])]
        self.assertEqual(len(notices), 1)

    def test_the_windows_engine_setting_switches_the_natural_voice_off(self):
        said = []
        voice = SimpleNamespace(Rate=0, Volume=100, Voice=SimpleNamespace(GetDescription=lambda: "x"), GetVoices=lambda: [],
                                Speak=lambda text, flags: said.append(text))
        with mock.patch.object(speech, "TTS_ENGINE", "windows"), mock.patch.object(speech, "_create_voice", return_value=voice):
            speech._say("hello there")
        self.assertEqual(said, ["hello there"])
        self.assertEqual(self.played, [])

    def test_long_sentences_are_spoken_a_little_faster_like_before(self):
        speech._say("Hi")
        speech._say("This is a much longer sentence than the first one")
        self.assertEqual([round(length, 3) for _, length, _ in self.piper.made], [1.0, round(1 / 1.1, 3)])

    def test_the_next_sentence_of_a_reply_is_made_while_the_one_before_is_spoken(self):
        order = []
        tts_piper.play.side_effect = lambda pcm, rate: (order.append("playing"), time.sleep(0.15))
        real_make = self.piper.synthesize

        def make(text, syn_config=None):
            order.append(f"made {text}")
            return real_make(text, syn_config=syn_config)

        with mock.patch.object(self.piper, "synthesize", side_effect=make):
            speech.SpeakStream(iter(["First sentence here.", "Second sentence here."]))
        for thread in threading.enumerate():
            if thread.name == "piper-prefetch":
                thread.join(2)
        self.assertLess(order.index("made Second sentence here."), len(order) - 1)               # made before the end ...
        self.assertEqual(order.count("playing"), 2)                                              # ... and both spoken

    def test_warming_up_loads_the_voice_in_the_background_only_when_it_will_be_used(self):
        with mock.patch.object(tts_piper, "warm_up") as warm:
            speech.warm_up()
            warm.assert_called_once()
        with mock.patch.object(tts_piper, "warm_up") as warm, mock.patch.object(speech, "TTS_ENGINE", "windows"):
            speech.warm_up()
            warm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
