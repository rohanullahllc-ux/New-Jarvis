"""Dependency-free microphone capture for Windows.

Pure Python: ``ctypes`` against ``winmm.dll``, the multimedia library every Windows
install already ships with (the ``waveIn*`` API). No PortAudio, PyAudio, sounddevice,
CFFI or compiler is involved, so it keeps working whatever Python version is installed
- there is no wheel that can be "missing" for a new Python release.

It plugs into ``speech_recognition`` as an ``AudioSource``::

    with WinMMMicrophone() as source:
        audio = recognizer.listen(source)

Run ``python winmm_mic.py`` to list the input devices and take a 1-second level reading.

Notes
-----
* MME is Windows' legacy audio API: device names are cut to 31 characters and there is
  no exclusive / ultra-low-latency mode. Neither matters for speech.
* Audio is requested as 16-bit mono PCM; the Windows audio engine converts from whatever
  the hardware natively delivers.
"""
import array
import ctypes
import ctypes.wintypes as wt
import math
import queue
import sys
import threading

try:  # speech_recognition is only needed to use this as an AudioSource
    import speech_recognition as _sr
    _AudioSource = _sr.AudioSource
except ImportError:  # pragma: no cover - lets the module work standalone (device listing, level test)
    _AudioSource = object

WAVE_MAPPER = 0xFFFFFFFF          # "the default input device"
CALLBACK_EVENT = 0x00050000
WHDR_DONE = 0x00000001
WAVERR_BADFORMAT = 32
SAMPLE_WIDTH = 2                  # 16-bit samples
_FALLBACK_RATES = (16000, 44100, 48000, 22050, 11025, 8000)


class MicrophoneError(Exception):
    """The microphone could not be opened, or opened but delivered no audio."""


# ---------------------------------------------------------------- Win32 plumbing

class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD), ("nSamplesPerSec", wt.DWORD),
                ("nAvgBytesPerSec", wt.DWORD), ("nBlockAlign", wt.WORD),
                ("wBitsPerSample", wt.WORD), ("cbSize", wt.WORD)]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wt.DWORD),
                    ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_size_t),
                    ("dwFlags", wt.DWORD), ("dwLoops", wt.DWORD),
                    ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


class WAVEINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                ("szPname", ctypes.c_wchar * 32), ("dwFormats", wt.DWORD),
                ("wChannels", wt.WORD), ("wReserved1", wt.WORD)]


_HANDLE = ctypes.c_void_p
_libs = None


def _api():
    """Load winmm/kernel32 once (lazily, so importing this module never touches Windows audio)."""
    global _libs
    if _libs is None:
        if sys.platform != "win32":
            raise MicrophoneError("the winmm backend only works on Windows")
        winmm = ctypes.WinDLL("winmm")
        kernel32 = ctypes.WinDLL("kernel32")

        winmm.waveInGetNumDevs.restype = wt.UINT
        winmm.waveInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(WAVEINCAPSW), wt.UINT]
        winmm.waveInGetDevCapsW.restype = wt.UINT
        winmm.waveInGetErrorTextW.argtypes = [wt.UINT, ctypes.c_wchar_p, wt.UINT]
        winmm.waveInGetErrorTextW.restype = wt.UINT
        winmm.waveInOpen.argtypes = [ctypes.POINTER(_HANDLE), wt.UINT, ctypes.POINTER(WAVEFORMATEX),
                                     ctypes.c_size_t, ctypes.c_size_t, wt.DWORD]
        winmm.waveInOpen.restype = wt.UINT
        for name in ("waveInPrepareHeader", "waveInAddBuffer", "waveInUnprepareHeader"):
            fn = getattr(winmm, name)
            fn.argtypes = [_HANDLE, ctypes.POINTER(WAVEHDR), wt.UINT]
            fn.restype = wt.UINT
        for name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
            fn = getattr(winmm, name)
            fn.argtypes = [_HANDLE]
            fn.restype = wt.UINT

        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        kernel32.CreateEventW.restype = _HANDLE
        kernel32.WaitForSingleObject.argtypes = [_HANDLE, wt.DWORD]
        kernel32.WaitForSingleObject.restype = wt.DWORD
        kernel32.SetEvent.argtypes = [_HANDLE]
        kernel32.SetEvent.restype = wt.BOOL
        kernel32.CloseHandle.argtypes = [_HANDLE]
        kernel32.CloseHandle.restype = wt.BOOL
        _libs = (winmm, kernel32)
    return _libs


