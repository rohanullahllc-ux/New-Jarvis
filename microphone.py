"""Microphone input for Jarvis.

`listen()` hears one phrase and returns it as lowercase text. With INPUT_MODE=text in
.env - or whenever no working microphone is available - commands are typed instead.

Two interchangeable capture backends sit behind one interface. Neither needs PyAudio,
which has no build for Python 3.14:

  sounddevice   PortAudio, shipped inside the `sounddevice` wheel (py3-none-win_amd64)
  winmm         pure-Python ctypes over Windows' own winmm.dll (see winmm_mic.py)

MIC_BACKEND=auto (the default) uses sounddevice first and fails over to winmm if it cannot
be loaded, will not open, or stops delivering audio. Nothing here can hang the program:
the sounddevice import runs on a watchdog thread and every read has a timeout.

Run `python microphone.py` for a step-by-step health check of the whole voice chain.
"""
import argparse
import queue
import sys
import threading
import time

import speech_recognition as sr

import speaker
import speech
import stt
import winmm_mic
from config import (INPUT_MODE, MIC_BACKEND, MIC_BEEP, MIC_DEVICE, MIC_PAUSE, MIC_VOLUME, SPEECH_LANGUAGE, SPEECH_LANGUAGE_FALLBACK,
                    STT_ENGINE)
from winmm_mic import MicrophoneError, WinMMMicrophone

READ_TIMEOUT = 5       # seconds without audio before a backend is declared dead
PROBE_TIMEOUT = 3      # the same, while checking a backend before first use
SD_INIT_TIMEOUT = 6    # seconds sounddevice may take to start before we give up on it
UNHEARD_LIMIT = 5      # this many empty tries in a row -> switch to typed input
LANGUAGE = SPEECH_LANGUAGE
SETTLE = 0.35          # seconds of quiet after Jarvis stops speaking before the microphone starts to listen (room echo)
PRE_ROLL = 0.5         # seconds of audio from just before listening begins that are kept, so the first word is not lost
CONTINUE_WAIT = 4.0    # after a sentence that sounds unfinished, how long to wait for the rest of it
MAX_CONTINUATIONS = 2
IDLE_RELEASE = 45      # seconds without listening before the microphone is released (so Windows' microphone light goes off)
RECALIBRATE_EVERY = 600
VOLUME_WAIT = 10       # the first listen waits at most this long for the Windows microphone volume to be put right


# ---------------------------------------------------------------- sounddevice backend

_sd = None            # the sounddevice module, once loaded
_sd_error = None      # why it cannot be used in this process, if so


def _load_sounddevice(timeout=SD_INIT_TIMEOUT):
    """Import sounddevice on a watchdog thread.

    Importing it runs PortAudio's start-up device scan, which can block for good when a
    Windows audio driver is stuck. A fallback cannot rescue a blocked main thread, a
    watchdog can: if the import has not finished in `timeout` seconds we give up on
    sounddevice for the rest of this run (the stuck thread is a daemon and is harmless).
    """
    global _sd, _sd_error
    if _sd is not None:
        return _sd
    if _sd_error:
        raise MicrophoneError(_sd_error)
    result = {}

    def work():
        try:
            import sounddevice
            result["module"] = sounddevice
        except Exception as e:     # e.g. the bundled PortAudio DLL could not be loaded
            result["error"] = e

    worker = threading.Thread(target=work, name="sounddevice-init", daemon=True)
    worker.start()
    worker.join(timeout)
    if "module" in result:
        _sd = result["module"]
        return _sd
    if "error" in result:
        _sd_error = f"sounddevice could not be loaded ({result['error']})"
    else:
        _sd_error = f"sounddevice did not start within {timeout} s (the Windows audio driver is not responding)"
    raise MicrophoneError(_sd_error)


def _pick_sd_device(sd, device):
    """None/'' -> the default input; digits -> that index; text -> first input whose name contains it."""
    if device is None or str(device).strip() == "":
        return None
    text = str(device).strip()
    if text.isdigit():
        return int(text)
    try:
        default_api = sd.default.hostapi
    except Exception:
        default_api = None
    matches = [(i, d) for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0 and text.lower() in d["name"].lower()]
    if not matches:
        raise MicrophoneError(f"no sounddevice input has {text!r} in its name")
    preferred = [m for m in matches if m[1]["hostapi"] == default_api]
    return (preferred or matches)[0][0]


