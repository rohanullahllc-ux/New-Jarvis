"""Tests for the wake word and the always-on listener:  python -m unittest tests.test_wakeword -v

The detectors' models are replaced by stand-ins and the microphone by a list of sound pieces: nothing is opened or loaded.
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clap  # noqa: E402
import listener  # noqa: E402
import wakeword  # noqa: E402

PIECE = np.zeros(wakeword.FRAME, dtype=np.int16)


class FakeModel:
    """Gives the scores it was told to, one per 80 ms piece."""

    def __init__(self, scores):
        self.scores = list(scores)
        self.pieces = 0
        self.resets = 0

    def predict(self, piece):
        assert len(piece) == wakeword.FRAME and piece.dtype == np.int16
        self.pieces += 1
        return {"hey_jarvis_v0.1": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


class WakeWordTests(unittest.TestCase):
    def detector(self, scores, sensitivity=0.5):
        return wakeword.WakeWordDetector(sensitivity, model=FakeModel(scores))

    def feed_all(self, detector, pieces, size=None):
        found = []
        for _ in range(pieces):
            found.append(detector.feed(PIECE if size is None else PIECE[:size]))
        return found

    def test_it_needs_two_pieces_in_a_row_above_the_level(self):
        d = self.detector([0.1, 0.9, 0.1, 0.9, 0.95, 0.1])
        self.assertEqual(self.feed_all(d, 6), [False, False, False, False, True, False])

    def test_the_sensitivity_is_the_score_that_wakes_him(self):
        self.assertEqual(wakeword.level_for(0.5), 0.5)
        self.assertEqual((wakeword.level_for(0.0), wakeword.level_for(5)), (0.05, 0.95))
        loose, strict = self.detector([0.4, 0.4], 0.3), self.detector([0.4, 0.4], 0.7)
        self.assertEqual((self.feed_all(loose, 2)[-1], self.feed_all(strict, 2)[-1]), (True, False))

    def test_sound_in_odd_sized_pieces_is_collected_into_80_ms_pieces(self):
        d = self.detector([0.9, 0.9])
        found = [d.feed(np.zeros(500, dtype=np.int16)) for _ in range(6)]           # 3000 samples = two whole pieces and a bit
        self.assertEqual(d.model.pieces, 2)
        self.assertEqual(found.count(True), 1)

    def test_floats_from_minus_one_to_one_are_converted_to_16_bit(self):
        d = self.detector([0.9, 0.9])
        d.feed(np.full(wakeword.FRAME * 2, 0.5, dtype=np.float32))
        self.assertEqual(d.model.pieces, 2)

    def test_after_hearing_it_the_model_is_reset_so_the_same_phrase_is_not_heard_twice(self):
        d = self.detector([0.9, 0.9, 0.9, 0.9])
        self.assertEqual(self.feed_all(d, 2), [False, True])
        self.assertEqual(d.model.resets, 1)

    def test_one_long_piece_with_the_phrase_in_it_is_heard_once(self):
        d = self.detector([0.9, 0.9, 0.9, 0.9, 0.9])
        self.assertTrue(d.feed(np.zeros(wakeword.FRAME * 5, dtype=np.int16)))

    def test_resetting_clears_what_was_half_heard(self):
        d = self.detector([0.9, 0.9, 0.9])
        d.feed(PIECE)
        d.reset()
        self.assertFalse(d.feed(PIECE))                                              # (one piece is not two in a row)

    def test_it_is_available_only_with_the_library_the_files_and_a_safe_import_order(self):
        with mock.patch.object(wakeword, "files_ready", return_value=True), mock.patch.object(wakeword.native_libs, "safe", return_value=True):
            self.assertTrue(wakeword.available())
            with mock.patch("importlib.util.find_spec", return_value=None):
                self.assertFalse(wakeword.available())
            with mock.patch.object(wakeword.native_libs, "safe", return_value=False):
                self.assertFalse(wakeword.available())
        with mock.patch.object(wakeword, "files_ready", return_value=False):
            self.assertFalse(wakeword.available())

    def test_all_three_model_files_are_needed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(wakeword, "FOLDER", Path(folder)):
                self.assertFalse(wakeword.files_ready())
                for name in (wakeword.MODEL_FILE, *wakeword.SUPPORT_FILES):
                    (Path(folder) / name).write_bytes(b"x")
                self.assertTrue(wakeword.files_ready())


def pieces_of(*items):
    """A stand-in for the microphone: each item is the sound piece to give, in order; then the stream ends."""
    def blocks(stop):
        for item in items:
            if stop.is_set():
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    return blocks


class ScriptedDetector:
    """Says True on the pieces it was told to (by position); counts resets."""

    def __init__(self, fires=()):
        self.fires, self.seen, self.resets = set(fires), 0, 0

    def feed(self, piece):
        self.seen += 1
        return self.seen in self.fires

    def reset(self):
        self.resets += 1


class ListenerTests(unittest.TestCase):
    def run_listener(self, blocks, wake_word=None, claps=None, verify=None, cooldown=0.0):
        woke = []
        heard = listener.WakeListener(woke.append, wake_word=wake_word, claps=claps, blocks=blocks, verify=verify or (lambda samples: True),
                                      cooldown=cooldown)
        with mock.patch("builtins.print"), mock.patch.object(listener.speech, "is_speaking", return_value=False):
            self.assertTrue(heard.start())
            heard._thread.join(5)
        self.assertFalse(heard.running)
        return woke, heard

    def test_the_wake_word_wakes_him(self):
        woke, _ = self.run_listener(pieces_of(PIECE, PIECE, PIECE), wake_word=ScriptedDetector({2}))
        self.assertEqual(woke, ["wake word"])

    def test_a_clap_pattern_wakes_him(self):
        woke, _ = self.run_listener(pieces_of(PIECE, PIECE), claps=ScriptedDetector({1}))
        self.assertEqual(woke, ["clap"])

    def test_both_detectors_are_reset_after_waking_so_the_same_sound_cannot_wake_him_again(self):
        wake_word, claps = ScriptedDetector({1}), ScriptedDetector()
        self.run_listener(pieces_of(PIECE, PIECE), wake_word=wake_word, claps=claps)
        self.assertEqual((wake_word.resets, claps.resets), (1, 1))

    def test_for_a_while_after_waking_everything_is_ignored(self):
        woke, _ = self.run_listener(pieces_of(*[PIECE] * 6), wake_word=ScriptedDetector({1, 2, 3, 4}), cooldown=60)
        self.assertEqual(woke, ["wake word"])

    def test_a_wake_word_in_somebody_elses_voice_is_ignored_but_a_clap_is_not_checked(self):
        woke, _ = self.run_listener(pieces_of(PIECE, PIECE, PIECE), wake_word=ScriptedDetector({1}), verify=lambda samples: False)
        self.assertEqual(woke, [])
        woke, _ = self.run_listener(pieces_of(PIECE, PIECE), claps=ScriptedDetector({1}), verify=lambda samples: False)
        self.assertEqual(woke, ["clap"])                                              # (it only opens the password question)

    def test_the_voice_check_gets_the_last_few_seconds_of_sound(self):
        seen = []
        self.run_listener(pieces_of(*[PIECE] * 5), wake_word=ScriptedDetector({5}), verify=lambda samples: seen.append(len(samples)) or True)
        self.assertEqual(seen, [5 * wakeword.FRAME])

    def test_his_own_voice_never_wakes_him(self):
        woke = []
        heard = listener.WakeListener(woke.append, wake_word=ScriptedDetector({1, 2, 3}), claps=ScriptedDetector({1, 2, 3}),
                                      blocks=pieces_of(PIECE, PIECE, PIECE), verify=lambda samples: True, cooldown=0)
        with mock.patch.object(listener.speech, "is_speaking", return_value=True):
            heard.start()
            heard._thread.join(5)
        self.assertEqual(woke, [])

    def test_a_microphone_that_fails_ends_the_listening_with_a_message_instead_of_crashing(self):
        woke, heard = self.run_listener(pieces_of(PIECE, RuntimeError("the microphone was unplugged")), wake_word=ScriptedDetector())
        self.assertEqual(woke, [])
        self.assertIn("unplugged", heard.error)
        self.assertIn("can't listen", heard.error)

    def test_stopping_lets_go_of_the_microphone_promptly(self):
        opened, closed = threading.Event(), threading.Event()

        def blocks(stop):
            try:
                while not stop.is_set():
                    opened.set()
                    time.sleep(0.01)
                    yield PIECE
            finally:
                closed.set()

        heard = listener.WakeListener(lambda reason: None, wake_word=ScriptedDetector(), blocks=blocks)
        heard.start()
        self.assertTrue(opened.wait(2))
        started = time.time()
        heard.stop()
        self.assertTrue(closed.is_set())
        self.assertLess(time.time() - started, 2)
        self.assertFalse(heard.running)

    def test_there_is_nothing_to_start_when_both_detectors_are_off(self):
        with mock.patch.object(listener, "WAKE_WORD", False), mock.patch.object(listener, "CLAP_WAKE", False):
            heard = listener.WakeListener(lambda reason: None, blocks=pieces_of())
            self.assertFalse(heard.start())
        self.assertIn("switched off", heard.error)

    def test_the_real_detectors_are_made_from_the_settings(self):
        with mock.patch.object(listener, "WAKE_WORD", False), mock.patch.object(listener, "CLAP_WAKE", True), \
                mock.patch.object(listener, "CLAP_COUNT", 3), mock.patch.object(listener, "CLAP_SENSITIVITY", 2.0):
            heard = listener.WakeListener(lambda reason: None, blocks=pieces_of())
            wake_word, claps = heard._detectors()
        self.assertIsNone(wake_word)
        self.assertIsInstance(claps, clap.ClapDetector)
        self.assertEqual((claps.count, claps.sensitivity), (3, 2.0))

    def test_a_real_clap_in_a_real_stream_of_sound_wakes_him(self):
        from tests.test_clap import a_clap, put, room
        signal = put(put(room(4), a_clap(), 1.0), a_clap(seed=2), 1.4)
        pieces = [(signal[i:i + wakeword.FRAME] * 32767).astype(np.int16) for i in range(0, len(signal) - wakeword.FRAME, wakeword.FRAME)]
        woke, _ = self.run_listener(pieces_of(*pieces), claps=clap.ClapDetector(count=2))
        self.assertEqual(woke, ["clap"])


class WhatIsListenedForTests(unittest.TestCase):
    def test_the_hint_names_what_will_wake_him(self):
        with mock.patch.object(listener.wakeword, "available", return_value=True), mock.patch.object(listener, "WAKE_WORD", True), \
                mock.patch.object(listener, "CLAP_WAKE", True), mock.patch.object(listener, "CLAP_COUNT", 2):
            self.assertEqual(listener.wanted(), ["wake word", "clap"])
            self.assertEqual(listener.hint(), "To wake me, say 'hey Jarvis' or clap 2 times, or press START.")
        with mock.patch.object(listener.wakeword, "available", return_value=False), mock.patch.object(listener, "CLAP_WAKE", True), \
                mock.patch.object(listener, "CLAP_COUNT", 1):
            self.assertEqual(listener.hint(), "To wake me, clap 1 time, or press START.")
        with mock.patch.object(listener.wakeword, "available", return_value=False), mock.patch.object(listener, "CLAP_WAKE", False):
            self.assertEqual((listener.wanted(), listener.hint()), ([], ""))


class WaitForWakeTests(unittest.TestCase):
    def test_it_returns_the_reason_he_was_woken_and_lets_go_of_the_microphone(self):
        stopped = []

        class Fake:
            def __init__(self, on_wake):
                self.on_wake, self.running = on_wake, True

            def start(self):
                threading.Timer(0.05, lambda: self.on_wake("clap")).start()
                return True

            def stop(self):
                stopped.append(True)

        with mock.patch.object(listener, "WakeListener", Fake):
            self.assertEqual(listener.wait_for_wake(), "clap")
        self.assertEqual(stopped, [True])

    def test_it_gives_up_at_once_when_there_is_nothing_to_listen_for_or_the_microphone_dies(self):
        class Nothing:
            def __init__(self, on_wake):
                pass

            def start(self):
                return False

        class Dies(Nothing):
            running = False

            def start(self):
                return True

            def stop(self):
                pass

        with mock.patch.object(listener, "WakeListener", Nothing):
            self.assertIsNone(listener.wait_for_wake())
        with mock.patch.object(listener, "WakeListener", Dies):
            self.assertIsNone(listener.wait_for_wake())


if __name__ == "__main__":
    unittest.main()
