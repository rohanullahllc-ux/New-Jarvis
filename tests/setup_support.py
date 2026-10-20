"""A pretend outside world for testing the setup wizard: no program is run, nothing is downloaded or installed, and the PC "looks"
however a test says. Used by tests/test_setup_*.py."""
import io
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settings_registry  # noqa: E402
from jarvis_setup import system, windows  # noqa: E402
from jarvis_setup.console import Console  # noqa: E402
from jarvis_setup.context import Context  # noqa: E402
from jarvis_setup.effects import RunResult, Signature  # noqa: E402


class FakeEffects:
    """Records what the wizard asks for. ``rules`` is a list of (predicate(command), result or function(command)) tried in order."""

    def __init__(self):
        self.runs, self.visible, self.fetched, self.detached, self.scripts, self.envs = [], [], [], [], [], []
        self.rules = []
        self.json = {}                                     # url fragment -> the JSON answer
        self.signature_result = Signature("Valid", "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond")
        self.reachable_result = True
        self.fetch_error = None
        self.visible_code = 0
        self.powershell_output = ""

    def when(self, predicate, result):
        self.rules.append((predicate, result))

    def result_for(self, command):
        for predicate, result in self.rules:
            if predicate(command):
                return result(command) if callable(result) else result
        return RunResult(0, "")

    def run(self, command, cwd=None, env=None, timeout=None, on_line=None):
        self.runs.append(list(command))
        self.envs.append(env)
        result = self.result_for(command)
        if on_line:
            for line in result.output.splitlines():
                on_line(line)
        return result

    def run_visible(self, command, cwd=None, env=None):
        self.visible.append(list(command))
        result = self.result_for(command)
        return self.visible_code if not self.rules else result.returncode

    def powershell(self, script, timeout=60):
        self.scripts.append(script)
        if self.powershell_output == "RAISE":
            raise RuntimeError("no PowerShell")
        return self.powershell_output

    def signature(self, path):
        return self.signature_result

    def http_json(self, url, timeout=3):
        for fragment, data in self.json.items():
            if fragment in url:
                return data
        return None

    def reachable(self, url, timeout=6):
        return self.reachable_result

    def fetch(self, url, dest, progress=None, expected_size=None, retries=3):
        if self.fetch_error:
            raise self.fetch_error
        self.fetched.append((url, str(dest)))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"installer")
        return Path(dest)

    def start_detached(self, command):
        self.detached.append(list(command))
        return True

    def commands(self, word):
        """The commands run (hidden or visible) that mention ``word``."""
        return [c for c in self.runs + self.visible if any(word in str(part) for part in c)]


def has(*words):
    """A rule predicate: the command contains all these words."""
    return lambda command: all(any(word in str(part) for part in command) for word in words)