class _SoundDeviceStream:
    """Reads audio from a callback-fed queue, so a stuck driver times out instead of blocking.

    A blocking read froze inside PortAudio's C call earlier in this project (and surfaced as
    a bogus KeyboardInterrupt) when a device opened but never produced samples. In callback
    mode PortAudio pushes audio from its own thread and read() waits on the queue with a timeout.
    """

    def __init__(self, raw, audio_queue, sample_width, timeout, rate=16000):
        self.raw, self.queue, self.width, self.timeout, self.rate = raw, audio_queue, sample_width, timeout, rate
        self.buffer = bytearray()

    def flush(self, keep_seconds=0.0):
        """Throw away audio recorded earlier than the last ``keep_seconds``, and keep the rest."""
        while True:
            try:
                self.buffer.extend(self.queue.get_nowait())
            except queue.Empty:
                break
        keep = int(max(0.0, keep_seconds) * self.rate) * self.width
        if len(self.buffer) > keep:
            del self.buffer[:len(self.buffer) - keep]

    def read(self, frames):
        needed = frames * self.width
        while len(self.buffer) < needed:
            try:
                self.buffer.extend(self.queue.get(timeout=self.timeout))
            except queue.Empty:
                raise MicrophoneError(f"the microphone delivered no audio for {self.timeout:g} s") from None
        data = bytes(self.buffer[:needed])
        del self.buffer[:needed]
        return data

    def close(self):
        try:
            self.raw.stop()
            self.raw.close()
        except Exception:
            pass


class SoundDeviceMicrophone(sr.AudioSource):
    backend = "sounddevice"

    def __init__(self, device_index=None, sample_rate=None, chunk_size=1024, read_timeout=READ_TIMEOUT):
        sd = _load_sounddevice()
        try:
            self._device = _pick_sd_device(sd, device_index)
            info = sd.query_devices(self._device, "input")
        except MicrophoneError:
            raise
        except Exception as e:
            raise MicrophoneError(f"sounddevice found no usable input device ({e})") from e
        self.device_index = device_index
        self.device_name = str(info["name"]).strip()
        self.SAMPLE_RATE = int(sample_rate or info["default_samplerate"])
        self.SAMPLE_WIDTH = 2          # 16-bit audio
        self.CHUNK = chunk_size
        self.read_timeout = read_timeout
        self.stream = None

    def __enter__(self):
        audio_queue = queue.Queue(maxsize=256)

        def callback(indata, frames, time_info, status):
            chunk = bytes(indata)
            try:
                audio_queue.put_nowait(chunk)
            except queue.Full:          # nobody is reading: drop the oldest audio
                try:
                    audio_queue.get_nowait()
                    audio_queue.put_nowait(chunk)
                except (queue.Empty, queue.Full):
                    pass

        try:
            raw = _sd.RawInputStream(samplerate=self.SAMPLE_RATE, blocksize=self.CHUNK, device=self._device,
                                     channels=1, dtype="int16", callback=callback)
            raw.start()
        except Exception as e:
            raise MicrophoneError(f"sounddevice could not open the microphone ({e})") from e
        self.stream = _SoundDeviceStream(raw, audio_queue, self.SAMPLE_WIDTH, self.read_timeout, self.SAMPLE_RATE)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


# ---------------------------------------------------------------- choosing a backend

BACKENDS = {"sounddevice": SoundDeviceMicrophone, "winmm": WinMMMicrophone}

_active = None          # name of the backend in use
_active_device = ""     # its device name, for status messages
_failed = {}            # backend name -> why it stopped working in this run


def _order():
    return [MIC_BACKEND] if MIC_BACKEND in BACKENDS else list(BACKENDS)


def _make(name, **kwargs):
    return BACKENDS[name](device_index=MIC_DEVICE or None, **kwargs)


def _select_backend():
    """Find a backend that really delivers audio: open it and read one chunk."""
    global _active, _active_device
    tried = []
    for name in _order():
        if name in _failed:
            continue
        try:
            source = _make(name, read_timeout=PROBE_TIMEOUT)
            with source as opened:
                opened.stream.read(opened.CHUNK)
        except Exception as e:         # MicrophoneError, OSError, whatever a driver throws
            _failed[name] = str(e)
            tried.append(f"{name}: {e}")
            continue
        _active, _active_device = name, source.device_name
        if tried:
            print(f": Using the '{name}' microphone backend instead ({'; '.join(tried)}).")
        return
    reasons = tried or [f"{k}: {v}" for k, v in _failed.items()]
    raise MicrophoneError("no working microphone (" + "; ".join(reasons) + ")")


def Microphone(**kwargs):
    """A ready-to-use audio source on the best working backend."""
    if _active is None:
        _select_backend()
    return _make(_active, **kwargs)


def mic_status():
    """One short line for logs and the GUI: what Jarvis is listening with."""
    if _text_mode:
        return "typed input"
    if _active:
        return f"{_active}: {_active_device}"
    return "voice, not started yet"


