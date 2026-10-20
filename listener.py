"""The always-on ear for when Jarvis is asleep: waits for "hey Jarvis" and/or a clap pattern, and tells the window or terminal to wake him.

While the window is open and Jarvis is asleep, WakeListener holds the microphone (16 kHz, 80 ms at a time) and feeds every piece
to the clap detector (clap.py) and the wake-word detector (wakeword.py). Nothing is recorded, nothing is sent anywhere, and the
sound is thrown away as it is looked at (apart from the last three seconds, kept only to check whose voice said the wake word).

Waking him is the same as pressing START: he still asks for the password. A clap cannot be checked against your voice, so it only
ever opens that password question. When a voice print exists (enroll_voice.py), "hey Jarvis" must be in your voice too.

The listener lets go of the microphone the moment it wakes him (the session opens it for itself) and the window starts it again
when he goes back to sleep.
"""
import collections
import queue
import threading
import time

import numpy as np

import clap
import speaker
import speech
import wakeword
from config import CLAP_COUNT, CLAP_SENSITIVITY, CLAP_WAKE, MIC_DEVICE, WAKE_SENSITIVITY, WAKE_WORD

RATE = 16000
BLOCK = wakeword.FRAME            # 80 ms
KEEP_SECONDS = 3                  # of sound kept to check the voice that said the wake word
COOLDOWN = 3.0                    # after waking him, ignore everything for this long
OPEN_TIMEOUT = 5                  # seconds a microphone that opens but delivers nothing is given


def wanted():
    """What the listener would listen for, from the settings and what is installed: a list of "wake word" / "clap"."""
    found = []
    if WAKE_WORD and wakeword.available():
        found.append("wake word")
    if CLAP_WAKE:
        found.append("clap")
    return found


def hint():
    """The sentence the window shows while he sleeps and listens ("" when nothing is being listened for)."""
    parts = []
    if "wake word" in wanted():
        parts.append("say 'hey Jarvis'")
    if "clap" in wanted():
        parts.append(f"clap {CLAP_COUNT} time{'' if CLAP_COUNT == 1 else 's'}")
    return ("To wake me, " + " or ".join(parts) + ", or press START.") if parts else ""


def microphone_blocks(stop=None, device=MIC_DEVICE):
    """Yield the microphone as pieces of BLOCK 16 kHz samples (16-bit integers) until ``stop`` (a threading.Event) is set.

    The sound arrives through a callback into a queue and is read with a timeout, so a driver that stalls ends this with an
    error instead of freezing the thread (the first version of the voice code froze inside a blocking read)."""
    import microphone
    sd = microphone._load_sounddevice()
    chosen = microphone._pick_sd_device(sd, device or None)
    audio = queue.Queue(maxsize=64)

    def callback(indata, frames, time_info, status):
        try:
            audio.put_nowait(bytes(indata))
        except queue.Full:
            pass

    try:
        stream = sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, device=chosen, channels=1, dtype="int16", callback=callback)
        stream.start()
    except Exception as error:                              # noqa: BLE001 - whatever PortAudio says, it comes out as one message
        raise microphone.MicrophoneError(f"the microphone could not be opened for listening ({error})") from error
    try:
        while stop is None or not stop.is_set():
            try:
                yield np.frombuffer(audio.get(timeout=OPEN_TIMEOUT), dtype=np.int16)
            except queue.Empty:
                raise microphone.MicrophoneError(f"the microphone delivered no sound for {OPEN_TIMEOUT} s") from None
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:                                   # noqa: BLE001
            pass


class WakeListener:
    def __init__(self, on_wake, wake_word=None, claps=None, blocks=None, verify=None, cooldown=COOLDOWN):
        """``on_wake(reason)`` is called from the listener's own thread with "wake word" or "clap".

        ``wake_word`` and ``claps`` are the detectors (made from the settings when not given); ``blocks`` is a function that gives
        the pieces of sound (the microphone when not given); ``verify(samples) -> bool`` checks whose voice said the wake word."""
        self.on_wake = on_wake
        self._wake_word, self._claps = wake_word, claps
        self._blocks = blocks or microphone_blocks
        self._verify = verify or self._same_voice
        self.cooldown = cooldown
        self._stop = threading.Event()
        self._thread = None
        self._woke_at = -1e9
        self.error = ""                       # why it is not listening, in words for the user ("" when it is)
        self.listening = threading.Event()   # set once the microphone is open

    # ---- what is listened for

    def _detectors(self):
        if self._wake_word is None and WAKE_WORD and wakeword.available():
            try:
                self._wake_word = wakeword.WakeWordDetector(WAKE_SENSITIVITY)
            except Exception as error:                      # noqa: BLE001 - claps can still work
                self.error = f"the wake word could not be loaded ({error})"
        if self._claps is None and CLAP_WAKE:
            self._claps = clap.ClapDetector(CLAP_COUNT, CLAP_SENSITIVITY)
        return self._wake_word, self._claps

    # ---- running

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Begin listening in the background. False if there is nothing to listen for."""
        if self.running:
            return True
        wake_word, claps = self._detectors()
        if wake_word is None and claps is None:
            self.error = self.error or "wake word and claps are both switched off (or not installed)"
            return False
        self._stop.clear()
        self.listening.clear()
        self._thread = threading.Thread(target=self._run, args=(wake_word, claps), name="wake-listener", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout=3.0):
        """Stop listening and let go of the microphone (returns when it is let go, or after ``timeout`` seconds)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self, wake_word, claps):
        recent = collections.deque(maxlen=KEEP_SECONDS * RATE // BLOCK)
        try:
            for block in self._blocks(self._stop):
                self.listening.set()
                if self._stop.is_set():
                    break
                recent.append(block)
                if speech.is_speaking():                    # his own voice must not wake him
                    continue
                if time.monotonic() - self._woke_at < self.cooldown:
                    continue
                reason = None
                if claps is not None and claps.feed(block):
                    reason = "clap"
                if wake_word is not None and wake_word.feed(block) and reason is None:
                    reason = "wake word"
                if reason is None:
                    continue
                if reason == "wake word" and not self._verify(np.concatenate(list(recent))):
                    print(": (I heard 'hey Jarvis', but not in your voice, so I'm staying asleep)")
                    continue
                self._woke_at = time.monotonic()
                self.on_wake(reason)
                if claps is not None:
                    claps.reset()
                if wake_word is not None:
                    wake_word.reset()
        except Exception as error:                          # noqa: BLE001 - a microphone that fails must not take the program down
            self.error = f"I can't listen for the wake word: {error}"
        finally:
            self.listening.clear()

    @staticmethod
    def _same_voice(samples):
        """Was the wake phrase in the owner's voice? (True when there is no voice lock.)"""
        if not speaker.lock_active():
            return True
        import speech_recognition as sr
        verdict = speaker.accept(sr.AudioData(samples.tobytes(), RATE, 2), relaxed=True)
        return verdict.ok


def wait_for_wake(stop=None):
    """For the terminal: block until Jarvis is woken, and return "wake word" or "clap" (None if nothing can be listened for)."""
    woke = queue.Queue()
    heard = WakeListener(woke.put)
    if not heard.start():
        return None
    try:
        while stop is None or not stop.is_set():
            try:
                return woke.get(timeout=0.5)
            except queue.Empty:
                if not heard.running:
                    return None                             # the microphone failed: the caller falls back to the old way
    finally:
        heard.stop()
    return None
