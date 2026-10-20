"""The last step: try everything once, and say plainly what works and what still needs attention."""
from .. import system
from .base import FAIL, OK, SKIP, TODO, WARN, Check, Outcome, Step, tail

IMPORT_CODE = ("import config, envfile, settings_registry, gate, speech, stt, tts_piper, wakeword, speaker, microphone, listener, clap, "
               "transcript, backup_jarvis; from JarvisAdvancedBot import LocalBrain, ChatBrain, tools; import gui.main_window; print('imports ok')")


class SelfCheckStep(Step):
    id = "selfcheck"
    title = "Trying it all"
    why = "A last look: every part of Jarvis loads, the microphone works, and he can speak."
    read_only = True

    def check(self, ctx):
        return Check(TODO, "")

    def plan(self, ctx):
        return ["Load every part of Jarvis once (a few seconds)", "Check the microphone (a few seconds)", "Let him say a few sentences (you will hear him)",
                "Optionally run his 1,200 self-tests (about 2 minutes)"]

    def run(self, ctx):
        c = ctx.console
        problems = []
        c.say("Loading every part of Jarvis once...")
        loaded = ctx.run_python(["-c", IMPORT_CODE], timeout=300)
        if loaded.returncode == 0:
            c.good("Every part of Jarvis loads.")
        else:
            c.bad("Something does not load: " + tail(loaded.output, 4))
            problems.append("a part of Jarvis does not load")
        mics = system.audio_facts(ctx.root)["microphones"]
        if ctx.value("INPUT_MODE") == "voice" and mics:
            heard = ctx.run_python(["microphone.py", "--no-speech"], timeout=180, on_line=c.log)
            if heard.returncode == 0:
                c.good("The microphone chain works (Windows, the device, recording).")
            else:
                c.warn("The microphone check found something to fix:\n" + "\n".join("  " + line for line in heard.output.splitlines() if "->" in line or "FAIL" in line))
                problems.append("the microphone needs attention (run  python microphone.py  for details)")
        if c.confirm("test_voice", "Let Jarvis say a few sentences now, to prove that he speaks? (You will hear him.)", default=True):
            spoke = ctx.run_python(["speech.py"], timeout=240, on_line=c.log)
            (c.good if spoke.returncode == 0 else c.warn)("He speaks." if spoke.returncode == 0 else "He did not speak properly: " + tail(spoke.output, 3))
            if spoke.returncode != 0:
                problems.append("his voice needs attention (run  python speech.py)")
        if c.confirm("run_tests", "Run Jarvis's own self-tests too? (About 1,200 checks, around two minutes; nothing is touched.)", default=ctx.mode == "repair"):
            tests = ctx.run_python(["-m", "unittest", "discover", "-s", "tests"], timeout=1800, on_line=c.log)
            last = [line for line in tests.output.splitlines() if line.startswith(("Ran ", "OK", "FAILED"))]
            (c.good if tests.returncode == 0 else c.warn)("Self-tests: " + " ".join(last[-2:]))
            if tests.returncode != 0:
                problems.append("some self-tests failed (see Logs/setup.log)")
        return Outcome(WARN if problems else OK, "; ".join(problems))