def project(root):
    """A small Jarvis folder: requirements, the example settings, and nothing installed."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text("python-dotenv>=1.0\nrequests>=2.32            # talking\naudioop-lts>=0.2.1; python_version >= \"3.13\"\n# a comment\n",
                                           encoding="utf-8")
    (root / ".env.example").write_text(settings_registry.render_env_example(), encoding="utf-8")
    (root / "config.py").write_text("# code\n", encoding="utf-8")
    (root / "Startup.py").write_text("# code\n", encoding="utf-8")
    return root


def make_console(answers=None, assume_yes=False, interactive=None, replies=None):
    out = io.StringIO()
    read = None
    if replies is not None:
        pending = list(replies)
        read = lambda prompt="": pending.pop(0) if pending else ""        # noqa: E731
    console = Console(answers, assume_yes=assume_yes, colour=False, out=out, read=read, read_secret=read, interactive=interactive if interactive is not None else read is not None)
    return console, out


def make_context(root, answers=None, mode="fresh", express=True, dry_run=False, effects=None, facts=None, **console_options):
    console, out = make_console(answers, **console_options)
    ctx = Context(root, console, effects or FakeEffects(), mode=mode, dry_run=dry_run, express=express)
    ctx.facts = facts if facts is not None else normal_facts()
    return ctx, out


def normal_facts(tier="light", internet=True, ollama=None):
    return {
        "python": {"version": (3, 14, 7), "text": "3.14.7", "executable": sys.executable, "bits": 64, "store_stub": False, "supported": True, "recommended": True},
        "windows": {"is_windows": True, "text": "Windows 11 Pro (build 22631)", "build": 22631, "windows11": True, "winget": True, "powershell": True},
        "machine": {"ram_gb": 8.0, "free_ram_gb": 3.0, "cores": 4, "cpu": "Test CPU", "nvidia_gpu": False},
        "disk": {"project_free_gb": 50.0, "home_free_gb": 50.0},
        "audio": {"microphones": ["Test Microphone"], "speakers": 1, "privacy": {}},
        "vc": {"installed": True, "version": "14.38", "dlls": True},
        "packages": {module: True for module, *_ in system.PACKAGES},
        "models": {},
        "project": {},
        "tier": system.TIERS[tier],
        "internet": {name: internet for name, _ in system.ENDPOINTS},
        "ollama": ollama or {"installed": False, "executable": "", "running": False, "models": [], "version": ""},
    }


class World:
    """Patches the probes in jarvis_setup.system (and the shortcut functions in jarvis_setup.windows) so that a test decides what this
    PC looks like and nothing real is read or changed: not the microphone list, not the Windows start-up folder. Use as a context manager."""

    def __init__(self, packages_missing=(), microphones=("Test Microphone",), ollama_exe="", vc_installed=True, camera=True, startup=False):
        self.missing = set(packages_missing)
        self.microphones = list(microphones)
        self.ollama_exe = ollama_exe
        self.vc_installed = vc_installed
        self.camera = camera
        self.startup = startup                       # whether "start Jarvis when I log in" is switched on
        self.startup_calls = []                      # every True/False the wizard set it to
        self.desktop_shortcut_made = False
        self.desktop = Path("no such desktop folder")
        self.patchers = []

    def _set_startup(self, effects, root, on):
        self.startup_calls.append(bool(on))
        self.startup = bool(on)
        return self.startup

    def _make_desktop(self, effects, root, on=True):
        self.desktop_shortcut_made = bool(on)
        return bool(on)

    def start(self):
        specs = [
            mock.patch.object(system, "package_facts", side_effect=lambda: {m: m not in self.missing for m, *_ in system.PACKAGES}),
            mock.patch.object(system, "audio_facts", side_effect=lambda root=None: {"microphones": list(self.microphones), "speakers": 1, "privacy": {}}),
            mock.patch.object(system, "ollama_executable", side_effect=lambda: self.ollama_exe),
            mock.patch.object(system, "vc_runtime", side_effect=lambda: {"installed": self.vc_installed, "version": "14.38", "dlls": self.vc_installed}),
            mock.patch.object(system, "camera_present", side_effect=lambda effects: self.camera),
            mock.patch.object(windows, "starts_with_windows", side_effect=lambda: self.startup),
            mock.patch.object(windows, "set_start_with_windows", side_effect=self._set_startup),
            mock.patch.object(windows, "desktop_shortcut", side_effect=self._make_desktop),
            mock.patch.object(windows, "desktop_dir", side_effect=lambda effects: self.desktop),
        ]
        for patcher in specs:
            patcher.start()
            self.patchers.append(patcher)
        return self

    def stop(self):
        for patcher in self.patchers:
            patcher.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def install_models(root):
    """Put every model file in place, as a finished download would."""
    root = Path(root)
    for relative, text in {"models/piper/en_GB-alan-medium.onnx": "x", "models/piper/en_GB-alan-medium.onnx.json": "{}",
                           "models/whisper/models--Systran--faster-whisper-base.en/snapshots/abc/model.bin": "m",
                           "models/wakeword/hey_jarvis_v0.1.onnx": "w", "models/wakeword/melspectrogram.onnx": "w", "models/wakeword/embedding_model.onnx": "w",
                           "models/speaker/nemo_en_titanet_small.onnx": "s", "models/nlu.joblib": "n"}.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def pretend_downloads(effects, root):
    """Rules that make the model downloads "work": the commands create the files the wizard then checks for."""
    root = Path(root)

    def piper(command):
        name = command[command.index("piper.download_voices") + 1]
        (root / "models" / "piper").mkdir(parents=True, exist_ok=True)
        (root / "models" / "piper" / f"{name}.onnx").write_text("x")
        (root / "models" / "piper" / f"{name}.onnx.json").write_text("{}")
        return RunResult(0, "downloaded")

    def whisper(command):
        model = "base.en"
        snapshot = root / "models" / "whisper" / f"models--Systran--faster-whisper-{model}" / "snapshots" / "abc"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "model.bin").write_text("m")
        return RunResult(0, "ok")

    def wake(command):
        folder = root / "models" / "wakeword"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("hey_jarvis_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx"):
            (folder / name).write_text("w")
        return RunResult(0, "ok")

    def speaker(command):
        (root / "models" / "speaker").mkdir(parents=True, exist_ok=True)
        (root / "models" / "speaker" / "nemo_en_titanet_small.onnx").write_text("s")
        return RunResult(0, "ok")

    def nlu(command):
        (root / "models").mkdir(parents=True, exist_ok=True)
        (root / "models" / "nlu.joblib").write_text("n")
        return RunResult(0, "trained")

    effects.when(has("piper.download_voices"), piper)
    effects.when(has("stt.py", "--download"), whisper)
    effects.when(has("wakeword.py", "--download"), wake)
    effects.when(has("speaker.py", "--download"), speaker)
    effects.when(has("train_nlu.py"), nlu)
