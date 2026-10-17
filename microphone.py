"""Microphone input for Jarvis.

listen() hears one phrase and returns it as lowercase text. With INPUT_MODE=text
in .env (or when no microphone exists) commands are typed instead.

Microphone works with or without PyAudio. PyAudio has no build for Python 3.14,
so when it is missing we record through sounddevice instead.
"""
import queue
import sys

import speech_recognition as sr
from config import INPUT_MODE

READ_TIMEOUT = 5  # seconds to wait for audio before deciding the mic is dead


class MicrophoneError(Exception):
    """The microphone opened but delivered no audio."""


_microphone_class = None


def _build_microphone_class():
    """Import an audio backend and return a Microphone class, only when voice is actually used.

    This is deferred so merely importing microphone.py never loads PyAudio or
    sounddevice. Importing sounddevice runs PortAudio's Pa_Initialize(), which can
    block for seconds (or hang on a stuck audio driver) while it enumerates devices -
    in text mode we must never pay that cost or risk that hang.
    """
    try:
        import pyaudio  # noqa: F401
        return sr.Microphone
    except ImportError:
        pass

    import sounddevice as sd

    class _Stream:
        """Reads audio from a callback-fed queue so a stuck driver times out instead of blocking forever.

        A blocking sd.RawInputStream.read() froze inside PortAudio's C call (surfacing
        as a KeyboardInterrupt) when the device opened but never produced samples. In
        callback mode PortAudio pushes audio on its own thread; read() pulls from the
        queue with a timeout.
        """
        def __init__(self, raw, audio_queue, width):
            self.raw = raw
            self.queue = audio_queue
            self.width = width
            self.buffer = bytearray()

        def read(self, size):
            needed = size * self.width
            while len(self.buffer) < needed:
                try:
                    self.buffer.extend(self.queue.get(timeout=READ_TIMEOUT))
                except queue.Empty:
                    raise MicrophoneError("the microphone delivered no audio")
            chunk = bytes(self.buffer[:needed])
            del self.buffer[:needed]
            return chunk

        def close(self):
            try:
                self.raw.stop()
                self.raw.close()
            except Exception:
                pass

    class _SoundDeviceMicrophone(sr.AudioSource):
        def __init__(self, device_index=None, sample_rate=None, chunk_size=1024):
            if sample_rate is None:
                sample_rate = int(sd.query_devices(device_index, "input")["default_samplerate"])
            self.device_index = device_index
            self.SAMPLE_RATE = sample_rate
            self.SAMPLE_WIDTH = 2  # 16-bit audio
            self.CHUNK = chunk_size
            self.stream = None

        def __enter__(self):
            audio_queue = queue.Queue()

            def callback(indata, frames, time_info, status):
                audio_queue.put(bytes(indata))

            # Open and read on the same (PortAudio) thread via the callback - never across threads.
            raw = sd.RawInputStream(samplerate=self.SAMPLE_RATE, blocksize=self.CHUNK,
                                    device=self.device_index, channels=1, dtype="int16",
                                    callback=callback)
            raw.start()
            self.stream = _Stream(raw, audio_queue, self.SAMPLE_WIDTH)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            if self.stream is not None:
                self.stream.close()
            self.stream = None

    return _SoundDeviceMicrophone


def Microphone(*args, **kwargs):
    """Create a microphone, loading the audio backend on first use (never at import)."""
    global _microphone_class
    if _microphone_class is None:
        _microphone_class = _build_microphone_class()
    return _microphone_class(*args, **kwargs)


_recognizer = None
_text_mode = INPUT_MODE == "text"
_unheard = 0                 # consecutive tries that produced no understood words
UNHEARD_LIMIT = 5            # after this many, give up on the mic and switch to typing


_typed_hint_shown = False


