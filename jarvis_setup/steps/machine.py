"""The first two steps: look at this PC, and make sure Windows has the Visual C++ runtime the voice libraries need."""
import tempfile
from pathlib import Path

from .. import system, windows
from ..effects import DownloadError
from .base import FAIL, OK, SKIP, TODO, WARN, Check, Outcome, Step, outcome_from


def _yes(flag):
    return "yes" if flag else "NO"


class SystemStep(Step):
    id = "system"
    title = "Looking at this PC"
    why = "So that the setup suggests what suits it, and tells you plainly about anything that would get in the way."
    read_only = True

    def check(self, ctx):
        return Check(OK if ctx.facts else TODO, "")

    def plan(self, ctx):
        return ["Look at Windows, Python, memory, disk space, the internet, the sound devices and what is already installed (changes nothing)."]

    def run(self, ctx):
        c = ctx.console
        values = ctx.env_values()
        c.say("Looking around (this takes a few seconds)...")
        ctx.facts = system.gather(ctx.effects, ctx.root, values)
        f = ctx.facts
        problems, warnings = [], []

        windows_facts, py = f["windows"], f["python"]
        if not windows_facts["is_windows"]:
            problems.append("Jarvis is built for Windows; this computer is not running Windows.")
        c.info(windows_facts["text"])
        if py["store_stub"]:
            problems.append("This 'python' is the Microsoft Store shortcut, not a real Python. Install Python 3.14 from python.org and run Setup-Jarvis.bat again.")
        if py["recommended"]:
            c.good(f"Python {py['text']} ({py['bits']}-bit) - the version Jarvis was built and tested on")
        elif py["supported"]:
            c.warn(f"Python {py['text']} - Jarvis was tested on 3.14; this one should work, but 3.14 is the safe choice")
            warnings.append("Python is not 3.14")
        else:
            problems.append(f"Python {py['text']} is not supported. Install Python 3.14 from python.org and run Setup-Jarvis.bat again.")
        if py["bits"] != 64:
            problems.append("This is a 32-bit Python; the voice libraries need 64-bit.")

        m, tier = f["machine"], f["tier"]
        c.info(f"{m['cpu']}: {m['cores']} processor threads, {m['ram_gb']} GB memory ({m['free_ram_gb']} GB free right now)"
               + (", with an NVIDIA graphics card" if m["nvidia_gpu"] else ", no graphics card used"))
        c.info(f"This counts as a '{tier.name}' PC. {tier.note}")
        free = f["disk"]["project_free_gb"]
        if free and free < 6:
            c.warn(f"Only {free} GB of disk space is free here; the voices, models and packages need about 6 GB.")
            warnings.append("little disk space")
        else:
            c.good(f"Disk space: {free} GB free")

        net = f.get("internet", {})
        if net and not any(net.values()):
            c.warn("The internet does not seem to be reachable. Downloads will be skipped; run the setup again when you are online.")
            warnings.append("no internet")
        elif net:
            c.good("Internet: " + ", ".join(f"{name.split(' (')[0]} {'yes' if ok else 'NO'}" for name, ok in net.items()))
            if not all(net.values()):
                warnings.append("some download sites are not reachable")

        audio = f["audio"]
        if audio["microphones"]:
            c.good("Microphone: " + "; ".join(audio["microphones"]))
        else:
            c.warn("Windows reports no microphone. You can still type to Jarvis; plug one in later.")
            warnings.append("no microphone")
        denied = [label for label, value in audio["privacy"].items() if value == "Deny"]
        if denied:
            c.warn("Windows is blocking microphone access (" + ", ".join(denied) + "). Turn it on in Settings > Privacy & security > Microphone, "
                   "including 'Let desktop apps access your microphone'.")
            warnings.append("microphone blocked by Windows")
        c.info(f"Speakers found: {audio['speakers']}")

        vc = f["vc"]
        if vc["installed"]:
            c.good(f"Visual C++ runtime {vc['version'] or ''} is installed")
        else:
            c.todo("The Microsoft Visual C++ runtime is missing (the voice libraries need it) - the next step installs it")

        o = f.get("ollama", {})
        if o:
            if o["running"]:
                c.good("Ollama is running" + (f" with: {', '.join(o['models'])}" if o["models"] else " (no model yet)"))
            elif o["installed"]:
                c.info("Ollama is installed but not running")
            else:
                c.info("Ollama (the chat model) is not installed")
        missing = [name for module, ok in f["packages"].items() if not ok for name in [system.BY_MODULE[module][0]]]
        c.info(f"Python packages: {len(f['packages']) - len(missing)} of {len(f['packages'])} installed")
        if problems:
            for text in problems:
                c.bad(text)
            return Outcome(FAIL, " ".join(problems))
        return Outcome(WARN if warnings else OK, "; ".join(warnings))


