"""Tests for telling the owner's voice from other voices:  python -m unittest tests.test_speaker -v

The voice model is replaced by a stand-in that returns a vector chosen by the test: the model itself is never loaded.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech_recognition as sr  # noqa: E402

import speaker  # noqa: E402

RNG = np.random.default_rng(3)


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    return vector / np.linalg.norm(vector)


OWNER = unit(RNG.normal(size=192))


def near(base, closeness):
    """A unit vector whose cosine with ``base`` is about ``closeness``."""
    other = unit(RNG.normal(size=192))
    other = unit(other - (other @ base) * base)                          # at right angles to base
    return unit(closeness * base + np.sqrt(1 - closeness ** 2) * other)


def speech_clip(seconds=2.0, silence=0.5, rate=16000):
    """Quiet, then a loud tone like words, then quiet: as a speech_recognition AudioData."""
    quiet = np.zeros(int(silence * rate))
    tone = np.sin(np.arange(int(seconds * rate)) * 0.2) * 0.3 * (np.sin(np.arange(int(seconds * rate)) * 0.0007) ** 2 + 0.3)
    samples = np.concatenate([quiet, tone, quiet]) + np.random.default_rng(0).normal(0, 0.001, int((seconds + 2 * silence) * rate))
    return sr.AudioData((samples * 32767).astype(np.int16).tobytes(), rate, 2)


class VoiceCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.heard = OWNER                                               # what the stand-in model "hears" next
        self.embed = mock.Mock(side_effect=lambda samples: self.heard)
        for patcher in (mock.patch.object(speaker, "PRINT_FILE", Path(folder.name) / "voiceprint.npz"),
                        mock.patch.object(speaker, "embed", self.embed), mock.patch.object(speaker, "VOICE_LOCK", "auto"),
                        mock.patch.object(speaker, "VOICE_MATCH", 0.0), mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)
        speaker._print_cache.update(stamp=None, data=None)
        speaker._override[0] = None
        speaker._last_ok[0] = 0.0
        speaker._warned.clear()
        self.addCleanup(speaker._print_cache.update, stamp=None, data=None)
        self.addCleanup(speaker._override.__setitem__, 0, None)

    def enrol(self, count=15, closeness=0.85):
        clips = [np.concatenate([np.zeros(8000), np.sin(np.arange(40000) * 0.2) * 0.3, np.zeros(8000)]) for _ in range(count)]
        vectors = iter([near(OWNER, closeness) for _ in range(count)])
        self.embed.side_effect = lambda samples: next(vectors)
        result = speaker.enroll(clips)
        self.embed.side_effect = lambda samples: self.heard
        return result


class SpeechPartTests(unittest.TestCase):
    def test_the_silence_around_the_words_is_cut_away_and_the_speech_time_counted(self):
        samples = np.concatenate([np.zeros(16000), np.sin(np.arange(32000) * 0.2) * 0.3, np.zeros(16000)]).astype(np.float32)
        part, seconds = speaker.speech_part(samples)
        self.assertAlmostEqual(seconds, 2.0, delta=0.15)
        self.assertLess(len(part), 36000)
        self.assertGreater(len(part), 30000)

    def test_a_recording_with_nothing_in_it_has_no_speech(self):
        self.assertEqual(speaker.speech_part(np.zeros(32000, dtype=np.float32))[1], 0.0)
        self.assertEqual(speaker.speech_part(np.zeros(10, dtype=np.float32))[1], 0.0)


class EnrolTests(VoiceCase):
    def test_enrolling_saves_a_voice_print_and_chooses_a_level_between_the_limits(self):
        self.assertFalse(speaker.enrolled())
        result = self.enrol()
        self.assertTrue(speaker.enrolled())
        self.assertEqual(result["used"], 15)
        self.assertTrue(speaker.LOWEST <= result["threshold"] <= speaker.HIGHEST)
        self.assertGreater(result["mean"], 0.5)
        self.assertEqual(speaker.threshold(), result["threshold"])

    def test_a_sentence_that_is_too_short_or_silent_is_left_out_and_too_few_is_an_error(self):
        clips = [np.zeros(16000)] * 3 + [np.sin(np.arange(40000) * 0.2) * 0.3] * 6
        self.embed.side_effect = lambda samples: near(OWNER, 0.85)
        result = speaker.enroll(clips)
        self.assertEqual((result["used"], result["skipped"]), (6, 3))
        with self.assertRaises(ValueError):
            speaker.enroll([np.zeros(16000)] * 8 + [np.sin(np.arange(40000) * 0.2) * 0.3] * 2)

    def test_the_voice_print_can_be_deleted(self):
        self.enrol()
        self.assertTrue(speaker.delete_print())
        self.assertFalse(speaker.enrolled())
        self.assertFalse(speaker.delete_print())

    def test_a_damaged_voice_print_counts_as_none(self):
        speaker.PRINT_FILE.write_bytes(b"not a numpy file")
        self.assertFalse(speaker.enrolled())

    def test_a_new_voice_print_is_noticed_without_restarting(self):
        self.enrol(closeness=0.85)
        first = speaker.threshold()
        time.sleep(0.02)
        self.enrol(closeness=0.6)
        self.assertNotEqual(speaker.threshold(), first)


class AcceptTests(VoiceCase):
    def test_without_a_voice_print_every_voice_is_answered(self):
        verdict = speaker.accept(speech_clip())
        self.assertEqual((verdict.ok, verdict.reason), (True, "off"))
        self.embed.assert_not_called()

    def test_the_owner_is_accepted_and_somebody_else_is_not(self):
        self.enrol()
        self.heard = near(OWNER, 0.8)
        mine = speaker.accept(speech_clip())
        self.assertEqual((mine.ok, mine.reason), (True, "match"))
        self.assertGreater(mine.score, speaker.threshold())
        self.heard = near(OWNER, 0.1)
        other = speaker.accept(speech_clip())
        self.assertEqual((other.ok, other.reason), (False, "mismatch"))
        self.assertLess(other.score, speaker.threshold())

    def test_the_short_wake_phrase_needs_a_little_less(self):
        self.enrol()
        edge = speaker.threshold() - speaker.RELAXED / 2
        self.heard = near(OWNER, edge)
        self.assertFalse(speaker.accept(speech_clip()).ok)
        self.assertTrue(speaker.accept(speech_clip(), relaxed=True).ok)

    def test_the_level_in_the_settings_beats_the_one_chosen_at_enrolment(self):
        self.enrol()
        self.heard = near(OWNER, 0.7)
        with mock.patch.object(speaker, "VOICE_MATCH", 0.9):
            self.assertFalse(speaker.accept(speech_clip()).ok)
            self.assertEqual(speaker.threshold(), 0.9)
        with mock.patch.object(speaker, "VOICE_MATCH", 0.3):
            self.assertTrue(speaker.accept(speech_clip()).ok)

    def test_a_word_too_short_to_judge_is_accepted_only_soon_after_a_phrase_that_passed(self):
        self.enrol()
        word = speech_clip(seconds=0.3)
        self.assertEqual(speaker.accept(word).reason, "short")                 # nothing has passed yet
        self.assertFalse(speaker.accept(word).ok)
        self.heard = near(OWNER, 0.85)
        self.assertTrue(speaker.accept(speech_clip()).ok)
        self.assertEqual(speaker.accept(word).reason, "trusted")
        speaker._last_ok[0] = time.monotonic() - speaker.TRUST_SECONDS - 1
        self.assertEqual(speaker.accept(word).reason, "short")

    def test_a_rejected_voice_does_not_extend_the_trust(self):
        self.enrol()
        self.heard = near(OWNER, 0.05)
        speaker.accept(speech_clip())
        self.assertEqual(speaker.accept(speech_clip(seconds=0.3)).reason, "short")

    def test_the_lock_can_be_switched_off_and_on_for_this_run(self):
        self.enrol()
        self.heard = near(OWNER, 0.05)
        self.assertFalse(speaker.accept(speech_clip()).ok)
        speaker.set_lock(False)
        self.assertEqual(speaker.accept(speech_clip()).reason, "off")
        self.assertIn("off", speaker.status())
        speaker.set_lock(None)
        with mock.patch.object(speaker, "VOICE_LOCK", "off"):
            self.assertTrue(speaker.accept(speech_clip()).ok)
            speaker.set_lock(True)
            self.assertFalse(speaker.accept(speech_clip()).ok)

    def test_when_the_model_cannot_be_used_every_voice_is_heard_and_the_user_is_told_once(self):
        self.enrol()
        self.embed.side_effect = speaker.SpeakerUnavailable("the voice model is not downloaded")
        with mock.patch("builtins.print") as shown:
            first, second = speaker.accept(speech_clip()), speaker.accept(speech_clip())
        self.assertEqual((first.ok, first.reason, second.ok), (True, "unavailable", True))
        notices = [call.args[0] for call in shown.call_args_list if call.args and "voice lock is on but cannot be used" in str(call.args[0])]
        self.assertEqual(len(notices), 1)


class StatusTests(VoiceCase):
    def test_the_status_says_what_the_lock_is_doing(self):
        self.assertIn("enroll_voice.py", speaker.status())
        self.enrol()
        self.assertIn("only answer your voice", speaker.status())
        with mock.patch.object(speaker, "VOICE_LOCK", "off"):
            self.assertIn("any voice", speaker.status())


class ModelTests(unittest.TestCase):
    def test_the_model_needs_its_file_and_the_library(self):
        with mock.patch.object(speaker, "MODEL_FILE", Path("no such model.onnx")):
            self.assertFalse(speaker.model_ready())
            with self.assertRaises(speaker.SpeakerUnavailable) as caught:
                speaker._load() if speaker._extractor is None else self.skipTest("already loaded")
            self.assertIn("--download", str(caught.exception))

    def test_loading_in_the_wrong_order_is_refused_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "m.onnx"
            model.write_bytes(b"x")
            with mock.patch.object(speaker, "MODEL_FILE", model), mock.patch.object(speaker, "_extractor", None), \
                    mock.patch.object(speaker.native_libs, "safe", return_value=False):
                with self.assertRaises(speaker.SpeakerUnavailable):
                    speaker._load()

    def test_warming_up_does_nothing_without_the_lock(self):
        with mock.patch.object(speaker, "lock_active", return_value=False), mock.patch.object(speaker.threading, "Thread") as thread:
            speaker.warm_up()
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