def _type_prompt():
    global _typed_hint_shown
    if not _typed_hint_shown:
        if not sys.stdin or not sys.stdin.isatty():
            # Non-interactive stdin: input() would hit EOF immediately. This is the usual cause
            # of "it prints the prompt then exits" - the program is running where you can't type.
            print(": This window can't accept typed input, so Jarvis has nowhere to read commands from.\n"
                  ": That happens with the 'Run' button when it uses the Output pane (or Code Runner).\n"
                  ": Open a real terminal - in VS Code press Ctrl+` for the integrated terminal - and run:\n"
                  ":     python Startup.py\n"
                  ": then type your commands there. (Or set INPUT_MODE=voice in .env to use the mic.)")
            raise SystemExit(1)
        print(": Typed mode. Type a command and press Enter. Type 'quit' to stop Jarvis.")
        _typed_hint_shown = True
    try:
        return input("You (type): ").strip().lower()
    except EOFError:
        # No traceback - a clean stop. SystemExit isn't caught by the feature loops' except Exception.
        print("\n: Keyboard input closed, so I'm stopping. Run 'python Startup.py' in a terminal to type to me.")
        raise SystemExit(0)
    except KeyboardInterrupt:
        print("\n: Goodbye, sir.")
        raise SystemExit(0)


def _switch_to_typing(reason):
    global _text_mode
    _text_mode = True
    print(f": {reason}\n"
          ": Switching to typed commands. Raise the mic volume in Windows Sound settings\n"
          ": and test it with 'python microphone.py', then it will use voice again.")
    return _type_prompt()


def _unheard_try():
    """Count one try that heard nothing usable; switch to typing once too many pile up."""
    global _unheard
    _unheard += 1
    if _unheard >= UNHEARD_LIMIT:
        return _switch_to_typing("I can't make out any speech from the microphone.")
    return ""


def listen(language="en-pk", timeout=10, phrase_time_limit=8):
    """Return one spoken (or typed) phrase as lowercase text, or "" if nothing was understood."""
    global _recognizer, _unheard, _text_mode
    if not _text_mode and _recognizer is None:
        print(": Starting the microphone, stay quiet for a second...")
        try:
            _recognizer = sr.Recognizer()
            _recognizer.pause_threshold = 1
            with Microphone() as source:
                _recognizer.adjust_for_ambient_noise(source, duration=1)
            print(": Microphone ready. Say a wake word like 'hey jarvis'.")
        except Exception as e:
            return _switch_to_typing(f"The microphone isn't working ({e}).")
    if _text_mode:
        return _type_prompt()

    r = _recognizer
    try:
        with Microphone() as source:
            print(": Listening.....")
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
    except sr.WaitTimeoutError:
        return _unheard_try()
    except Exception as e:
        return _switch_to_typing(f"The microphone stopped working ({e}).")
    try:
        print(": Recognizing.....")
        query = r.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        return _unheard_try()
    except sr.RequestError as e:
        print(f": Speech service unavailable, check your internet ({e})")
        return ""
    _unheard = 0
    print(f": You Said: {query}")
    return query.lower()


if __name__ == "__main__":
    # Mic check: run "python microphone.py" and talk.
    import audioop
    r = sr.Recognizer()
    with Microphone() as source:
        print("Stay quiet for 1 second...")
        r.adjust_for_ambient_noise(source, duration=1)
        print(f"Background threshold: {r.energy_threshold:.0f}. Now talk for 5 seconds:")
        per_line = max(1, int(0.5 * source.SAMPLE_RATE / source.CHUNK))
        for _ in range(10):
            level = max(audioop.rms(source.stream.read(source.CHUNK), source.SAMPLE_WIDTH)
                        for _ in range(per_line))
            print(f"  level {level:5d} " + "#" * min(level // 25, 60))
        print("Now say a sentence...")
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=6)
            print("Google heard:", r.recognize_google(audio, language="en-pk"))
        except sr.WaitTimeoutError:
            print("No speech detected - raise the mic volume in Windows Sound settings.")
        except sr.UnknownValueError:
            print("Heard something but could not understand it.")
