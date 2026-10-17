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

import speech_recognition as sr

import winmm_mic
from config import INPUT_MODE, MIC_BACKEND, MIC_DEVICE
from winmm_mic import MicrophoneError, WinMMMicrophone

READ_TIMEOUT = 5       # seconds without audio before a backend is declared dead
PROBE_TIMEOUT = 3      # the same, while checking a backend before first use
SD_INIT_TIMEOUT = 6    # seconds sounddevice may take to start before we give up on it
UNHEARD_LIMIT = 5      # this many empty tries in a row -> switch to typed input
LANGUAGE = "en-pk"


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

    def __init__(self, raw, audio_queue, sample_width, timeout):
        self.raw, self.queue, self.width, self.timeout = raw, audio_queue, sample_width, timeout
        self.buffer = bytearray()

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
        self.stream = _SoundDeviceStream(raw, audio_queue, self.SAMPLE_WIDTH, self.read_timeout)
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
        return input("You (type): ").strip().lower()
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
    _failed.clear()
    _active, _recognizer, _unheard = None, None, 0
    _text_mode = INPUT_MODE == "text"


# ---------------------------------------------------------------- listening

def _ensure_ready():
    """First use: pick a backend and calibrate for background noise. True if voice is usable."""
    global _recognizer
    if _recognizer is not None:
        return True
    print(": Starting the microphone, stay quiet for a second...")
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1
    for _ in range(2):                  # the second pass runs after a failover
        try:
            with Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
            _recognizer = recognizer
            print(f": Microphone ready [{mic_status()}]. Say a wake word like 'hey jarvis'.")
            return True
        except (MicrophoneError, OSError) as e:
            print(f": Microphone problem: {e}")
            if not _failover(e):
                break
    return False


def listen(language=LANGUAGE, timeout=10, phrase_time_limit=8):
    """Return one spoken (or typed) phrase as lowercase text, or "" if nothing was understood."""
    global _unheard
    if not _text_mode and not _ensure_ready():
        return _switch_to_typing("The microphone isn't working.")
    if _text_mode:
        return _type_prompt()

    audio = None
    for attempt in range(2):
        try:
            with Microphone() as source:
                print(": Listening.....")
                audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            break
        except sr.WaitTimeoutError:
            return _unheard_try()
        except (MicrophoneError, OSError) as e:
            if attempt == 0 and _failover(e):
                continue                  # the other backend works: try the same listen again
            return _switch_to_typing(f"The microphone stopped working ({e}).")
    try:
        print(": Recognizing.....")
        query = _recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        return _unheard_try()
    except sr.RequestError as e:
        print(f": Speech service unavailable, check your internet ({e})")
        return ""
    _unheard = 0
    print(f": You Said: {query}")
    return query.lower()


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
        print("5) Speech recognition (Google)")
        try:
            heard = sr.Recognizer().recognize_google(sr.AudioData(raw, rate, 2), language=LANGUAGE)
            line("OK", f"Google heard: {heard!r}")
        except sr.UnknownValueError:
            line("WARN", "Google could not understand that recording (speak closer / louder, reduce noise)")
        except sr.RequestError as e:
            line("FAIL", f"cannot reach Google's speech service: {e}")
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
