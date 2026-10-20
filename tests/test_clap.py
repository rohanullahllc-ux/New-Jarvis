"""Tests for clap detection:  python -m unittest tests.test_clap -v

Claps and everything that is not a clap are made up (noise bursts, tones, speech-like sound), so no microphone is used.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clap  # noqa: E402

RATE = 16000


def room(seconds, level=0.0015, seed=0):
    return np.random.default_rng(seed).normal(0, level, int(seconds * RATE)).astype(np.float32)


def a_clap(loudness=0.3, seed=1):
    """A hand clap: 60 ms of wide-band noise that dies away within about 25 ms."""
    t = np.arange(int(0.06 * RATE)) / RATE
    noise = np.diff(np.random.default_rng(seed).normal(0, 1, len(t) + 1)).astype(np.float32)      # (more high than low sound)
    burst = noise * np.exp(-t / 0.012)
    return (burst / np.sqrt(np.mean(burst[:160] ** 2)) * loudness).astype(np.float32)


def put(signal, sound, at):
    start = int(at * RATE)
    signal[start:start + len(sound)] += sound[:len(signal) - start]
    return signal


def run(signal, detector=None, block=1280):
    """Feed the signal in pieces; returns the seconds at which the clap pattern completed."""
    detector = detector or clap.ClapDetector(count=2, sensitivity=1.0)
    fired = []
    for start in range(0, len(signal), block):
        if detector.feed(signal[start:start + block]):
            fired.append(round(detector.time, 2))
    return fired, detector


class ClapPatternTests(unittest.TestCase):
    def test_two_claps_close_together_wake_him_once(self):
        signal = put(put(room(4), a_clap(), 1.0), a_clap(seed=2), 1.4)
        fired, _ = run(signal)
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0], 1.4, delta=0.3)

    def test_one_clap_is_not_enough_for_a_two_clap_pattern(self):
        fired, detector = run(put(room(3), a_clap(), 1.0))
        self.assertEqual(fired, [])
        self.assertEqual([what for _, what, _ in detector.events], ["clap"])             # (it was seen, and counted)

    def test_one_clap_is_enough_when_the_count_is_one(self):
        fired, _ = run(put(room(3), a_clap(), 1.0), clap.ClapDetector(count=1))
        self.assertEqual(len(fired), 1)

    def test_three_claps_in_a_row_are_one_wake_up_not_two(self):
        signal = room(5)
        for n, at in enumerate((1.0, 1.4, 1.8)):
            put(signal, a_clap(seed=n), at)
        fired, _ = run(signal)
        self.assertEqual(len(fired), 1)                                    # (he is deaf for two seconds after waking)

    def test_claps_too_far_apart_are_two_separate_single_claps(self):
        signal = put(put(room(5), a_clap(), 1.0), a_clap(seed=2), 2.5)
        self.assertEqual(run(signal)[0], [])

    def test_a_pattern_of_three_needs_three(self):
        signal = put(put(room(4), a_clap(), 1.0), a_clap(seed=2), 1.4)
        self.assertEqual(run(signal, clap.ClapDetector(count=3))[0], [])
        put(signal, a_clap(seed=3), 1.8)
        self.assertEqual(len(run(signal, clap.ClapDetector(count=3))[0]), 1)

    def test_the_same_result_however_the_sound_is_cut_into_pieces(self):
        signal = put(put(room(4), a_clap(), 1.0), a_clap(seed=2), 1.4)
        moments = []
        for size in (160, 333, 1280, 4000, 16000):
            fired, detector = run(signal, block=size)
            self.assertEqual(len(fired), 1, size)
            moments.append([when for when, what, _ in detector.events if what == "pattern complete"])
        self.assertTrue(all(len(found) == 1 for found in moments), moments)
        self.assertEqual(len({found[0] for found in moments}), 1, moments)               # (the same moment, whatever the pieces)

    def test_whole_numbers_from_the_microphone_work_like_floats(self):
        signal = put(put(room(4), a_clap(), 1.0), a_clap(seed=2), 1.4)
        fired, _ = run((signal * 32767).astype(np.int16))
        self.assertEqual(len(fired), 1)


class NotAClapTests(unittest.TestCase):
    def test_speech_is_never_a_clap(self):
        """Vowels with word-like rises and short noisy consonants, at a normal speaking level, for twenty seconds."""
        t = np.arange(20 * RATE) / RATE
        voice = sum(np.sin(2 * np.pi * f * t * (1 + 0.05 * np.sin(2 * np.pi * 3 * t))) / k for k, f in enumerate((140, 280, 420, 560), 1))
        syllables = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t) ** 2
        signal = (voice * syllables * 0.05).astype(np.float32) + room(20)
        for n in range(40):                                                 # consonant bursts, much quieter than a clap
            put(signal, a_clap(0.04, seed=n), 0.5 * n + 0.2)
        self.assertEqual(run(signal)[0], [])

    def test_a_thump_on_the_desk_is_mostly_low_sound_and_does_not_count(self):
        t = np.arange(int(0.2 * RATE)) / RATE
        thump = (np.sin(2 * np.pi * 70 * t) * np.exp(-t / 0.03) * 0.6).astype(np.float32)
        signal = put(put(room(4), thump, 1.0), thump, 1.4)
        fired, detector = run(signal)
        self.assertEqual(fired, [])
        self.assertTrue(any("thump" in what or "goes on" in what for _, what, _ in detector.events), detector.events)

    def test_a_loud_sound_that_does_not_stop_is_not_a_clap(self):
        t = np.arange(RATE) / RATE
        alarm = (np.sin(2 * np.pi * 2500 * t) * 0.3).astype(np.float32)
        signal = put(put(room(5), alarm, 1.0), alarm, 2.5)
        fired, detector = run(signal)
        self.assertEqual(fired, [])
        self.assertTrue(any("goes on" in what for _, what, _ in detector.events))

    def test_a_loud_start_that_rises_slowly_is_not_a_clap(self):
        t = np.arange(int(0.5 * RATE)) / RATE
        swell = (np.random.default_rng(5).normal(0, 1, len(t)) * np.minimum(1, t / 0.3) * np.exp(-np.maximum(0, t - 0.3) / 0.01) * 0.3).astype(np.float32)
        self.assertEqual(run(put(put(room(4), swell, 1.0), swell, 1.4))[0], [])

    def test_a_quiet_room_noise_burst_below_the_minimum_is_ignored(self):
        soft = a_clap(0.012)                                              # about -38 dB: a keystroke, not a clap
        self.assertEqual(run(put(put(room(4), soft, 1.0), soft, 1.4))[0], [])

    def test_silence_and_steady_noise_never_trigger(self):
        self.assertEqual(run(np.zeros(5 * RATE, dtype=np.float32))[0], [])
        self.assertEqual(run(room(10, level=0.02))[0], [])


class SensitivityTests(unittest.TestCase):
    def test_a_higher_sensitivity_counts_softer_claps_and_a_lower_one_only_loud_ones(self):
        soft = a_clap(0.04)
        signal = put(put(room(4), soft, 1.0), a_clap(0.04, seed=2), 1.4)
        self.assertEqual(run(signal, clap.ClapDetector(count=2, sensitivity=1.0))[0] != [], True)
        self.assertEqual(run(signal, clap.ClapDetector(count=2, sensitivity=0.4))[0], [])
        very_soft = put(put(room(4), a_clap(0.012), 1.0), a_clap(0.012, seed=2), 1.4)
        self.assertEqual(run(very_soft, clap.ClapDetector(count=2, sensitivity=1.0))[0], [])
        self.assertEqual(len(run(very_soft, clap.ClapDetector(count=2, sensitivity=3.0))[0]), 1)

    def test_it_learns_the_room_so_a_noisy_room_needs_louder_claps(self):
        noisy = room(6, level=0.02, seed=9)
        signal = put(put(noisy.copy(), a_clap(0.12), 3.0), a_clap(0.12, seed=2), 3.4)      # clearly a clap in a quiet room
        self.assertEqual(run(signal)[0], [])
        signal = put(put(noisy.copy(), a_clap(0.6), 3.0), a_clap(0.6, seed=2), 3.4)
        self.assertEqual(len(run(signal)[0]), 1)


class StateTests(unittest.TestCase):
    def test_resetting_forgets_a_half_finished_pattern(self):
        detector = clap.ClapDetector(count=2)
        run(put(room(2), a_clap(), 1.0), detector)
        detector.reset()
        self.assertEqual(run(put(room(2), a_clap(), 0.5), detector)[0], [])

    def test_what_it_saw_is_kept_for_the_live_meter_but_not_for_ever(self):
        detector = clap.ClapDetector(count=9)
        signal = room(150)
        for n in range(150):
            put(signal, a_clap(seed=n), n + 0.5)
        run(signal, detector)
        self.assertLessEqual(len(detector.events), 200)
        self.assertEqual(detector.events[-1][1], "clap")


if __name__ == "__main__":
    unittest.main()