def _failover(reason):
    """The active backend broke: remember why, then try the other one. True if audio works again."""
    global _active
    if _active:
        _failed[_active] = str(reason)
    _active = None
    try:
        _select_backend()
        return True
    except MicrophoneError:
        return False


# ---------------------------------------------------------------- typed fallback

_recognizer = None
_text_mode = INPUT_MODE == "text"
_unheard = 0                  # consecutive tries that produced no understood words
_typed_hint_shown = False


def _type_prompt():
    global _typed_hint_shown
    if not _typed_hint_shown:
        if not sys.stdin or not sys.stdin.isatty():
            # Non-interactive stdin: input() would hit EOF at once. This is the usual cause of
            # "it prints the prompt and exits" - the program is running where you cannot type.
            print(": This window can't accept typed input, so Jarvis has nowhere to read commands from.\n"
                  ": That happens with the 'Run' button when it uses the Output pane (or Code Runner).\n"
                  ": Open a real terminal - in VS Code press Ctrl+` for the integrated terminal - and run:\n"
                  ":     python Startup.py\n"
                  ": then type your commands there. (Or set INPUT_MODE=voice in .env to use the mic.)")
            raise SystemExit(1)
        print(": Typed mode. Type a command and press Enter. Type 'quit' to stop Jarvis.")
        _typed_hint_shown = True
    try:
        return input("You (type): ").strip()
    except EOFError:
        print("\n: Keyboard input closed, so I'm stopping. Run 'python Startup.py' in a terminal to type to me.")
        raise SystemExit(0)
    except KeyboardInterrupt:
        print("\n: Goodbye, sir.")
        raise SystemExit(0)


def _switch_to_typing(reason):
    global _text_mode
    _text_mode = True
    print(f": {reason}")
    for hint in _quick_hints():
        print(f": {hint}")
    print(": Switching to typed commands.")
    return _type_prompt()


def _unheard_try():
    """Count one try that heard nothing usable; switch to typing once too many pile up."""
    global _unheard
    _unheard += 1
    if _unheard >= UNHEARD_LIMIT:
        return _switch_to_typing("I can't make out any speech from the microphone.")
    return ""


def reset_microphone():
    """Forget past failures and try voice again (used by the GUI's mic button)."""
    global _active, _recognizer, _text_mode, _unheard
    close_microphone()
    _failed.clear()
    _active, _recognizer, _unheard = None, None, 0
    _text_mode = INPUT_MODE == "text"


# ---------------------------------------------------------------- the open microphone

