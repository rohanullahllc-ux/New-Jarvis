"""What this PC is, and what is already installed: Windows, Python, memory, disk, internet, sound devices, the Visual C++ runtime,
Ollama, the Python packages and the downloaded models. Every probe returns plain values and never raises: a probe that cannot
find out says so ("unknown") instead of stopping the wizard.

The wizard's decisions (how big a speech model to suggest, whether to offer the chat model) come from hardware_tier() below.
"""
import ctypes
import importlib.util
import os
import platform
import re
import shutil
import sys
import threading
from collections import namedtuple
from pathlib import Path

WINDOWS = os.name == "nt"

# Python module -> the pip package that provides it, and what it is for. "critical" ones stop Jarvis from starting at all.
PACKAGES = (
    # module,            pip package,              critical, what it is for
    ("dotenv",           "python-dotenv",           True,  "reading your settings"),
    ("requests",         "requests",                True,  "talking to the internet"),
    ("anthropic",        "anthropic",               True,  "the tools Jarvis uses"),
    ("psutil",           "psutil",                  True,  "reading the state of this PC"),
    ("PyQt5",            "PyQt5",                   True,  "the window"),
    ("speech_recognition", "SpeechRecognition",     True,  "listening"),
    ("sounddevice",      "sounddevice",             False, "the microphone (Windows' own method is the backup)"),
    ("comtypes",         "comtypes",                False, "the Windows voice"),
    ("pygame",           "pygame-ce",               False, "reminder sounds and the theme music"),
    ("numpy",            "numpy",                   True,  "sound and models"),
    ("scipy",            "scipy",                   False, "the clap detector and resampling"),
    ("faster_whisper",   "faster-whisper",          False, "hearing you offline (Whisper)"),
    ("piper",            "piper-tts",               False, "the natural voice"),
    ("openwakeword",     "openwakeword",            False, "\"hey Jarvis\""),
    ("sherpa_onnx",      "sherpa-onnx",             False, "knowing your voice from other people's"),
    ("sklearn",          "scikit-learn",            False, "his own trained language model"),
    ("joblib",           "joblib",                  False, "his own trained language model"),
    ("ollama",           "ollama",                  False, "chatting with the model on this PC"),
    ("ddgs",             "ddgs",                    False, "looking facts up"),
    ("keyboard",         "keyboard",                False, "pressing keys for you"),
    ("pynput",           "pynput",                  False, "mouse and keyboard control"),
    ("pyautogui",        "pyautogui",               False, "screenshots and clicking"),
    ("plyer",            "plyer",                   False, "desktop notifications"),
    ("deep_translator",  "deep-translator",         False, "translating"),
    ("pypdf",            "pypdf",                   False, "reading PDF books"),
    ("yt_dlp",           "yt-dlp",                  False, "downloading YouTube videos"),
    ("instaloader",      "instaloader",             False, "Instagram profile pictures"),
    ("cv2",              "opencv-contrib-python",   False, "the face check after the password"),
    ("customtkinter",    "customtkinter",           False, "the calculator, calendar and currency windows"),
    ("PIL",              "Pillow",                  False, "pictures"),
)
BY_MODULE = {module: (package, critical, purpose) for module, package, critical, purpose in PACKAGES}

Tier = namedtuple("Tier", "name stt_model ollama_models auto_max_mb preload note")
TIERS = {
    "light": Tier("light", "base.en", ("qwen2.5:1.5b",), 1600, False,
                  "A modest PC: the quick speech model and the small chat model keep him responsive."),
    "balanced": Tier("balanced", "base.en", ("qwen2.5:1.5b", "llama3.2:3b"), 2600, False,
                     "A middling PC: both chat models are comfortable; the bigger one writes a little better."),
    "strong": Tier("strong", "small.en", ("llama3.2:3b", "qwen2.5:1.5b"), 6000, True,
                   "A strong PC: the most accurate speech model and the bigger chat model, loaded at start-up."),
}


def _safely(function, default):
    try:
        return function()
    except Exception:                                     # noqa: BLE001 - a probe that fails just reports "unknown"
        return default


# ---------------------------------------------------------------- Python and Windows

def python_facts():
    info = sys.version_info
    path = str(sys.executable)
    return {
        "version": (info.major, info.minor, info.micro),
        "text": f"{info.major}.{info.minor}.{info.micro}",
        "executable": path,
        "bits": 64 if sys.maxsize > 2 ** 32 else 32,
        "store_stub": "windowsapps" in path.lower(),
        "supported": (3, 12) <= (info.major, info.minor) <= (3, 14),
        "recommended": (info.major, info.minor) == (3, 14),
    }


def _registry(hive, path, name):
    import winreg
    with winreg.OpenKey(hive, path) as handle:
        return winreg.QueryValueEx(handle, name)[0]