def _error_text(code):
    winmm, _ = _api()
    buf = ctypes.create_unicode_buffer(256)
    if winmm.waveInGetErrorTextW(code, buf, 256) == 0 and buf.value:
        return f"{buf.value} (code {code})"
    return f"Windows audio error {code}"


# ---------------------------------------------------------------- devices

def list_devices():
    """Return ``[(index, name), ...]`` for every input device winmm can see."""
    winmm, _ = _api()
    devices = []
    for index in range(winmm.waveInGetNumDevs()):
        caps = WAVEINCAPSW()
        if winmm.waveInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            devices.append((index, caps.szPname))
    return devices


def resolve_device(device=None):
    """Turn a user setting into ``(winmm_device_id, display_name)``.

    ``None`` / ``""`` -> the Windows default input; an integer (or digit string) -> that
    index; any other text -> the first device whose name contains it (case-insensitive).
    """
    if device is None or str(device).strip() == "":
        return WAVE_MAPPER, "Windows default input"
    devices = list_devices()
    text = str(device).strip()
    if text.isdigit():
        index = int(text)
        for i, name in devices:
            if i == index:
                return i, name
        raise MicrophoneError(f"there is no input device number {index} (available: {_describe(devices)})")
    for i, name in devices:
        if text.lower() in name.lower():
            return i, name
    raise MicrophoneError(f"no input device name contains {text!r} (available: {_describe(devices)})")


def _describe(devices):
    return ", ".join(f"{i}: {n}" for i, n in devices) or "none"


# ---------------------------------------------------------------- the stream