class RuntimeStep(Step):
    id = "runtime"
    title = "The Visual C++ runtime"
    why = ("The voice libraries (speech recognition, the natural voice, the wake word) are written in C++ and need Microsoft's free Visual C++ "
           "runtime. A fresh or 'lite' Windows often does not have it, and without it they fail with 'DLL load failed'.")

    def check(self, ctx):
        vc = ctx.facts.get("vc") or system.vc_runtime()
        return Check(OK if vc["installed"] else TODO, f"version {vc['version']}" if vc["installed"] else "missing")

    def plan(self, ctx):
        return ["Download Microsoft's Visual C++ runtime (about 25 MB) from aka.ms/vs/17/release/vc_redist.x64.exe",
                "Check that it is signed by Microsoft Corporation",
                "Install it (Windows will ask you to allow it) - a restart may be needed afterwards"]

    def run(self, ctx):
        c = ctx.console
        net = ctx.facts.get("internet", {})
        if net and not any(net.values()):
            c.warn("No internet, so the runtime cannot be downloaded now. Run the setup again when you are online.")
            return Outcome(WARN, "no internet")
        if not c.confirm("install_vc_runtime", "May I download and install Microsoft's Visual C++ runtime (25 MB, free, signed by Microsoft)?", default=True):
            return Outcome(SKIP, "declined")
        target = Path(tempfile.gettempdir()) / "JarvisSetup" / "vc_redist.x64.exe"
        try:
            c.say("Downloading...")
            ctx.effects.fetch(windows.VC_REDIST_URL, target, progress=lambda done, total: c.progress(_progress(done, total)))
            c.end_progress()
        except DownloadError as error:
            c.end_progress()
            c.bad(str(error))
            return Outcome(FAIL, "download failed")
        signed = ctx.effects.signature(target)
        if signed.status != "Valid" or "microsoft" not in signed.subject.lower():
            c.bad(f"The downloaded file is not signed by Microsoft (status {signed.status}), so I will not run it.")
            return Outcome(FAIL, "signature not valid")
        c.good("Signed by Microsoft Corporation")
        c.say("Installing - Windows will ask 'Do you want to allow this app to make changes?'. Please say Yes.")
        code = windows.run_elevated(ctx.effects, str(target), "/install /quiet /norestart")
        if code in (0, 1638):                              # 1638: a newer one is already there
            c.good("The Visual C++ runtime is installed.")
            return Outcome(OK, "installed")
        if code == 3010:
            c.warn("Installed, but Windows wants a restart before it is used. Restart the PC, then run the setup again.")
            return Outcome(WARN, "restart needed")
        c.bad("The installer did not finish" + (f" (code {code})" if code is not None else " (the permission question was refused)")
              + ". You can run it yourself: " + windows.VC_REDIST_URL)
        return Outcome(FAIL, "installer failed")


def _progress(done, total):
    if total:
        return f"{done / 1e6:6.1f} of {total / 1e6:.1f} MB  ({done * 100 // total}%)"
    return f"{done / 1e6:6.1f} MB"