def windows_facts():
    if not WINDOWS:
        return {"is_windows": False, "text": platform.platform(), "build": 0, "windows11": False, "winget": False, "powershell": False}
    import winreg
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    product = _safely(lambda: _registry(winreg.HKEY_LOCAL_MACHINE, key, "ProductName"), "Windows")
    display = _safely(lambda: _registry(winreg.HKEY_LOCAL_MACHINE, key, "DisplayVersion"), "")
    build = _safely(lambda: int(_registry(winreg.HKEY_LOCAL_MACHINE, key, "CurrentBuild")), 0)
    windows11 = build >= 22000
    if windows11 and "Windows 10" in product:
        product = product.replace("Windows 10", "Windows 11")        # (the registry still says "Windows 10" on Windows 11)
    return {"is_windows": True, "text": f"{product} {display} (build {build})".replace("  ", " ").strip(), "build": build, "windows11": windows11,
            "winget": shutil.which("winget") is not None, "powershell": shutil.which("powershell") is not None}


# ---------------------------------------------------------------- the machine

class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def machine_facts():
    ram = free = 0.0
    if WINDOWS:
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if _safely(lambda: ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)), 0):
            ram, free = status.ullTotalPhys / 2 ** 30, status.ullAvailPhys / 2 ** 30
    cpu = platform.processor() or "unknown processor"
    if WINDOWS:
        import winreg
        cpu = _safely(lambda: _registry(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString"), cpu)
    return {"ram_gb": round(ram, 1), "free_ram_gb": round(free, 1), "cores": os.cpu_count() or 1, "cpu": re.sub(r"\s+", " ", str(cpu)).strip(),
            "nvidia_gpu": shutil.which("nvidia-smi") is not None}


def disk_facts(path):
    def free(target):
        return round(shutil.disk_usage(target).free / 2 ** 30, 1)
    return {"project_free_gb": _safely(lambda: free(path), 0.0), "home_free_gb": _safely(lambda: free(Path.home()), 0.0)}


def hardware_tier(machine):
    """"light", "balanced" or "strong" for the machine_facts() found, and the Tier of recommendations that goes with it."""
    ram, cores = machine.get("ram_gb", 0) or 0, machine.get("cores", 1) or 1
    if ram and ram < 3.5:
        return Tier("very light", "tiny.en", ("qwen2.5:1.5b",), 1200, False, "Very little memory: the quickest speech model, and the chat model may be slow.")
    if (ram and ram <= 9.5) or cores <= 2:
        return TIERS["light"]
    if ram >= 15 and cores >= 6:
        return TIERS["strong"]
    return TIERS["balanced"]


# ---------------------------------------------------------------- the internet

ENDPOINTS = (("PyPI (Python packages)", "https://pypi.org"), ("Hugging Face (voices and speech models)", "https://huggingface.co"),
             ("GitHub (more models)", "https://github.com"), ("Ollama (the chat model)", "https://ollama.com"))


def internet_facts(effects):
    """{name: True/False} for each address the setup downloads from, asked at the same time."""
    answers = {}

    def ask(name, url):
        answers[name] = bool(_safely(lambda: effects.reachable(url), False))
    threads = [threading.Thread(target=ask, args=item, daemon=True) for item in ENDPOINTS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    return {name: answers.get(name, False) for name, _ in ENDPOINTS}


# ---------------------------------------------------------------- sound and camera

def microphone_privacy():
    """Windows' microphone privacy switches: {'system-wide'|'your account'|'desktop apps': 'Allow'|'Deny'|None}."""
    if not WINDOWS:
        return {}
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    spots = {"system-wide": (winreg.HKEY_LOCAL_MACHINE, base), "your account": (winreg.HKEY_CURRENT_USER, base),
             "desktop apps": (winreg.HKEY_CURRENT_USER, base + r"\NonPackaged")}
    return {label: _safely(lambda hive=hive, path=path: _registry(hive, path, "Value"), None) for label, (hive, path) in spots.items()}


def audio_facts(root):
    """The microphones Windows reports (their names), the number of speakers, and the privacy switches."""
    mics = []
    if WINDOWS:
        sys.path.insert(0, str(root))
        try:
            import winmm_mic
            mics = [name for _, name in _safely(winmm_mic.list_devices, [])]
        except Exception:                                 # noqa: BLE001
            mics = []
        finally:
            if sys.path and sys.path[0] == str(root):
                sys.path.pop(0)
    speakers = _safely(lambda: ctypes.windll.winmm.waveOutGetNumDevs(), 0) if WINDOWS else 0
    return {"microphones": mics, "speakers": int(speakers), "privacy": microphone_privacy()}


def camera_present(effects):
    """True/False if Windows lists a camera, None if it could not be found out."""
    try:
        out = effects.powershell("(Get-PnpDevice -Class Camera,Image -PresentOnly -ErrorAction SilentlyContinue | Measure-Object).Count", timeout=40)
        return int(out.strip() or 0) > 0
    except Exception:                                     # noqa: BLE001
        return None


# ---------------------------------------------------------------- programs

def vc_runtime():
    """The Microsoft Visual C++ runtime that the voice libraries need: {'installed': bool, 'version': text}."""
    if not WINDOWS:
        return {"installed": True, "version": "not needed"}
    import winreg
    path = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64"
    installed = _safely(lambda: int(_registry(winreg.HKEY_LOCAL_MACHINE, path, "Installed")) == 1, False)
    version = _safely(lambda: str(_registry(winreg.HKEY_LOCAL_MACHINE, path, "Version")), "")
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    dlls = all((system32 / name).exists() for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"))
    return {"installed": bool(installed and dlls), "version": version.lstrip("v"), "dlls": dlls}


def ollama_executable():
    found = shutil.which("ollama")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        candidate = Path(base) / "Programs" / "Ollama" / "ollama.exe" if base else None
        if candidate and candidate.exists():
            return str(candidate)
        candidate = Path(base) / "Ollama" / "ollama.exe" if base else None
        if candidate and candidate.exists():
            return str(candidate)
    return ""


def ollama_facts(effects, url="http://127.0.0.1:11434"):
    exe = ollama_executable()
    version = effects.http_json(url + "/api/version", timeout=2)
    tags = effects.http_json(url + "/api/tags", timeout=2) if version else None
    models = [m.get("name", "") for m in (tags or {}).get("models", [])]
    return {"installed": bool(exe), "executable": exe, "running": version is not None, "models": models,
            "version": (version or {}).get("version", "")}


# ---------------------------------------------------------------- Python packages and models

def package_facts():
    """{module: True/False} - is each package importable by this Python."""
    importlib.invalidate_caches()
    return {module: _safely(lambda m=module: importlib.util.find_spec(m) is not None, False) for module, *_ in PACKAGES}


def whisper_folder(root, model):
    for snapshot in sorted((Path(root) / "models" / "whisper").glob(f"models--Systran--faster-whisper-{model}/snapshots/*")):
        if (snapshot / "model.bin").exists():
            return snapshot
    return None


def model_facts(root, stt_model="base.en", piper_voice="en_GB-alan-medium"):
    root = Path(root)
    voices = sorted(p.stem for p in (root / "models" / "piper").glob("*.onnx") if p.with_name(p.name + ".json").exists())
    wake = root / "models" / "wakeword"
    return {
        "piper_voices": voices,
        "piper_ready": bool(voices),
        "chosen_voice_ready": piper_voice in voices,
        "whisper_ready": whisper_folder(root, stt_model) is not None,
        "whisper_models": [m for m in ("tiny.en", "base.en", "small.en") if whisper_folder(root, m)],
        "wakeword_ready": all((wake / name).exists() for name in ("hey_jarvis_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx")),
        "speaker_ready": (root / "models" / "speaker" / "nemo_en_titanet_small.onnx").exists(),
        "language_model_ready": (root / "models" / "nlu.joblib").exists(),
    }


def project_facts(root):
    root = Path(root)
    face = root / "DataBase" / "FaceDetectionModule" / "trainer"
    return {
        "env_exists": (root / ".env").exists(),
        "voiceprint": (root / "DataBase" / "voiceprint.npz").exists(),
        "face_model": face.exists() and any(face.iterdir()),
        "notes": (root / "DataBase" / "Notes").exists() and any((root / "DataBase" / "Notes").iterdir()),
        "tasks": (root / "DataBase" / "Tasks").exists() and any((root / "DataBase" / "Tasks").iterdir()),
        "setup_state": (root / "DataBase" / "setup_state.json").exists(),
    }


def gather(effects, root, env_values=None, with_internet=True, with_ollama=True):
    """Everything above in one dict (what the 'system' step shows and the other steps look at)."""
    env_values = env_values or {}
    machine = machine_facts()
    facts = {
        "python": python_facts(),
        "windows": windows_facts(),
        "machine": machine,
        "disk": disk_facts(root),
        "audio": audio_facts(root),
        "vc": vc_runtime(),
        "packages": package_facts(),
        "models": model_facts(root, env_values.get("STT_MODEL") or "base.en", env_values.get("PIPER_VOICE") or "en_GB-alan-medium"),
        "project": project_facts(root),
        "tier": hardware_tier(machine),
    }
    facts["internet"] = internet_facts(effects) if with_internet else {}
    facts["ollama"] = ollama_facts(effects, env_values.get("OLLAMA_URL") or "http://127.0.0.1:11434") if with_ollama else {}
    return facts
