"""Regression tests for the voice-input chain.

Each test reproduces a real failure this project has had (or could have), so it cannot
silently come back:  python -m unittest tests.test_microphone -v

Tests marked "hardware" need a working microphone and are skipped without one.
"""
import builtins
import importlib.abc
import queue
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speech_recognition as sr  # noqa: E402

import microphone  # noqa: E402
import winmm_mic  # noqa: E402
from tests.isolation import no_windows_audio  # noqa: E402


def setUpModule():
    no_windows_audio()                    # (getting the microphone ready also checks the Windows volume; these tests must not touch it)


try:
    HAS_MIC = sys.platform == "win32" and bool(winmm_mic.list_devices())
except Exception:
    HAS_MIC = False


RELEASE_WHEN_IDLE = microphone._release_when_idle          # the real one, kept for the test that checks it


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
    microphone.last_note = ""
    microphone._calibration.update(at=0.0, base=0.0, misses=0)
    microphone._volume_checked[0] = True                 # the Windows volume has been looked at: nothing to wait for
    microphone._volume_done.set()


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


def audio_of(seconds=1.5, level=1500, rate=16000):
    """A recording of a steady tone at roughly the given loudness (16-bit mono)."""
    import array
    import math
    samples = array.array("h", (int(level * 1.414 * math.sin(i * 0.3)) for i in range(int(seconds * rate))))
    return sr.AudioData(samples.tobytes(), rate, 2)


class FakeSource:
    """An open microphone that records what is done to it."""
    SAMPLE_RATE, SAMPLE_WIDTH, CHUNK = 16000, 2, 1024
    device_name = "fake mic"

    def __init__(self, *args, **kwargs):
        self.opened = self.closed = 0
        self.reads = 0
        self.flushed = []
        outer = self

        class Stream:
            def read(self, frames):
                outer.reads += 1
                return b"\0" * (frames * 2)

            def flush(self, keep_seconds=0.0):
                outer.flushed.append(keep_seconds)

        self.stream = Stream()

    def __enter__(self):
        self.opened += 1
        return self

    def __exit__(self, *exc):
        self.closed += 1
        return False