class WinMMStream:
    """An open recording stream. ``read(frames)`` returns exactly ``frames`` 16-bit mono samples."""

    BUFFERS = 8            # ring of reusable capture buffers
    MAX_QUEUED_CHUNKS = 256  # ~16 s of audio at 1024-frame chunks; older audio is dropped beyond this

    def __init__(self, device_id, rate, chunk, read_timeout):
        self._winmm, self._kernel = _api()
        self.rate = rate
        self._read_timeout = read_timeout
        self._chunk_bytes = chunk * SAMPLE_WIDTH
        self._handle = _HANDLE()
        self._event = None
        self._buffers = []        # (ctypes buffer, WAVEHDR) pairs, kept alive here
        self._prepared = []
        self._queue = queue.Queue(maxsize=self.MAX_QUEUED_CHUNKS)
        self._pending = bytearray()
        self._stop = threading.Event()
        self._thread = None
        self._closed = False
        try:
            self._open(device_id, rate)
        except Exception:
            self.close()
            raise

    def _open(self, device_id, rate):
        winmm, kernel = self._winmm, self._kernel
        self._event = kernel.CreateEventW(None, False, False, None)
        if not self._event:
            raise MicrophoneError("could not create a Windows event object")
        tried = []
        for candidate in (rate, *[r for r in _FALLBACK_RATES if r != rate]):
            tried.append(candidate)
            fmt = WAVEFORMATEX(1, 1, candidate, candidate * SAMPLE_WIDTH, SAMPLE_WIDTH, 16, 0)
            code = winmm.waveInOpen(ctypes.byref(self._handle), device_id, ctypes.byref(fmt),
                                    self._event, 0, CALLBACK_EVENT)
            if code == 0:
                self.rate = candidate
                break
            if code != WAVERR_BADFORMAT:
                raise MicrophoneError(f"could not open the microphone: {_error_text(code)}")
        else:
            raise MicrophoneError(f"the microphone accepts none of the sample rates {tried}")

        for _ in range(self.BUFFERS):
            data = ctypes.create_string_buffer(self._chunk_bytes)
            hdr = WAVEHDR()
            hdr.lpData = ctypes.addressof(data)
            hdr.dwBufferLength = self._chunk_bytes
            code = winmm.waveInPrepareHeader(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            if code:
                raise MicrophoneError(f"could not prepare an audio buffer: {_error_text(code)}")
            self._prepared.append(hdr)
            code = winmm.waveInAddBuffer(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            if code:
                raise MicrophoneError(f"could not queue an audio buffer: {_error_text(code)}")
            self._buffers.append((data, hdr))

        code = winmm.waveInStart(self._handle)
        if code:
            raise MicrophoneError(f"could not start recording: {_error_text(code)}")
        self._thread = threading.Thread(target=self._pump, name="winmm-capture", daemon=True)
        self._thread.start()

    def _pump(self):
        """Move finished buffers into the queue, strictly in the order the driver fills them."""
        winmm, kernel = self._winmm, self._kernel
        index = 0
        while not self._stop.is_set():
            kernel.WaitForSingleObject(self._event, 100)   # wakes when a buffer is done (or every 100 ms)
            while not self._stop.is_set():
                data, hdr = self._buffers[index]
                if not hdr.dwFlags & WHDR_DONE:
                    break
                chunk = ctypes.string_at(ctypes.addressof(data), hdr.dwBytesRecorded)
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:                       # nobody is reading: drop the oldest audio
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(chunk)
                winmm.waveInAddBuffer(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
                index = (index + 1) % len(self._buffers)

    def read(self, frames):
        needed = frames * SAMPLE_WIDTH
        while len(self._pending) < needed:
            try:
                self._pending.extend(self._queue.get(timeout=self._read_timeout))
            except queue.Empty:
                raise MicrophoneError(f"the microphone delivered no audio for {self._read_timeout:g} s") from None
        data = bytes(self._pending[:needed])
        del self._pending[:needed]
        return data

    def close(self):
        """Release everything. Safe to call twice, and after a partly failed open."""
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        winmm, kernel = self._winmm, self._kernel
        if self._thread is not None:
            if self._event:
                kernel.SetEvent(self._event)              # wake the capture thread now instead of in <=100 ms
            self._thread.join(2)
        if self._handle:
            winmm.waveInStop(self._handle)
            winmm.waveInReset(self._handle)           # hands every queued buffer back
            for hdr in self._prepared:
                winmm.waveInUnprepareHeader(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            winmm.waveInClose(self._handle)
            self._handle = _HANDLE()
        if self._event:
            kernel.CloseHandle(self._event)
            self._event = None


class WinMMMicrophone(_AudioSource):
    """A ``speech_recognition`` audio source backed by :class:`WinMMStream`."""

    backend = "winmm"

    def __init__(self, device_index=None, sample_rate=16000, chunk_size=1024, read_timeout=5.0):
        self._device_id, self.device_name = resolve_device(device_index)
        self.device_index = device_index
        self.SAMPLE_RATE = sample_rate or 16000
        self.SAMPLE_WIDTH = SAMPLE_WIDTH
        self.CHUNK = chunk_size
        self.read_timeout = read_timeout
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise MicrophoneError("this microphone is already open")
        self.stream = WinMMStream(self._device_id, self.SAMPLE_RATE, self.CHUNK, self.read_timeout)
        self.SAMPLE_RATE = self.stream.rate
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def rms(data):
    """Root-mean-square level of 16-bit PCM bytes (no audioop needed)."""
    samples = array.array("h", data[: len(data) // 2 * 2])
    if not samples:
        return 0
    return int(math.sqrt(sum(s * s for s in samples) / len(samples)))


if __name__ == "__main__":
    print("Input devices seen by winmm:")
    for i, name in list_devices():
        print(f"  [{i}] {name}")
    with WinMMMicrophone() as mic:
        levels = [rms(mic.stream.read(mic.CHUNK)) for _ in range(int(mic.SAMPLE_RATE / mic.CHUNK))]
    print(f"Recorded ~1 s from '{mic.device_name}' at {mic.SAMPLE_RATE} Hz; "
          f"level min/avg/max = {min(levels)}/{sum(levels) // len(levels)}/{max(levels)}")
