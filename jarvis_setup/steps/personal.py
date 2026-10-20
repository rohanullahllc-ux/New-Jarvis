"""The steps that make Jarvis yours: his voice and your microphone, the password, your voice and face, his language model, and the shortcuts."""
import sys

import settings_registry as registry

from .. import questions, system, windows
from .base import FAIL, OK, SKIP, TODO, WARN, Check, Outcome, Step, tail

WEAK = {"1234", "12345", "123456", "password", "jarvis", "python", "admin", "qwerty", "letmein", "0000", "1111"}


class VoiceStep(Step):
    id = "voice"
    title = "How Jarvis sounds and hears you"
    why = "You choose his voice (and can hear each one), how he is woken, and which microphone he listens to."

    def check(self, ctx):
        if self.done_before(ctx):
            return Check(OK, "already chosen")
        if self.hand_made(ctx):
            return Check(OK, "your voice and microphone settings are already in .env")
        return Check(TODO, "")

    def plan(self, ctx):
        return ["Let you hear the installed voices and choose one", "Ask how you want to wake him (\"hey Jarvis\", claps, or the button) and which microphone to use",
                "Offer to test the microphone"]

    def run(self, ctx):
        c = ctx.console
        audio = system.audio_facts(ctx.root)
        mics = audio["microphones"]
        models = system.model_facts(ctx.root, ctx.value("STT_MODEL"), ctx.value("PIPER_VOICE"))
        if ctx.mode == "restore" and ctx.express and not ctx.force:
            device = ctx.value("MIC_DEVICE")
            if device and not any(device.lower() in name.lower() for name in mics):
                c.warn(f"The microphone '{device}' from your backup is not on this PC, so Jarvis will use the Windows default one.")
                ctx.save_settings({"MIC_DEVICE": ""})
            c.good("Your voice and microphone settings came back with your backup.")
            return Outcome(OK, "kept from the backup")

        def play(name):
            ctx.run_python(["tts_piper.py", questions.SAMPLE_SENTENCE], env={"PIPER_VOICE": name}, timeout=120, on_line=c.log)

        c.say("Now his voice and your microphone.")
        questions.speaking(ctx, models["piper_voices"], play=play)
        questions.hearing(ctx, mics)
        if ctx.value("INPUT_MODE") == "voice" and mics and c.confirm("test_microphone", "Test the microphone now? (it listens for a few seconds; speak normally)", default=True):
            ctx.run_python(["microphone.py", "--no-speech"], visible=True)
        return Outcome(OK, "chosen")


class PasswordStep(Step):
    id = "password"
    title = "The password"
    why = ("Jarvis can control this PC, so a password stands in front of everything he does. Without one he lets nobody in. "
           "Only a scrambled form of it is stored (never the password itself).")

    def check(self, ctx):
        values = ctx.env_values()
        if values.get("JARVIS_PASSWORD_HASH"):
            return Check(OK, "set (stored scrambled)")
        if values.get("JARVIS_PASSWORD"):
            return Check(WARN, "set, but stored as readable text in .env")
        return Check(TODO, "none set: Jarvis would let nobody in")

    def plan(self, ctx):
        return ["Ask for a password (typing is hidden, you type it twice) and store only its scrambled form in .env"]

    def run(self, ctx):
        import gate
        c = ctx.console
        values = ctx.env_values()
        env_path = ctx.root / ".env"
        if values.get("JARVIS_PASSWORD") and not values.get("JARVIS_PASSWORD_HASH"):
            if c.confirm("scramble_password", "Your password is stored in .env as readable text, so anyone who can open that file can read it.\n"
                         "I can scramble it now without changing it. Do that?", default=True):
                if not ctx.dry_run:
                    gate.store_password(values["JARVIS_PASSWORD"], env_path=env_path)
                c.good("Done: .env now holds only the scrambled form. Your password is the same as before.")
                return Outcome(OK, "scrambled")
        if values.get("JARVIS_PASSWORD_HASH") and not c.confirm("change_password", "A password is already set. Change it?", default=False):
            return Outcome(OK, "kept")
        c.say("Choose the password you will type to unlock Jarvis (at least 4 characters; 8 or more is better).")
        for _ in range(3):
            password = c.secret("JARVIS_PASSWORD", "New password:", minimum=4)
            if not password:
                break
            if password.lower() in WEAK and not c.confirm("weak_password_ok", "That is one of the first things anybody would try. Use it anyway?", default=False):
                c.answers.pop("JARVIS_PASSWORD", None)
                continue
            if not ctx.dry_run:
                gate.store_password(password, env_path=env_path)
            c.good("The password is set. Only its scrambled form is stored.")
            return Outcome(OK, "set")
        c.warn("No password was set, so Jarvis will let nobody in. Set one any time with:  python gate.py --set-password  (or in the admin panel).")
        return Outcome(WARN, "no password")