class _Held(sr.AudioSource):
    """The microphone, kept open between phrases.

    Opening a stream for every phrase meant the first fraction of a second of speech fell into the time the stream took to start,
    so the first word of a command was often lost or half heard. Kept open, the microphone is already listening when you speak.
    """

    def __init__(self, source):
        self._source = source
        self.fresh = True                         # just opened: not warmed up yet

    def __getattr__(self, name):                  # SAMPLE_RATE, SAMPLE_WIDTH, CHUNK, stream, device_name...
        return getattr(self._source, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def flush(self, keep_seconds):
        flush = getattr(getattr(self._source, "stream", None), "flush", None)
        if flush:
            flush(keep_seconds)

    def close(self):
        self._source.__exit__(None, None, None)


_held = None
_held_lock = threading.RLock()
_idle_timer = None
_calibration = {"at": 0.0, "base": 0.0, "misses": 0}
last_note = ""             # why the last try heard nothing useful, in words for the user ("" if nothing to say)


def _held_source():
    """The open microphone (opened now if it is not)."""
    global _held
    with _held_lock:
        if _held is None:
            source = Microphone()
            source.__enter__()
            _held = _Held(source)
        return _held


def close_microphone():
    """Release the microphone (the Windows microphone light goes off). Safe at any time."""
    global _held, _idle_timer
    with _held_lock:
        held, _held = _held, None
        timer, _idle_timer = _idle_timer, None
    if timer is not None:
        timer.cancel()
    if held is not None:
        try:
            held.close()
        except Exception:                          # noqa: BLE001 - a driver that is already gone is fine
            pass


def _keep_open():
    """Listening has begun again: the microphone must not be released from under it."""
    global _idle_timer
    with _held_lock:
        timer, _idle_timer = _idle_timer, None
    if timer is not None:
        timer.cancel()


def _release_when_idle():
    """Schedule the microphone to be released if nothing listens for a while (hands-free listening never leaves it idle)."""
    global _idle_timer
    with _held_lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(IDLE_RELEASE, close_microphone)
        _idle_timer.daemon = True
        _idle_timer.start()


def take_note():
    """Why the last try heard nothing useful ("" when there is nothing to say); reading it clears it."""
    global last_note
    note, last_note = last_note, ""
    return note


# ---------------------------------------------------------------- listening

def _ensure_ready():
    """First use: pick a backend and calibrate for background noise. True if voice is usable."""
    global _recognizer
    if _recognizer is not None:
        return True
    print(": Starting the microphone, stay quiet for a second...")
    check_windows_volume()                          # (nothing new when the program's start-up has begun it already)
    _volume_done.wait(VOLUME_WAIT)                  # the room is measured at the volume it will be heard at
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = MIC_PAUSE          # a pause to think is not the end of the sentence (it was 1 s, and cut some off)
    recognizer.non_speaking_duration = min(0.6, MIC_PAUSE)     # a little silence is kept either side of the words
    recognizer.phrase_threshold = 0.2               # a short "yes" or "no" is a phrase, not a click
    recognizer.operation_timeout = 12               # a stuck speech service must not freeze the session
    for _ in range(2):                  # the second pass runs after a failover
        try:
            source = _held_source()
            recognizer.adjust_for_ambient_noise(source, duration=1)
            _recognizer = recognizer
            _calibration.update(at=time.monotonic(), base=recognizer.energy_threshold, misses=0)
            _clamp_threshold()
            print(f": Microphone ready [{mic_status()}]. Say a wake word like 'hey jarvis'.")
            return True
        except (MicrophoneError, OSError) as e:
            print(f": Microphone problem: {e}")
            close_microphone()
            if not _failover(e):
                break
    return False


_volume_checked = [False]
_volume_done = threading.Event()              # set while no check of the Windows microphone volume is running
_volume_done.set()


def _put_right(audio_levels, volume, muted):
    """Switch the Windows microphone on and raise it to MIC_VOLUME when it is muted or under LOW_VOLUME percent (a louder one
    is left as it is). Returns the volume and mute state afterwards."""
    too_quiet = volume < min(audio_levels.LOW_VOLUME, MIC_VOLUME)
    if not (muted or too_quiet):
        return volume, muted
    was = " and ".join((["muted"] if muted else []) + ([f"only at {volume} percent"] if too_quiet else []))
    did = []
    try:
        if muted:
            audio_levels.set_muted(False)
            muted = False
            did.append("switched it on")
        if too_quiet:
            volume = audio_levels.set_volume(MIC_VOLUME)
            did.append(f"set it to {volume} percent")
    except audio_levels.AudioError:
        pass                                      # what could not be done is reported by the advice that follows
    if did:
        print(f": The Windows microphone was {was}, so I {' and '.join(did)}. (MIC_VOLUME in .env; 0 leaves Windows alone.)")
    return volume, muted


def check_windows_volume():
    """Once per run, in the background: put right a Windows microphone that is muted or turned down low (MIC_VOLUME; 0 only
    warns), which is the usual reason a voice assistant misses words or hears half a sentence. The first listen waits for it."""
    if _volume_checked[0]:
        return
    _volume_checked[0] = True
    _volume_done.clear()

    def look():
        global last_note
        try:
            import audio_levels
            volume, muted = audio_levels.state()
            if MIC_VOLUME:
                volume, muted = _put_right(audio_levels, volume, muted)
            advice = audio_levels.advice(volume, muted)
            if advice:
                print(f": {advice}")
                last_note = last_note or advice
        except Exception:                            # noqa: BLE001 - this is only help; Jarvis works without it
            pass
        finally:
            _volume_done.set()

    threading.Thread(target=look, name="mic-volume-check", daemon=True).start()


def _clamp_threshold():
    """Keep the loudness that counts as speech within sensible limits of the first measurement: a noisy minute must not leave
    it so high that a normal voice is ignored (words skipped), or so low that the room itself is 'speech'."""
    base = _calibration["base"] or _recognizer.energy_threshold
    _recognizer.energy_threshold = min(max(_recognizer.energy_threshold, 60, base * 0.5), min(2500, base * 2.5))


def _maybe_recalibrate(source):
    """Measure the room again now and then, and after several tries in a row that heard nothing."""
    due = time.monotonic() - _calibration["at"] > RECALIBRATE_EVERY or _calibration["misses"] >= 3
    if not due:
        _clamp_threshold()
        return
    before = _recognizer.energy_threshold
    try:
        _recognizer.adjust_for_ambient_noise(source, duration=0.6)
    except (MicrophoneError, OSError):
        return
    _recognizer.energy_threshold = min(_recognizer.energy_threshold, before * 1.5)       # (someone may have spoken meanwhile)
    _calibration.update(at=time.monotonic(), misses=0)
    _clamp_threshold()


def _beep():
    try:
        import winsound
        winsound.Beep(1000, 60)
    except Exception:                                # noqa: BLE001 - no sound device: the beep is only a convenience
        pass


def _prepare_to_listen(source):
    """Before each phrase: let Jarvis finish speaking, drop what the microphone heard of him, keep the last moments before now."""
    speech.wait_until_quiet(timeout=30, settle=SETTLE)
    if getattr(source, "fresh", False):
        source.fresh = False
        for _ in range(max(1, int(0.3 * source.SAMPLE_RATE / source.CHUNK))):      # let a freshly opened device settle
            source.stream.read(source.CHUNK)
        if MIC_BEEP:
            _beep()
            time.sleep(0.12)
        source.flush(0)
    else:
        source.flush(max(0.0, min(PRE_ROLL, speech.quiet_for() - SETTLE)))
    _maybe_recalibrate(source)


class _VoiceUnavailable(Exception):
    """Voice input can't be used right now; the message says why."""


def _capture(timeout, phrase_time_limit):
    """One phrase of audio, or None if nobody spoke within ``timeout`` seconds. Raises _VoiceUnavailable if the microphone fails."""
    for attempt in range(3):
        started = time.monotonic()
        try:
            source = _held_source()
            _prepare_to_listen(source)
            print(": Listening.....")
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        except sr.WaitTimeoutError:
            return None
        except (MicrophoneError, OSError) as e:
            close_microphone()
            if attempt < 2 and _failover(e):
                continue                  # the other backend works: try the same listen again
            raise _VoiceUnavailable(f"The microphone stopped working ({e}).") from None
        if speech.spoke_since(started):
            print(": (that was Jarvis's own voice, so I'm ignoring it)")        # e.g. a reminder spoke while the microphone was open
            continue
        return audio
    return None


def _louder(audio):
    """The recording with its volume raised when the voice was quiet: a faint voice is where words go missing."""
    try:
        import audioop
        loudest = audioop.max(audio.frame_data, audio.sample_width)
        level = audioop.rms(audio.frame_data, audio.sample_width)
        if 40 < level < 1500 and loudest:
            gain = min(8.0, 3000 / level, 30000 / loudest)
            if gain > 1.2:
                return sr.AudioData(audioop.mul(audio.frame_data, audio.sample_width, gain), audio.sample_rate, audio.sample_width)
    except Exception:                                # noqa: BLE001 - recognition still works on the recording as it was
        pass
    return audio


def _alternatives(result):
    """The different things Google thought it heard, best first, from a show_all result."""
    found = result.get("alternative", []) if isinstance(result, dict) else []
    texts = []
    for entry in found:
        text = (entry.get("transcript") or "").strip().lower()
        if text and text not in texts:
            texts.append(text)
    return texts


def _understanding():
    """The function that says whether Jarvis would do something with a sentence, once the command brain is loaded (or None)."""
    module = sys.modules.get("JarvisAdvancedBot.LocalBrain")
    return getattr(module, "is_command", None)


def _choose(alternatives):
    """Of the possible sentences, the first one Jarvis would act on; the best guess otherwise. A command heard as another
    word ("remove not number 2" for note) is put right by the alternative that makes sense."""
    understand = _understanding()
    if understand:
        for text in alternatives[:6]:
            try:
                if understand(text):
                    if text != alternatives[0]:
                        print(f": (chose {text!r} over {alternatives[0]!r}: that is a command I know)")
                    return text
            except Exception:                        # noqa: BLE001 - a faulty check must not cost the user a command
                break
    return alternatives[0]


def _noted(audio, why):
    global last_note
    seconds = len(audio.frame_data) / max(1, audio.sample_rate * audio.sample_width)
    if why == "unclear" and seconds >= 1.0:
        last_note = "I heard you but couldn't make out the words. Please say it again, a little slower."
    elif why == "quiet":
        last_note = "Your voice is very quiet for the microphone. Move closer, or raise the microphone volume in Windows."


def _owner(audio):
    """True if the voice lock lets this recording through (it is the owner's voice, or the lock is off)."""
    global last_note
    try:
        verdict = speaker.accept(audio)
    except Exception as error:                       # noqa: BLE001 - a faulty check must never leave Jarvis deaf
        print(f": (the voice lock failed - {error}; listening anyway)")
        return True
    if verdict.ok:
        return True
    shown = f", score {verdict.score:.2f}" if verdict.score is not None else ""
    print(f": (that was not your voice{shown}, so I'm ignoring it)")
    last_note = ("I didn't recognise your voice, so I ignored that. Say it again, a little closer to the microphone, or type it. "
                 "Saying or typing 'turn off the voice lock' stops this.")
    return False


def _whisper(audio):
    """What Whisper (on this PC) heard: the words, "" if it ran and heard nothing, None if it cannot be used (then Google is asked)."""
    if not stt.available():
        return None
    try:
        print(": Recognizing (on this PC).....")
        return stt.transcribe(audio)
    except stt.SpeechRecognitionFailed as error:
        if str(error) not in _whisper_problems:
            _whisper_problems.add(str(error))
            print(f": (Whisper could not be used - {error}; asking Google instead)")
        return None


_whisper_problems = set()


def _no_words(audio):
    """Nothing could be understood in this recording: leave a hint for the user and count the miss."""
    try:
        import audioop
        quiet = audioop.rms(audio.frame_data, audio.sample_width) < 40
    except Exception:                                # noqa: BLE001
        quiet = False
    _noted(audio, "quiet" if quiet else "unclear")
    _calibration["misses"] += 1
    return None


def _recognize(audio, language):
    """The words in a recording: a string, None if nothing could be understood, "" if Google's speech service is out of reach.

    Whisper on this PC goes first. Google is the second opinion when Whisper heard nothing (STT_ENGINE=auto), and the only
    one when Whisper is not installed or STT_ENGINE=google."""
    audio_loud = _louder(audio)
    heard = _whisper(audio_loud)
    if heard:
        _calibration["misses"] = 0
        return _choose([heard])
    if heard == "" and STT_ENGINE == "whisper":      # Whisper heard nothing, and Google is not allowed to listen
        return _no_words(audio)
    result = None
    for attempt in range(2):
        try:
            print(": Recognizing.....")
            result = _recognizer.recognize_google(audio_loud, language=language, show_all=True)
            break
        except sr.UnknownValueError:
            result = []
            break
        except sr.RequestError as e:
            if attempt == 0:
                time.sleep(0.4)                       # a hiccup in the connection: one more go
                continue
            print(f": Speech service unavailable, check your internet ({e})")
            return ""
    alternatives = _alternatives(result)
    seconds = len(audio.frame_data) / max(1, audio.sample_rate * audio.sample_width)
    if not alternatives and seconds >= 0.8 and SPEECH_LANGUAGE_FALLBACK and SPEECH_LANGUAGE_FALLBACK != language:
        try:
            alternatives = _alternatives(_recognizer.recognize_google(audio_loud, language=SPEECH_LANGUAGE_FALLBACK, show_all=True))
        except (sr.UnknownValueError, sr.RequestError):
            alternatives = []
    if not alternatives:
        return _no_words(audio)
    _calibration["misses"] = 0
    return _choose(alternatives)


_UNFINISHED = {"to", "a", "an", "the", "and", "or", "of", "for", "from", "with", "my", "your", "in", "on", "at", "by", "if", "is",
               "are", "into", "about", "as", "than", "then", "so", "but", "can", "could", "would", "will", "what", "how", "why",
               "when", "where", "who", "which", "also", "just", "remove", "delete", "add", "open", "show", "tell", "make", "create",
               "set", "take", "call", "find", "search", "write", "erase", "turn", "give", "send", "last", "first", "next", "previous",
               "latest", "newest", "oldest", "second", "third", "every", "some", "any"}       # (not "it", "me", "you", "please"...:
                                                                                                          # "what time is it" is finished)


def _unfinished(text):
    """True when a phrase ends in the middle of a thought ("can you add a", "remove the last"), so the rest is probably coming."""
    words = text.lower().split()
    return not words or words[-1] in _UNFINISHED or words[-1].isdigit() and len(words) == 1


def _hear(language, timeout, phrase_time_limit):
    """One attempt to hear a phrase by voice.

    Returns the lowercase words, None if nothing was understood, or "" if Google's speech service couldn't be
    reached. Raises _VoiceUnavailable if the microphone itself fails.

    A phrase that stops in the middle of a thought ("can you add a") is not the end: the microphone keeps listening for the rest.
    """
    if not _ensure_ready():
        raise _VoiceUnavailable("The microphone isn't working.")
    _keep_open()
    audio = _capture(timeout, phrase_time_limit)
    if audio is None:
        _release_when_idle()
        return None
    if not _owner(audio):
        _release_when_idle()
        return ""                                    # heard, but not the owner's voice: nothing is done with it
    text = _recognize(audio, language)
    for _ in range(MAX_CONTINUATIONS):
        if not text or not _unfinished(text):
            break
        print(f": ({text!r} sounds unfinished, so I'm still listening...)")
        more_audio = _capture(CONTINUE_WAIT, phrase_time_limit)
        if more_audio is not None and not _owner(more_audio):
            break
        more = _recognize(more_audio, language) if more_audio is not None else None
        if not more:
            break
        text = f"{text} {more}"
    _release_when_idle()
    if text:
        print(f": You Said: {text}")
    return text.lower() if text else text


def listen(language=LANGUAGE, timeout=10, phrase_time_limit=8):
    """Return one spoken or typed phrase, or "" if nothing was understood.

    Spoken phrases come back lowercase; typed ones keep the capitals they were typed with.
    """
    global _unheard
    if _text_mode:
        return _type_prompt()
    try:
        heard = _hear(language, timeout, phrase_time_limit)
    except _VoiceUnavailable as e:
        return _switch_to_typing(str(e))
    if heard is None:
        return _unheard_try()
    if heard:
        _unheard = 0
    return heard


def listen_voice(language=LANGUAGE, timeout=10, phrase_time_limit=8):
    """Listen once by voice and never touch the keyboard (the GUI has no console to type into).

    Returns the lowercase words, or "" if nothing was understood. Raises MicrophoneError if the
    microphone cannot be used.
    """
    try:
        return _hear(language, timeout, phrase_time_limit) or ""
    except _VoiceUnavailable as e:
        raise MicrophoneError(str(e)) from None


# ---------------------------------------------------------------- health check

def windows_mic_permissions():
    """The Windows microphone privacy switches: {'system-wide'|'your account'|'desktop apps': 'Allow'|'Deny'|None}."""
    try:
        import winreg
    except ImportError:
        return {}
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    spots = {"system-wide": (winreg.HKEY_LOCAL_MACHINE, base),
             "your account": (winreg.HKEY_CURRENT_USER, base),
             "desktop apps": (winreg.HKEY_CURRENT_USER, base + r"\NonPackaged")}
    found = {}
    for label, (hive, path) in spots.items():
        try:
            with winreg.OpenKey(hive, path) as handle:
                found[label] = winreg.QueryValueEx(handle, "Value")[0]
        except OSError:
            found[label] = None
    return found


def _quick_hints():
    """Short, targeted advice shown whenever voice falls back to typing."""
    hints = []
    denied = [label for label, value in windows_mic_permissions().items() if value == "Deny"]
    if denied:
        hints.append("Windows is blocking microphone access (" + ", ".join(denied) + "). Turn it on in "
                     "Settings > Privacy & security > Microphone, including 'Let desktop apps access your microphone'.")
    try:
        if not winmm_mic.list_devices():
            hints.append("Windows reports no microphone at all - check it is plugged in and enabled "
                         "(Settings > System > Sound > Input).")
    except MicrophoneError:
        pass
    hints.append("Run 'python microphone.py' for a full step-by-step check of the voice chain.")
    return hints


def _bar(level):
    return "#" * min(level // 25, 50)


def _record(source, seconds, show_live=False):
    """Read `seconds` of audio; return (raw bytes, [level per chunk])."""
    raw, levels = bytearray(), []
    for _ in range(max(1, int(seconds * source.SAMPLE_RATE / source.CHUNK))):
        chunk = source.stream.read(source.CHUNK)
        raw.extend(chunk)
        level = winmm_mic.rms(chunk)
        levels.append(level)
        if show_live:
            print(f"\r    level {level:5d} {_bar(level):<50}", end="", flush=True)
    if show_live:
        print()
    return bytes(raw), levels


def diagnose(only_backend=None, speak_test=True):
    """Step-by-step health check of the voice chain. Returns True if everything passed."""
    problems = []

    def line(tag, text):
        print(f"  [{tag:^4}] {text}")

    print("== Jarvis microphone check ==")
    line("INFO", f"Python {sys.version.split()[0]}, INPUT_MODE={INPUT_MODE}, MIC_BACKEND={MIC_BACKEND}, "
                 f"MIC_DEVICE={MIC_DEVICE or '(Windows default)'}")

    print("1) Windows microphone privacy")
    permissions = windows_mic_permissions()
    for label, value in permissions.items():
        if value == "Deny":
            line("FAIL", f"{label}: access DENIED")
            problems.append("Turn microphone access on in Settings > Privacy & security > Microphone "
                            "(and 'Let desktop apps access your microphone').")
        else:
            line("OK" if value == "Allow" else "INFO", f"{label}: {value or 'not set (defaults apply)'}")

    print("1b) Windows microphone volume")
    try:
        import audio_levels
        volume, muted = audio_levels.state()
        advice = audio_levels.advice(volume, muted)
        line("WARN" if advice else "OK", f"input volume {volume} percent, {'MUTED' if muted else 'not muted'}")
        if advice:
            problems.append(advice + " To fix it now, run:  python audio_levels.py --mic 80")
    except Exception as e:                           # noqa: BLE001
        line("INFO", f"could not read the Windows microphone volume ({e})")

    print("2) Input devices")
    try:
        devices = winmm_mic.list_devices()
    except MicrophoneError as e:
        devices = []
        line("FAIL", str(e))
    for index, name in devices:
        line("INFO", f"winmm [{index}] {name}")
    if not devices:
        line("FAIL", "Windows reports no input device")
        problems.append("Plug in / enable a microphone (Settings > System > Sound > Input).")
    try:
        sd = _load_sounddevice()
        default_api = sd.query_hostapis(sd.default.hostapi)["name"]
        for index, info in enumerate(sd.query_devices()):
            if info["max_input_channels"] > 0 and info["hostapi"] == sd.default.hostapi:
                line("INFO", f"sounddevice [{index}] {info['name']} ({default_api})")
    except MicrophoneError as e:
        line("WARN", str(e))

    print("3) Capture backends (1.5 s each)")
    working = None
    for name in ([only_backend] if only_backend else list(BACKENDS)):
        try:
            source = _make(name, read_timeout=PROBE_TIMEOUT)
            with source as opened:
                _, levels = _record(opened, 1.5)
            line("OK", f"{name}: opened '{source.device_name}' at {source.SAMPLE_RATE} Hz; "
                       f"background level {sum(levels) // len(levels)} (peak {max(levels)})")
            working = working or (name, sum(levels) // len(levels))
        except Exception as e:
            line("FAIL", f"{name}: {e}")
    if not working:
        problems.append("No capture backend could record. See the messages above; Windows privacy and the "
                        "default input device are the usual causes.")

    if working and speak_test and sys.stdin and sys.stdin.isatty():
        name, background = working
        print(f"4) Your voice (using {name})")
        input("    Press Enter, then say a sentence like 'hey jarvis, what time is it' for 5 seconds... ")
        with _make(name, read_timeout=PROBE_TIMEOUT) as source:
            raw, levels = _record(source, 5, show_live=True)
            rate = source.SAMPLE_RATE
        peak = max(levels)
        top = sorted(levels)[int(len(levels) * 0.9)]
        floor = max(background, 4)
        if peak >= max(150, 4 * floor):
            line("OK", f"voice level is strong (peak {peak}, background {background})")
        elif peak >= max(60, 2 * floor):
            line("WARN", f"voice level is low (peak {peak}, background {background})")
            problems.append("Raise the microphone volume: Settings > System > Sound > Input > your microphone "
                            "> Volume (try 80-100), and check for a laptop mic-mute key.")
        else:
            line("FAIL", f"no speech detected (peak {peak}, 90th percentile {top}, background {background})")
            problems.append("Jarvis hears only background noise. Check the Input volume and mute switch in "
                            "Settings > System > Sound, and that the right microphone is the default input "
                            "(or set MIC_DEVICE in .env).")
        print("5) Speech recognition")
        recording = sr.AudioData(raw, rate, 2)
        if stt.available():
            started = time.time()
            try:
                line("OK", f"Whisper (on this PC) heard: {stt.transcribe(recording)!r} in {time.time() - started:.1f}s")
            except stt.SpeechRecognitionFailed as error:
                line("WARN", f"Whisper could not be used: {error}")
        else:
            line("INFO", "Whisper is not set up (python stt.py --download), so Google is used")
        if STT_ENGINE != "whisper":
            try:
                heard = sr.Recognizer().recognize_google(recording, language=LANGUAGE)
                line("OK", f"Google heard: {heard!r}")
            except sr.UnknownValueError:
                line("WARN", "Google could not understand that recording (speak closer / louder, reduce noise)")
            except sr.RequestError as e:
                line("FAIL" if not stt.available() else "WARN", f"cannot reach Google's speech service: {e}")
                if not stt.available():
                    problems.append("Check your internet connection, firewall or proxy - the speech service is online-only.")
    elif working and speak_test:
        line("INFO", "skipping the 'say a sentence' step (this window cannot take typed input)")

    print("== Result ==")
    if problems:
        for text in dict.fromkeys(problems):
            print(f"  -> {text}")
        return False
    print("  Everything checked is working.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check that Jarvis can hear you.")
    parser.add_argument("--backend", choices=sorted(BACKENDS), help="test only this capture backend")
    parser.add_argument("--diagnose", action="store_true", help="run the full check (this is the default)")
    parser.add_argument("--no-speech", action="store_true", help="skip the 'say a sentence' step")
    parser.add_argument("--list", action="store_true", help="just list the input devices")
    args = parser.parse_args()
    if args.list:
        for index, name in winmm_mic.list_devices():
            print(f"[{index}] {name}")
        sys.exit(0)
    sys.exit(0 if diagnose(args.backend, speak_test=not args.no_speech) else 1)
