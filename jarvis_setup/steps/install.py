"""The steps that download and install things: the Python packages, the voices and speech models, and Ollama (the chat model)."""
import shutil
import tempfile
import time
from pathlib import Path

from .. import questions, system
from ..effects import DownloadError
from .base import FAIL, OK, SKIP, TODO, WARN, Check, Outcome, Step, tail

CRITICAL_NOTE = "Without it Jarvis cannot start."
OLLAMA_URL = "https://ollama.com/download/OllamaSetup.exe"


def _progress(done, total):
    if total:
        return f"{done / 1e6:7.1f} of {total / 1e6:.1f} MB  ({done * 100 // total}%)"
    return f"{done / 1e6:7.1f} MB"


def requirement_lines(path):
    """The lines of requirements.txt that name a package (comments taken away)."""
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split(" #")[0].strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


# ---------------------------------------------------------------- the Python packages

class PackagesStep(Step):
    id = "packages"
    title = "Installing the Python packages"
    why = ("Jarvis is built from about 30 free Python libraries (the window, hearing, speaking, the tools). They are downloaded once from "
           "pypi.org: roughly 1 to 2 GB, so allow 5 to 20 minutes depending on the internet.")

    def check(self, ctx):
        present = system.package_facts()
        missing = [module for module, ok in present.items() if not ok]
        if not missing:
            return Check(OK, f"all {len(present)} installed")
        essential = [m for m in missing if system.BY_MODULE[m][1]]
        return Check(TODO, f"{len(missing)} missing" + (f", {len(essential)} of them essential" if essential else ""))

    def plan(self, ctx):
        missing = [system.BY_MODULE[m][0] for m, ok in system.package_facts().items() if not ok]
        return [f"Run: {ctx.python} -m pip install -r requirements.txt", "Packages still missing: " + (", ".join(missing) or "none"),
                "If one package fails, install the others one by one and report which could not be installed",
                "Check that the window library and the voice libraries load together without crashing"]

    def run(self, ctx):
        c = ctx.console
        net = ctx.facts.get("internet", {})
        if net and not net.get("PyPI (Python packages)", True):
            c.warn("pypi.org cannot be reached, so the packages cannot be installed now. Connect to the internet and run the setup again.")
            return Outcome(WARN, "no internet")
        requirements = ctx.root / "requirements.txt"
        if not requirements.exists():
            c.bad("requirements.txt is missing from the Jarvis folder.")
            return Outcome(FAIL, "no requirements.txt")
        seen = [0]

        def show(line):
            c.log(line)
            if line.startswith(("Collecting ", "Installing collected packages", "Successfully installed", "ERROR")):
                seen[0] += 1
                c.note(line[:100])

        if ctx.effects.run([ctx.python, "-m", "pip", "--version"]).returncode != 0:
            c.say("pip is missing; adding it...")
            ctx.run_python(["-m", "ensurepip", "--upgrade"])
        c.say("Installing. This is the longest step; pip shows each package as it arrives.")
        base = ["-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
        result = None
        for attempt in (1, 2, 3):
            result = ctx.run_python(base + ["-r", "requirements.txt"], on_line=show, timeout=3600)
            if result.returncode == 0:
                break
            c.warn(f"pip stopped (try {attempt} of 3). " + ("Trying again." if attempt < 3 else "Installing the packages one at a time instead."))
            time.sleep(2)
        if result is not None and result.returncode != 0:
            for line in requirement_lines(requirements):
                one = ctx.run_python(base + [line], on_line=show, timeout=1800)
                if one.returncode != 0:
                    c.warn(f"Could not install: {line}")
        after = system.package_facts()
        missing = [m for m, ok in after.items() if not ok]
        essential = [m for m in missing if system.BY_MODULE[m][1]]
        for module in missing:
            package, critical, purpose = system.BY_MODULE[module]
            (c.bad if critical else c.warn)(f"{package} is not installed - it is for {purpose}. " + (CRITICAL_NOTE if critical else ""))
        check = ctx.run_python(["-c", "import native_libs; native_libs.preload(); import PyQt5.QtCore, PyQt5.QtWidgets; print('window library ok')"], timeout=180)
        if check.returncode != 0 and after.get("PyQt5"):
            c.bad("The window library and the voice libraries crashed when loaded together: " + tail(check.output, 3))
            return Outcome(FAIL, "libraries crash")
        if essential:
            return Outcome(FAIL, f"essential packages missing: {', '.join(essential)}")
        if missing:
            return Outcome(WARN, f"{len(missing)} optional packages missing")
        c.good(f"All {len(after)} packages are installed and load together.")
        return Outcome(OK, "installed")


# ---------------------------------------------------------------- voices and speech models

class ModelsStep(Step):
    id = "models"
    title = "Downloading the voices and speech models"
    why = ("The natural voice, offline hearing (Whisper), the \"hey Jarvis\" wake word and the voice-recognition model are downloaded once, "
           "and then work with no internet at all. About 300 MB.")

    def _facts(self, ctx):
        return system.model_facts(ctx.root, ctx.value("STT_MODEL"), ctx.value("PIPER_VOICE"))

    def check(self, ctx):
        m = self._facts(ctx)
        missing = [name for name, ok in (("a natural voice", m["piper_ready"]), ("Whisper", m["whisper_ready"]), ("the wake word", m["wakeword_ready"]),
                                         ("the voice-recognition model", m["speaker_ready"])) if not ok]
        return Check(OK if not missing else TODO, "everything is there" if not missing else "missing: " + ", ".join(missing))

    def plan(self, ctx):
        m = self._facts(ctx)
        out = []
        if not m["piper_ready"]:
            out.append(f"Download the natural voice {ctx.value('PIPER_VOICE')} (about {questions.VOICE_SIZE_MB} MB) into models/piper")
        if not m["whisper_ready"]:
            out.append(f"Download the Whisper model {ctx.value('STT_MODEL')} into models/whisper")
        if not m["wakeword_ready"]:
            out.append("Download the \"hey Jarvis\" wake-word model (about 4 MB)")
        if not m["speaker_ready"]:
            out.append("Download the voice-recognition model (26 MB)")
        return out or ["Nothing to download: all the models are there."]

    def run(self, ctx):
        c = ctx.console
        net = ctx.facts.get("internet", {})
        m = self._facts(ctx)
        needed = not (m["piper_ready"] and m["whisper_ready"] and m["wakeword_ready"] and m["speaker_ready"])
        if needed and net and not (net.get("Hugging Face (voices and speech models)", True) or net.get("GitHub (more models)", True)):
            c.warn("The model sites cannot be reached, so nothing can be downloaded now. Connect to the internet and run the setup again.")
            return Outcome(WARN, "no internet")
        questions_done = questions.speech_model(ctx)
        failures = []

        def fetch(label, arguments, ready, env=None, minutes=20):
            c.say(f"{label}...")
            for attempt in (1, 2):
                result = ctx.run_python(arguments, env=env, on_line=c.log, timeout=minutes * 60)
                if result.returncode == 0 and ready():
                    c.good(f"{label}: done")
                    return True
                if attempt == 1:
                    c.warn("That did not work; trying once more.")
            c.bad(f"{label}: failed. " + tail(result.output, 3))
            failures.append(label)
            return False

        m = self._facts(ctx)
        installed = list(m["piper_voices"])
        wanted = questions.wanted_voices(ctx)
        for name in wanted:
            if name in installed:
                continue
            fetch(f"The natural voice {questions.friendly_voice(name)}", ["-m", "piper.download_voices", name, "--download-dir", "models/piper"],
                  lambda n=name: (ctx.root / "models" / "piper" / f"{n}.onnx").exists())
        model = ctx.value("STT_MODEL")
        if not system.whisper_folder(ctx.root, model):
            fetch(f"The Whisper model {model} (about {questions.WHISPER_SIZE_MB.get(model, 150)} MB)", ["stt.py", "--download"],
                  lambda: system.whisper_folder(ctx.root, model) is not None, env={"STT_MODEL": model})
        if not m["wakeword_ready"]:
            fetch("The \"hey Jarvis\" wake word", ["wakeword.py", "--download"], lambda: self._facts(ctx)["wakeword_ready"])
        if not m["speaker_ready"]:
            fetch("The voice-recognition model", ["speaker.py", "--download"], lambda: self._facts(ctx)["speaker_ready"])
        if failures:
            return Outcome(WARN, "could not download: " + ", ".join(failures))
        return Outcome(OK, "downloaded" if questions_done is not None else "")


# ---------------------------------------------------------------- Ollama, the chat model

def models_in(models_dir):
    """The names ("qwen2.5:1.5b") of the models whose manifests are in an Ollama models folder."""
    names = []
    base = Path(models_dir) / "manifests"
    for tag_file in base.rglob("*"):
        if tag_file.is_file():
            relative = tag_file.relative_to(base).parts
            if len(relative) >= 3:
                model = "/".join(relative[2:-1]) if len(relative) > 3 else relative[-2]
                names.append(f"{model}:{relative[-1]}")
    return sorted(set(names))


def copy_additively(source, target):
    """Copy a folder tree, leaving alone any file that is already there with the same size. Returns the number of files copied."""
    copied = 0
    for path in Path(source).rglob("*"):
        if path.is_file():
            destination = Path(target) / path.relative_to(source)
            if destination.exists() and destination.stat().st_size == path.stat().st_size:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied += 1
    return copied


class OllamaStep(Step):
    id = "ollama"
    title = "The chat model (Ollama)"
    why = ("Ollama is a free program that runs an AI model on this PC, so Jarvis can chat about anything with no account, no card and no "
           "internet. The model is a download of about 1 GB.")
    optional = True

    def applies(self, ctx):
        return ctx.choices.get("install_ollama", True)

    def _wanted(self, ctx):
        wanted = ctx.choices.get("ollama_models")
        if wanted:
            return list(wanted)
        restored = ctx.choices.get("ollama_restore_from")
        if restored:
            return models_in(restored)[:2]
        return [ctx.tier.ollama_models[0]] if ctx.tier else ["qwen2.5:1.5b"]

    def check(self, ctx):
        o = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))
        wanted = self._wanted(ctx)
        have = [m for m in wanted if m in o["models"]]
        if o["running"] and len(have) == len(wanted):
            return Check(OK, "running with " + ", ".join(o["models"]))
        if not o["installed"]:
            return Check(TODO, "Ollama is not installed")
        return Check(TODO, "installed, but " + ("not running" if not o["running"] else "model missing: " + ", ".join(set(wanted) - set(have))))

    def plan(self, ctx):
        o = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))
        out = []
        if not o["installed"]:
            out += [f"Download OllamaSetup.exe from {OLLAMA_URL} (about 1 GB)", "Check that it is signed", "Install it quietly (no administrator rights needed)"]
        if not o["running"]:
            out.append("Start Ollama")
        restored = ctx.choices.get("ollama_restore_from")
        for model in self._wanted(ctx):
            if model in o["models"]:
                continue
            out.append(f"Put back {model} from your backup" if restored and model in models_in(restored) else f"Download the model {model}")
        return out or ["Nothing to do: Ollama is running with the model."]

    def _wait_until_running(self, ctx, seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))["running"]:
                return True
            time.sleep(2)
        return False

    def run(self, ctx):
        c = ctx.console
        if "install_ollama" not in ctx.choices:
            if not c.confirm("install_ollama", "Set up the chat model now? (Ollama is free; the model is a download of about 1 GB.)", default=True):
                return Outcome(SKIP, "declined")
        o = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))
        net = ctx.facts.get("internet", {})
        online = not net or net.get("Ollama (the chat model)", True)
        wanted = self._wanted(ctx)
        restored = ctx.choices.get("ollama_restore_from")

        if restored and Path(restored).is_dir():                  # saved models go back first: they spare the download
            target = Path.home() / ".ollama" / "models"
            if ctx.dry_run:
                c.note(f"would copy the saved models from {restored} to {target}")
            else:
                copied = copy_additively(restored, target)
                c.good(f"Put back the saved chat models ({copied} files).")

        if not o["installed"]:
            if not online:
                c.warn("ollama.com cannot be reached, so Ollama cannot be downloaded now. Run the setup again when you are online.")
                return Outcome(WARN, "no internet")
            installer = Path(tempfile.gettempdir()) / "JarvisSetup" / "OllamaSetup.exe"
            c.say("Downloading Ollama (about 1 GB; if it stops, run the setup again and it carries on)...")
            try:
                ctx.effects.fetch(OLLAMA_URL, installer, progress=lambda done, total: c.progress(_progress(done, total)), retries=4)
                c.end_progress()
            except DownloadError as error:
                c.end_progress()
                c.bad(str(error))
                return Outcome(FAIL, "download failed")
            signed = ctx.effects.signature(installer)
            if signed.status != "Valid":
                c.bad(f"The Ollama installer is not properly signed (status {signed.status}), so I will not run it.")
                return Outcome(FAIL, "signature not valid")
            if "ollama" not in signed.subject.lower() and not c.confirm("ollama_signer_ok", f"It is signed by '{signed.subject or 'unknown'}', not by Ollama. The signature itself is valid and the file came from ollama.com. Install it anyway?", default=True):
                return Outcome(SKIP, "signer not trusted")
            c.say("Installing Ollama (a minute or two)...")
            done = ctx.effects.run([str(installer), "/SILENT", "/NORESTART"], timeout=900)
            o = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))
            if not o["installed"]:
                c.bad("The installer finished but Ollama is not there: " + tail(done.output, 2))
                return Outcome(FAIL, "install failed")
            c.good("Ollama is installed.")
        if not o["running"]:
            ctx.effects.start_detached([o["executable"], "serve"])
        if not self._wait_until_running(ctx):
            c.bad("Ollama did not start. Open it from the Start menu once, then run the setup again.")
            return Outcome(WARN, "not running")
        c.good("Ollama is running.")

        have = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))["models"]
        for model in wanted:
            if model in have:
                continue
            if not online:
                c.warn(f"{model} is not here and ollama.com cannot be reached; run the setup again when you are online.")
                continue
            c.say(f"Downloading the chat model {model} (Ollama shows its own progress)...")
            code = ctx.effects.run_visible([o["executable"] or "ollama", "pull", model])
            if code != 0:
                c.bad(f"Could not download {model}. Try later with:  ollama pull {model}")
        have = system.ollama_facts(ctx.effects, ctx.value("OLLAMA_URL"))["models"]
        got = [m for m in wanted if m in have]
        if len(got) == len(wanted):
            c.good("Chat model ready: " + ", ".join(got))
            return Outcome(OK, "ready")
        return Outcome(WARN, "model missing: " + ", ".join(set(wanted) - set(got)))