class IdentityStep(Step):
    id = "identity"
    title = "Teaching Jarvis your voice and your face"
    why = ("Your voice print lets him ignore everybody else's voice; your face photos let him glance at the camera after the password. "
           "Both are optional, stay on this PC, and can be done or redone any time.")
    optional = True

    def check(self, ctx):
        p = system.project_facts(ctx.root)
        if p["voiceprint"] and p["face_model"]:
            return Check(OK, "he knows your voice and your face")
        known = [name for name, ok in (("voice", p["voiceprint"]), ("face", p["face_model"])) if ok]
        return Check(TODO, ("he knows your " + " and ".join(known) + "; ") if known else "" + "not taught yet")

    def plan(self, ctx):
        return ["Run enroll_voice.py: you read about 16 sentences (about 3 minutes) and he learns your voice",
                "Run the face photo tool and the face trainer (the camera takes photos while you turn your head slowly)"]

    def run(self, ctx):
        c = ctx.console
        p = system.project_facts(ctx.root)
        models = system.model_facts(ctx.root)
        done = []
        if not p["voiceprint"] and ctx.value("INPUT_MODE") == "voice":
            if not models["speaker_ready"]:
                c.warn("The voice-recognition model is not downloaded yet, so the voice lesson has to wait. Run the setup again once it is.")
            elif c.confirm("enroll_voice", "Teach him your voice now? You read about 16 sentences (3 minutes) in your normal speaking voice, in a quiet room.\n"
                           "After that he answers only you.", default=ctx.mode != "restore"):
                code = ctx.run_python(["enroll_voice.py"], visible=True)
                (c.good if code == 0 else c.warn)("Voice lesson finished." if code == 0 else "The voice lesson did not finish; run  python enroll_voice.py  when you can.")
                done.append("voice")
        if not p["face_model"] and ctx.facts.get("packages", {}).get("cv2", system.package_facts().get("cv2")):
            camera = system.camera_present(ctx.effects)
            if camera is not False and c.confirm("enroll_face", "Teach him your face now? The camera takes about 30 photos while you slowly turn your head (a minute).\n"
                                                 "He then confirms it is you after the password.", default=False):
                a = ctx.run_python(["DataBase/FaceDetectionModule/SampleGenerator.py"], visible=True)
                b = ctx.run_python(["DataBase/FaceDetectionModule/ModelTrainer.py"], visible=True) if a == 0 else a
                (c.good if b == 0 else c.warn)("Face lesson finished." if b == 0 else "The face lesson did not finish; see the README for the two commands.")
                done.append("face")
        return Outcome(OK if done else SKIP, ", ".join(done) or "nothing taught now")


class LanguageModelStep(Step):
    id = "language_model"
    title = "Training his own language model"
    why = ("Jarvis trains a small model of his own, on this PC, from the phrases in training/nlu/. It lets him understand loosely worded "
           "commands (\"snap my display\"). It takes about two minutes and needs no internet.")

    def check(self, ctx):
        if system.model_facts(ctx.root)["language_model_ready"]:
            return Check(OK, "models/nlu.joblib exists")
        if not system.package_facts().get("sklearn"):
            return Check(WARN, "scikit-learn is not installed")
        return Check(TODO, "not trained yet")

    def plan(self, ctx):
        return ["Run training/train_nlu.py (about two minutes) and save models/nlu.joblib"]

    def run(self, ctx):
        c = ctx.console
        if not system.package_facts().get("sklearn"):
            c.warn("scikit-learn is not installed, so the language model cannot be trained yet.")
            return Outcome(WARN, "scikit-learn missing")
        c.say("Training (about two minutes)...")
        result = ctx.run_python(["training/train_nlu.py"], on_line=c.log, timeout=1200)
        if result.returncode == 0 and system.model_facts(ctx.root)["language_model_ready"]:
            c.good("His language model is trained.")
            return Outcome(OK, "trained")
        c.bad("Training did not finish: " + tail(result.output, 3))
        return Outcome(WARN, "training failed")


class WindowsStep(Step):
    id = "windows"
    title = "Shortcuts and start-up"
    why = "A Jarvis shortcut on the desktop, and (only if you said yes) opening him by himself when you log in to Windows."

    def _wants_startup_changed(self, ctx):
        wants = ctx.choices.get("start_with_windows")
        return wants is not None and bool(wants) != windows.starts_with_windows()

    def applies(self, ctx):
        return bool(ctx.choices.get("desktop_shortcut")) or self._wants_startup_changed(ctx)

    def check(self, ctx):
        todo = []
        if ctx.choices.get("desktop_shortcut") and not (windows.desktop_dir(ctx.effects) / windows.LINK_NAME).exists():
            todo.append("the desktop shortcut")
        if self._wants_startup_changed(ctx):
            todo.append("the start-up setting")
        return Check(TODO, "to do: " + ", ".join(todo)) if todo else Check(OK, "")

    def plan(self, ctx):
        out = []
        if ctx.choices.get("desktop_shortcut"):
            out.append("Make the Jarvis shortcut on the desktop")
        if self._wants_startup_changed(ctx):
            out.append("Add Jarvis to your Windows start-up folder (remove it again in the admin panel)" if ctx.choices["start_with_windows"]
                       else "Take Jarvis out of your Windows start-up folder")
        return out

    def run(self, ctx):
        c = ctx.console
        done = []
        try:
            if ctx.choices.get("desktop_shortcut"):
                if windows.desktop_shortcut(ctx.effects, ctx.root, True):
                    c.good("The Jarvis shortcut is on the desktop.")
                    done.append("desktop")
            if self._wants_startup_changed(ctx):
                now = windows.set_start_with_windows(ctx.effects, ctx.root, bool(ctx.choices["start_with_windows"]))
                c.good("Jarvis will open when you log in to Windows." if now else "Jarvis will not open by himself when you log in.")
                done.append("startup")
        except Exception as error:                            # noqa: BLE001 - a shortcut is a nicety, never a reason to stop
            c.warn(f"Could not make the shortcut ({error}). You can start Jarvis with Start-Jarvis.bat instead.")
            return Outcome(WARN, "shortcut failed")
        return Outcome(OK, ", ".join(done))