class VoicePipelineCase(unittest.TestCase):
    """The listening pipeline with a fake microphone and a fake speech service: no hardware, no network."""

    def setUp(self):
        reset()
        self.addCleanup(reset)
        self.made = []

        def make(*args, **kwargs):
            source = FakeSource()
            self.made.append(source)
            return source

        self.recognizer = mock.Mock(energy_threshold=300, dynamic_energy_threshold=True)
        self.recognizer.listen.side_effect = lambda *a, **k: audio_of()
        self.said = []                                  # what the speech service "hears", one answer per call
        self.recognizer.recognize_google.side_effect = self.google
        microphone._recognizer = self.recognizer
        microphone._calibration.update(at=time.monotonic(), base=300, misses=0)
        for patcher in (mock.patch.object(microphone, "Microphone", make), mock.patch.object(microphone, "_beep"),
                        mock.patch.object(microphone, "MIC_BEEP", True), mock.patch("builtins.print"),
                        mock.patch.object(microphone, "_release_when_idle"),
                        mock.patch.object(microphone, "_understanding", return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def google(self, audio, language="en-US", show_all=False):
        answer = self.said.pop(0) if self.said else []
        if isinstance(answer, Exception):
            raise answer
        return {"alternative": [{"transcript": text} for text in answer], "final": True} if answer else []


class OpenMicrophoneTests(VoicePipelineCase):
    def test_the_microphone_stays_open_between_phrases_so_the_first_word_is_not_lost(self):
        for words in ("open chrome", "what time is it", "volume up"):
            self.said.append([words])
            self.assertEqual(microphone._hear("en-pk", 5, 10), words)
        self.assertEqual(len(self.made), 1)
        self.assertEqual((self.made[0].opened, self.made[0].closed), (1, 0))

    def test_a_freshly_opened_microphone_is_warmed_up_and_beeps_once_to_say_speak_now(self):
        self.said.extend([["one"], ["two"]])
        microphone._hear("en-pk", 5, 10)
        self.assertGreater(self.made[0].reads, 0)                               # the first moments after opening are read and thrown away
        microphone._beep.assert_called_once()
        microphone._hear("en-pk", 5, 10)
        microphone._beep.assert_called_once()                                   # (not again for the next phrase)

    def test_resetting_releases_the_microphone(self):
        self.said.append(["hello"])
        microphone._hear("en-pk", 5, 10)
        microphone.reset_microphone()
        self.assertEqual(self.made[0].closed, 1)
        microphone.close_microphone()                                           # (safe to do twice)

    def test_the_microphone_is_released_when_nothing_has_listened_for_a_while(self):
        patcher = mock.patch.object(microphone, "_release_when_idle", RELEASE_WHEN_IDLE)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch("threading.Timer") as timer:
            microphone._release_when_idle()
        timer.assert_called_once_with(microphone.IDLE_RELEASE, microphone.close_microphone)
        timer.return_value.start.assert_called_once()


    def test_listening_again_cancels_a_pending_release(self):
        timer = mock.Mock()
        microphone._idle_timer = timer
        self.said.append(["hello"])
        microphone._hear("en-pk", 5, 10)
        timer.cancel.assert_called_once()
        self.assertIsNone(microphone._idle_timer)


class EchoTests(VoicePipelineCase):
    def test_it_waits_for_jarvis_to_finish_speaking_and_drops_what_the_microphone_heard_of_him(self):
        import speech
        self.said.extend([["hello"], ["again"], ["third"]])
        with mock.patch.object(speech, "wait_until_quiet") as wait, mock.patch.object(speech, "quiet_for", return_value=0.6):
            microphone._hear("en-pk", 5, 10)
            microphone._hear("en-pk", 5, 10)
        self.assertEqual(wait.call_count, 2)
        self.assertAlmostEqual(self.made[0].flushed[-1], 0.6 - microphone.SETTLE)         # only audio after the echo has died away
        with mock.patch.object(speech, "wait_until_quiet"), mock.patch.object(speech, "quiet_for", return_value=500):
            microphone._hear("en-pk", 5, 10)
        self.assertEqual(self.made[0].flushed[-1], microphone.PRE_ROLL)                   # long quiet: just the last moments are kept

    def test_a_phrase_recorded_while_jarvis_was_speaking_is_thrown_away(self):
        import speech
        self.said.append(["real command"])
        answers = iter([True, False])
        with mock.patch.object(speech, "spoke_since", side_effect=lambda moment: next(answers)):
            self.assertEqual(microphone._hear("en-pk", 5, 10), "real command")
        self.assertEqual(self.recognizer.listen.call_count, 2)
        self.assertEqual(self.recognizer.recognize_google.call_count, 1)                  # his own voice was never sent to be recognised

    def test_the_speech_module_knows_when_it_is_speaking(self):
        import speech
        self.assertFalse(speech.is_speaking())
        with mock.patch.object(speech, "_voice") as voice:
            seen = []
            voice.return_value.Speak.side_effect = lambda *a: seen.append((speech.is_speaking(), speech.quiet_for()))
            before = time.monotonic()
            speech._say("Hello there")
        self.assertEqual(seen, [(True, 0.0)])
        self.assertFalse(speech.is_speaking())
        self.assertTrue(speech.spoke_since(before))
        self.assertTrue(speech.wait_until_quiet(timeout=2, settle=0.0))
        self.assertFalse(speech.spoke_since(time.monotonic() + 1))


class StreamFlushTests(unittest.TestCase):
    def test_a_sounddevice_stream_keeps_only_the_most_recent_audio(self):
        audio_queue = queue.Queue()
        for n in range(10):
            audio_queue.put(bytes([n]) * 200)                                   # 100 samples each
        stream = microphone._SoundDeviceStream(mock.Mock(), audio_queue, 2, 1, rate=1000)
        stream.flush(0.25)                                                      # 0.25 s at 1000 Hz, 2 bytes each = 500 bytes
        self.assertEqual(len(stream.buffer), 500)
        self.assertEqual(bytes(stream.buffer[-200:]), bytes([9]) * 200)         # the newest audio is what stays
        stream.flush(0)
        self.assertEqual(len(stream.buffer), 0)
        self.assertTrue(audio_queue.empty())

    def test_a_winmm_stream_keeps_only_the_most_recent_audio(self):
        stream = object.__new__(winmm_mic.WinMMStream)
        stream._queue, stream._pending, stream.rate = queue.Queue(), bytearray(), 1000
        for n in range(10):
            stream._queue.put(bytes([n]) * 200)
        winmm_mic.WinMMStream.flush(stream, 0.25)
        self.assertEqual(len(stream._pending), 500)
        self.assertEqual(bytes(stream._pending[-200:]), bytes([9]) * 200)
        winmm_mic.WinMMStream.flush(stream, 0)
        self.assertEqual(len(stream._pending), 0)


class MisheardWordsTests(VoicePipelineCase):
    def test_the_alternative_that_is_a_command_beats_a_better_scored_one_that_is_not(self):
        known = {"remove not number 2": False, "remove note number 2": True, "remove the note number 2": True}
        with mock.patch.object(microphone, "_understanding", return_value=lambda text: known.get(text, False)):
            self.said.append(["remove not number 2", "remove note number 2", "remove the note number 2"])
            self.assertEqual(microphone._hear("en-pk", 5, 10), "remove note number 2")

    def test_the_best_guess_is_used_when_no_alternative_is_a_command(self):
        with mock.patch.object(microphone, "_understanding", return_value=lambda text: False):
            self.said.append(["why is the sky blue", "wise the sky blue"])
            self.assertEqual(microphone._hear("en-pk", 5, 10), "why is the sky blue")

    def test_a_check_that_fails_never_costs_the_user_the_command(self):
        def broken(text):
            raise RuntimeError("faulty check")

        with mock.patch.object(microphone, "_understanding", return_value=broken):
            self.said.append(["open chrome", "open crowd"])
            self.assertEqual(microphone._hear("en-pk", 5, 10), "open chrome")

    def test_the_alternatives_are_read_from_googles_answer_in_order_without_repeats(self):
        result = {"alternative": [{"transcript": "Open Chrome"}, {"transcript": "open chrome"}, {"transcript": ""},
                                  {"transcript": "open crown"}]}
        self.assertEqual(microphone._alternatives(result), ["open chrome", "open crown"])
        self.assertEqual(microphone._alternatives([]), [])

    def test_the_second_language_is_tried_when_the_first_understands_nothing(self):
        self.said.extend([[], ["open chrome"]])
        self.assertEqual(microphone._hear("en-pk", 5, 10), "open chrome")
        languages = [call.kwargs["language"] for call in self.recognizer.recognize_google.call_args_list]
        self.assertEqual(languages, ["en-pk", microphone.SPEECH_LANGUAGE_FALLBACK])

    def test_a_quiet_voice_is_made_louder_before_it_is_sent(self):
        import audioop
        quiet = audio_of(level=400)
        louder = microphone._louder(quiet)
        self.assertGreater(audioop.rms(louder.frame_data, 2), 2 * audioop.rms(quiet.frame_data, 2))
        self.assertLess(audioop.max(louder.frame_data, 2), 32000)
        normal = audio_of(level=3000)
        self.assertIs(microphone._louder(normal), normal)
        silence = audio_of(level=5)
        self.assertIs(microphone._louder(silence), silence)                      # nothing worth shouting at


class CutOffSentenceTests(VoicePipelineCase):
    def test_a_sentence_that_stops_in_the_middle_gets_the_rest_added(self):
        self.said.extend([["can you add a"], ["task"]])
        self.assertEqual(microphone._hear("en-pk", 5, 10), "can you add a task")

    def test_it_keeps_listening_for_the_rest_at_most_twice(self):
        self.said.extend([["remove the"], ["last task from the"], ["to do"], ["extra"]])
        self.assertEqual(microphone._hear("en-pk", 5, 10), "remove the last task from the to do")
        self.assertEqual(self.recognizer.listen.call_count, 3)

    def test_silence_after_an_unfinished_sentence_gives_what_was_said(self):
        self.said.append(["tell me about the"])
        self.recognizer.listen.side_effect = [audio_of(), sr.WaitTimeoutError()]
        self.assertEqual(microphone._hear("en-pk", 5, 10), "tell me about the")
        self.assertEqual(self.recognizer.listen.call_args_list[1].kwargs["timeout"], microphone.CONTINUE_WAIT)

    def test_finished_sentences_do_not_wait_for_more(self):
        for text in ("what time is it", "thank you", "who am i", "open my to do list", "open chrome please", "remove task 2",
                     "hello", "what is that", "can you hear me", "volume up", "pause"):
            self.assertFalse(microphone._unfinished(text), text)

    def test_unfinished_sentences_are_noticed(self):
        for text in ("can you add a", "remove the", "tell me what", "open", "and", "delete the last", "what is the weather in",
                     "add a task to", "remind me to", "", "2"):
            self.assertTrue(microphone._unfinished(text), text)


class HeardNothingTests(VoicePipelineCase):
    def test_speech_that_could_not_be_understood_is_explained_once(self):
        self.said.extend([[], []])
        self.assertIsNone(microphone._hear("en-pk", 5, 10))
        self.assertIn("couldn't make out the words", microphone.take_note())
        self.assertEqual(microphone.take_note(), "")                            # reading it clears it

    def test_a_very_quiet_voice_is_told_so(self):
        self.recognizer.listen.side_effect = lambda *a, **k: audio_of(level=10)
        self.said.extend([[], []])
        microphone._hear("en-pk", 5, 10)
        self.assertIn("very quiet", microphone.take_note())

    def test_a_short_noise_is_not_worth_a_word(self):
        self.recognizer.listen.side_effect = lambda *a, **k: audio_of(seconds=0.4)
        self.said.extend([[], []])
        microphone._hear("en-pk", 5, 10)
        self.assertEqual(microphone.take_note(), "")

    def test_the_speech_service_being_out_of_reach_is_reported_after_one_retry(self):
        self.said.extend([sr.RequestError("offline"), sr.RequestError("offline")])
        with mock.patch.object(microphone.time, "sleep"):
            self.assertEqual(microphone._hear("en-pk", 5, 10), "")
        self.assertEqual(self.recognizer.recognize_google.call_count, 2)

    def test_a_hiccup_in_the_connection_is_retried(self):
        self.said.extend([sr.RequestError("blip"), ["open chrome"]])
        with mock.patch.object(microphone.time, "sleep"):
            self.assertEqual(microphone._hear("en-pk", 5, 10), "open chrome")


class LoudnessTests(VoicePipelineCase):
    def test_the_speech_threshold_stays_within_reach_of_the_first_measurement(self):
        self.recognizer.energy_threshold = 9000
        microphone._clamp_threshold()
        self.assertEqual(self.recognizer.energy_threshold, 750)                  # never more than 2.5 times the quiet-room level
        self.recognizer.energy_threshold = 5
        microphone._clamp_threshold()
        self.assertEqual(self.recognizer.energy_threshold, 150)                  # nor less than half of it

    def test_after_three_tries_in_a_row_that_heard_nothing_the_room_is_measured_again(self):
        source = FakeSource()
        microphone._calibration["misses"] = 3
        self.recognizer.adjust_for_ambient_noise.side_effect = lambda *a, **k: setattr(self.recognizer, "energy_threshold", 5000)
        microphone._maybe_recalibrate(source)
        self.recognizer.adjust_for_ambient_noise.assert_called_once()
        self.assertEqual(microphone._calibration["misses"], 0)
        self.assertLessEqual(self.recognizer.energy_threshold, 450)             # someone speaking meanwhile cannot make it deaf

    def test_a_quiet_stretch_does_not_trigger_measuring(self):
        microphone._maybe_recalibrate(FakeSource())
        self.recognizer.adjust_for_ambient_noise.assert_not_called()

    def test_the_recogniser_is_set_up_for_short_words_and_a_stuck_service(self):
        recognizer = mock.Mock(energy_threshold=300)
        reset()
        with mock.patch.object(microphone.sr, "Recognizer", return_value=recognizer), \
                mock.patch.object(microphone, "Microphone", FakeSource), mock.patch("builtins.print"):
            self.assertTrue(microphone._ensure_ready())
        self.assertLessEqual(recognizer.phrase_threshold, 0.2)
        self.assertLessEqual(recognizer.operation_timeout, 15)
        self.assertLessEqual(recognizer.non_speaking_duration, recognizer.pause_threshold)


class WindowsVolumeFirstTests(unittest.TestCase):
    """A muted or quiet Windows microphone is put right (see test_audio_levels) before the room is measured, so the speech threshold is
    worked out at the volume the voice will really be heard at."""

    def setUp(self):
        reset()
        self.addCleanup(reset)

    def ready(self, check, wait=None):
        recognizer = mock.Mock(energy_threshold=300)
        self.order = []
        recognizer.adjust_for_ambient_noise.side_effect = lambda *a, **k: self.order.append("measured the room")
        with mock.patch.object(microphone, "check_windows_volume", check), mock.patch.object(microphone.sr, "Recognizer", return_value=recognizer), \
                mock.patch.object(microphone, "Microphone", FakeSource), mock.patch("builtins.print"), \
                mock.patch.object(microphone, "VOLUME_WAIT", wait or microphone.VOLUME_WAIT):
            return microphone._ensure_ready()

    def test_the_room_is_measured_only_after_the_volume_has_been_put_right(self):
        def slow_check():
            microphone._volume_done.clear()

            def finish():
                time.sleep(0.3)
                self.order.append("volume put right")
                microphone._volume_done.set()

            threading.Thread(target=finish, daemon=True).start()

        self.assertTrue(self.ready(slow_check))
        self.assertEqual(self.order, ["volume put right", "measured the room"])

    def test_a_check_that_hangs_cannot_hold_the_microphone_up_for_ever(self):
        started = time.monotonic()
        self.assertTrue(self.ready(microphone._volume_done.clear, wait=0.2))
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(self.order, ["measured the room"])

    def test_with_nothing_to_check_the_microphone_does_not_wait_at_all(self):
        started = time.monotonic()
        self.assertTrue(self.ready(lambda: None))
        self.assertLess(time.monotonic() - started, 1)


class PauseSetting(unittest.TestCase):
    """A pause to think must not end the sentence: "can you tell me the square root of ... 6000" was cut after "of"."""

    def setUp(self):
        reset()
        self.addCleanup(reset)

    def test_the_recogniser_waits_as_long_as_the_setting_says_before_calling_it_the_end(self):
        class Quiet(DeadBackend):
            def __enter__(self):
                return self

        recognizer = mock.Mock(energy_threshold=300)
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
