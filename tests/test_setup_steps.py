"""Tests for each step of the setup wizard, against a pretend PC (nothing is installed, downloaded or run):
python -m unittest tests.test_setup_steps -v"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup_jarvis  # noqa: E402
import gate  # noqa: E402
from jarvis_setup import system, windows  # noqa: E402
from jarvis_setup.effects import DownloadError, RunResult, Signature  # noqa: E402
from jarvis_setup.steps import data, finish, install, machine, personal  # noqa: E402
from jarvis_setup.steps.base import FAIL, OK, SKIP, TODO, WARN  # noqa: E402
from tests.setup_support import FakeEffects, World, has, make_context, normal_facts, pretend_downloads, project  # noqa: E402


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.root = project(self.temp / "jarvis")
        sleeper = mock.patch("jarvis_setup.steps.install.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def ctx(self, answers=None, **kwargs):
        return make_context(self.root, answers, **kwargs)

    def env(self, ctx):
        return ctx.env.values()


class SystemStepTests(Temp):
    def run_with(self, facts):
        ctx, out = self.ctx()
        with mock.patch.object(system, "gather", return_value=facts):
            outcome = machine.SystemStep().run(ctx)
        return outcome, out.getvalue(), ctx

    def test_a_normal_pc_is_all_good_and_the_facts_are_kept_for_the_other_steps(self):
        outcome, text, ctx = self.run_with(normal_facts())
        self.assertEqual(outcome.state, OK)
        self.assertIn("the version Jarvis was built and tested on", text)
        self.assertIn("'light' PC", text)
        self.assertEqual(ctx.facts["tier"].name, "light")

    def test_the_microsoft_store_python_stops_everything_with_the_fix(self):
        facts = normal_facts()
        facts["python"] = dict(facts["python"], store_stub=True)
        outcome, text, _ = self.run_with(facts)
        self.assertEqual(outcome.state, FAIL)
        self.assertIn("Microsoft Store shortcut", text)

    def test_an_unsupported_python_stops_everything(self):
        facts = normal_facts()
        facts["python"] = dict(facts["python"], text="3.9.1", supported=False, recommended=False)
        self.assertEqual(self.run_with(facts)[0].state, FAIL)

    def test_another_supported_python_is_a_warning_not_a_stop(self):
        facts = normal_facts()
        facts["python"] = dict(facts["python"], text="3.13.2", recommended=False)
        outcome, text, _ = self.run_with(facts)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("3.14 is the safe choice", text)

    def test_not_windows_is_a_stop(self):
        facts = normal_facts()
        facts["windows"] = dict(facts["windows"], is_windows=False)
        self.assertEqual(self.run_with(facts)[0].state, FAIL)

    def test_no_internet_blocked_microphone_and_no_disk_space_are_warnings_with_advice(self):
        facts = normal_facts(internet=False)
        facts["audio"] = {"microphones": [], "speakers": 1, "privacy": {"desktop apps": "Deny"}}
        facts["disk"] = {"project_free_gb": 2.0, "home_free_gb": 2.0}
        outcome, text, _ = self.run_with(facts)
        self.assertEqual(outcome.state, WARN)
        for words in ("internet does not seem to be reachable", "no microphone", "blocking microphone access", "Only 2.0 GB"):
            self.assertIn(words, text)

    def test_a_missing_runtime_and_missing_packages_are_reported(self):
        facts = normal_facts()
        facts["vc"] = {"installed": False, "version": "", "dlls": False}
        facts["packages"]["PyQt5"] = False
        _, text, _ = self.run_with(facts)
        self.assertIn("Visual C++ runtime is missing", text)
        self.assertIn("Python packages: 29 of 30", text)

    def test_the_look_around_is_read_only_and_always_runs(self):
        step = machine.SystemStep()
        self.assertTrue(step.read_only)
        ctx, _ = self.ctx()
        self.assertEqual(step.check(ctx).state, OK)                     # (facts are already there)
        ctx.facts = {}
        self.assertEqual(step.check(ctx).state, TODO)


class RuntimeStepTests(Temp):
    def run_step(self, answers=None, facts=None, effects=None, elevated=0):
        effects = effects or FakeEffects()
        ctx, out = self.ctx(answers or {"install_vc_runtime": True}, effects=effects, facts=facts)
        with mock.patch.object(windows, "run_elevated", return_value=elevated) as run:
            outcome = machine.RuntimeStep().run(ctx)
        return outcome, effects, run, out.getvalue()

    def test_it_downloads_checks_the_signature_and_installs(self):
        outcome, effects, run, _ = self.run_step()
        self.assertEqual(outcome.state, OK)
        self.assertEqual(effects.fetched[0][0], windows.VC_REDIST_URL)
        run.assert_called_once()
        self.assertIn("/install /quiet /norestart", run.call_args[0][2])

    def test_an_installer_not_signed_by_microsoft_is_never_run(self):
        effects = FakeEffects()
        effects.signature_result = Signature("NotSigned", "")
        outcome, _, run, text = self.run_step(effects=effects)
        self.assertEqual(outcome.state, FAIL)
        run.assert_not_called()
        self.assertIn("not signed by Microsoft", text)

    def test_a_valid_signature_from_somebody_else_is_not_good_enough(self):
        effects = FakeEffects()
        effects.signature_result = Signature("Valid", "CN=Some Other Company")
        outcome, _, run, _ = self.run_step(effects=effects)
        self.assertEqual(outcome.state, FAIL)
        run.assert_not_called()

    def test_declining_installs_nothing(self):
        outcome, effects, run, _ = self.run_step({"install_vc_runtime": False})
        self.assertEqual(outcome.state, SKIP)
        self.assertEqual(effects.fetched, [])
        run.assert_not_called()

    def test_without_internet_it_waits_for_a_better_moment(self):
        outcome, effects, run, text = self.run_step(facts=normal_facts(internet=False))
        self.assertEqual(outcome.state, WARN)
        self.assertEqual(effects.fetched, [])
        self.assertIn("No internet", text)

    def test_a_failed_download_is_reported_in_plain_words(self):
        effects = FakeEffects()
        effects.fetch_error = DownloadError("could not download it (timed out)")
        outcome, _, run, text = self.run_step(effects=effects)
        self.assertEqual(outcome.state, FAIL)
        self.assertIn("timed out", text)
        run.assert_not_called()

    def test_the_installers_exit_codes(self):
        self.assertEqual(self.run_step(elevated=1638)[0].state, OK)                    # a newer one is already there
        self.assertEqual(self.run_step(elevated=3010)[0], ("warn", "restart needed"))
        outcome, _, _, text = self.run_step(elevated=None)
        self.assertEqual(outcome.state, FAIL)
        self.assertIn("refused", text)
        self.assertEqual(self.run_step(elevated=1603)[0].state, FAIL)

    def test_check_follows_the_real_runtime(self):
        ctx, _ = self.ctx()
        with World(vc_installed=False):
            ctx.facts = {}
            self.assertEqual(machine.RuntimeStep().check(ctx).state, TODO)
        with World(vc_installed=True):
            self.assertEqual(machine.RuntimeStep().check(ctx).state, OK)


def make_backup_folder(base, with_ollama=False):
    """A copy of the Jarvis folder as it would be on the backup drive, with some personal data in it."""
    copy = Path(base) / "Backup-2026-10-20" / "Jarvis" / "New Jarvis"
    copy.mkdir(parents=True)
    for name, text in {"config.py": "#", "Startup.py": "#", ".env": "USER_NAME=Restored Ali\nSTT_MODEL=small.en\nMIC_DEVICE=Gone Microphone\n",
                       "DataBase/Notes/n.txt": "buy milk", "DataBase/voiceprint.npz": "voice", "models/piper/a.onnx": "x"}.items():
        path = copy / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if with_ollama:
        models = copy.parent / "ollama-models" / "models"
        (models / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5").mkdir(parents=True)
        (models / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5" / "1.5b").write_text("{}")
        (models / "blobs").mkdir()
        (models / "blobs" / "sha256-abc").write_text("blob" * 10)
    return copy


class RestoreStepTests(Temp):
    def test_it_only_applies_in_restore_mode(self):
        ctx, _ = self.ctx(mode="fresh")
        self.assertFalse(data.RestoreStep().applies(ctx))
        ctx, _ = self.ctx(mode="restore")
        self.assertTrue(data.RestoreStep().applies(ctx))

    def test_a_folder_given_in_the_answers_is_restored_part_by_part(self):
        copy = make_backup_folder(self.temp)
        ctx, out = self.ctx({"restore_from": str(copy), "restore_parts": ["settings", "notes", "voice"]}, mode="restore")
        outcome = data.RestoreStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual((self.root / "DataBase" / "Notes" / "n.txt").read_text(), "buy milk")
        self.assertEqual(self.env(ctx)["USER_NAME"], "Restored Ali")
        self.assertFalse((self.root / "models").exists())                              # models were not among the chosen parts
        self.assertEqual(ctx.state.data["restored_from"], str(copy))
        self.assertEqual(data.RestoreStep().check(ctx).state, OK)

    def test_the_folder_that_holds_the_copy_is_enough(self):
        copy = make_backup_folder(self.temp)
        ctx, _ = self.ctx({"restore_from": str(copy.parent.parent), "restore_parts": ["settings"]}, mode="restore")
        self.assertEqual(data.RestoreStep().run(ctx).state, OK)
        self.assertTrue((self.root / ".env").exists())

    def test_saved_chat_models_beside_the_copy_are_remembered_for_the_ollama_step(self):
        copy = make_backup_folder(self.temp, with_ollama=True)
        ctx, _ = self.ctx({"restore_from": str(copy), "restore_parts": ["settings"]}, mode="restore")
        data.RestoreStep().run(ctx)
        self.assertTrue(ctx.choices["ollama_restore_from"].endswith("ollama-models\\models") or ctx.choices["ollama_restore_from"].endswith("ollama-models/models"))

    def test_a_file_of_yours_that_differs_is_saved_aside_when_the_backup_wins(self):
        copy = make_backup_folder(self.temp)
        (self.root / ".env").write_text("USER_NAME=Somebody\n")
        ctx, _ = self.ctx({"restore_from": str(copy), "restore_parts": ["settings"], "restore_conflict": "replace"}, mode="restore")
        data.RestoreStep().run(ctx)
        self.assertEqual(self.env(ctx)["USER_NAME"], "Restored Ali")
        self.assertEqual(len(list((self.root / "Backups").rglob(".env"))), 1)

    def test_with_no_backup_chosen_it_falls_back_to_a_fresh_setup(self):
        ctx, out = self.ctx({"restore_pick": "none"}, mode="restore")
        with mock.patch.object(backup_jarvis, "find_backups", return_value=[backup_jarvis.Backup(self.temp, "project", None, "x")]):
            outcome = data.RestoreStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)
        self.assertEqual(ctx.mode, "fresh")
        self.assertIn("set up fresh", out.getvalue())

    def test_a_folder_that_is_not_a_backup_is_refused_then_given_up_on(self):
        ctx, out = self.ctx(mode="restore", replies=["C:\\nowhere\\at all", "", ""])
        ctx.console.interactive = True
        with mock.patch.object(backup_jarvis, "find_backups", return_value=[]):
            outcome = data.RestoreStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)
        self.assertIn("not a Jarvis backup", out.getvalue())

    def test_the_newest_backup_found_is_the_usual_choice(self):
        copy = make_backup_folder(self.temp)
        found = [backup_jarvis.Backup(copy, "project", None, "newest"), backup_jarvis.Backup(self.temp, "project", None, "older")]
        ctx, _ = self.ctx({"restore_parts": ["settings"]}, mode="restore", assume_yes=True)
        with mock.patch.object(backup_jarvis, "find_backups", return_value=found):
            outcome = data.RestoreStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual(self.env(ctx)["USER_NAME"], "Restored Ali")

    def test_a_dry_run_restores_nothing(self):
        copy = make_backup_folder(self.temp)
        ctx, out = self.ctx({"restore_from": str(copy), "restore_parts": ["settings"]}, mode="restore", dry_run=True)
        data.RestoreStep().run(ctx)
        self.assertFalse((self.root / ".env").exists())
        self.assertIn("nothing was copied", out.getvalue())


ANSWERS = {"USER_NAME": "Ali", "ADDRESS_AS": "boss", "DEFAULT_CITY": "Lahore", "HOME_CURRENCY": "usd", "install_ollama": True, "desktop_shortcut": True,
           "start_with_windows": False, "fix_mic_level": True}


class ProfileStepTests(Temp):
    def test_express_asks_about_you_the_chat_brain_and_windows_and_saves_it_all(self):
        ctx, _ = self.ctx(ANSWERS)
        outcome = data.ProfileStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        values = self.env(ctx)
        self.assertEqual((values["USER_NAME"], values["ADDRESS_AS"], values["DEFAULT_CITY"], values["HOME_CURRENCY"]), ("Ali", "boss", "Lahore", "USD"))
        self.assertEqual(values["MIC_VOLUME"], "80")
        self.assertEqual(values["CHAT_AUTO_MAX_MB"], "1600")                         # the light tier's figure
        self.assertEqual(ctx.choices["install_ollama"], True)
        self.assertEqual(ctx.choices["ollama_models"], ["qwen2.5:1.5b"])
        self.assertEqual((ctx.choices["desktop_shortcut"], ctx.choices["start_with_windows"], ctx.choices["fix_mic_level"]), (True, False, True))

    def test_the_settings_file_is_made_from_the_example_with_all_its_explanations(self):
        ctx, _ = self.ctx(ANSWERS)
        data.ProfileStep().run(ctx)
        text = (self.root / ".env").read_text(encoding="utf-8")
        self.assertIn("# How Jarvis greets you", text)
        self.assertIn("USER_NAME=Ali", text)

    def test_declining_the_microphone_fix_switches_it_off_in_the_settings(self):
        ctx, _ = self.ctx(dict(ANSWERS, fix_mic_level=False))
        data.ProfileStep().run(ctx)
        self.assertEqual(self.env(ctx)["MIC_VOLUME"], "0")

    def test_declining_the_chat_brain_leaves_no_models_to_download(self):
        ctx, _ = self.ctx(dict(ANSWERS, install_ollama=False))
        data.ProfileStep().run(ctx)
        self.assertEqual((ctx.choices["install_ollama"], ctx.choices["ollama_models"]), (False, []))

    def test_custom_mode_asks_about_everything_else_too(self):
        answers = dict(ANSWERS, SPEECH_LANGUAGE="en-gb", ollama_models=["llama3.2:3b"], CHAT_WEB_SEARCH=False, LLM_API_KEY="gsk_testkey", LOG_CONVERSATIONS=True,
                       CONVERSATION_LOG_DAYS="7", set_up_email=True, EMAIL_ADDRESS="ali@example.com", EMAIL_PASSWORD="app-pass", GUI_ANIMATIONS=False)
        ctx, _ = self.ctx(answers, express=False, facts=normal_facts("balanced"))
        data.ProfileStep().run(ctx)
        values = self.env(ctx)
        self.assertEqual(values["SPEECH_LANGUAGE"], "en-gb")
        self.assertEqual(ctx.choices["ollama_models"], ["llama3.2:3b"])
        self.assertEqual((values["CHAT_WEB_SEARCH"], values["LLM_API_KEY"], values["CONVERSATION_LOG_DAYS"]), ("false", "gsk_testkey", "7"))
        self.assertEqual((values["EMAIL_ADDRESS"], values["EMAIL_PASSWORD"], values["GUI_ANIMATIONS"]), ("ali@example.com", "app-pass", "false"))

    def test_a_silly_answer_does_not_get_into_the_settings(self):
        ctx, out = self.ctx(dict(ANSWERS, HOME_CURRENCY="dollars"))
        data.ProfileStep().run(ctx)
        self.assertEqual(self.env(ctx)["HOME_CURRENCY"], "PKR")                      # the usual one, because "dollars" is not a currency code
        self.assertIn("three letters", out.getvalue())

    def test_the_step_counts_as_done_once_answered_or_for_a_hand_made_install(self):
        step = data.ProfileStep()
        ctx, _ = self.ctx()
        self.assertEqual(step.check(ctx).state, TODO)                                # a new folder: nothing yet
        (self.root / ".env").write_text("USER_NAME=Ali\n")
        self.assertEqual(step.check(ctx).state, OK)                                  # set up by hand before the wizard existed
        self.assertIn("already in .env", step.check(ctx).detail)
        ctx.state.save()                                                             # (the wizard has now been here)
        self.assertEqual(step.check(ctx).state, TODO)
        ctx.state.step("profile", "ok", "")
        self.assertEqual(step.check(ctx).state, OK)
        ctx.force = True
        self.assertEqual(step.check(ctx).state, TODO)

    def test_an_interrupted_run_asks_again_instead_of_trusting_the_copied_example(self):
        ctx, _ = self.ctx(ANSWERS)
        with mock.patch.object(data.questions, "about_you", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                data.ProfileStep().run(ctx)
        self.assertTrue((self.root / ".env").exists())
        self.assertEqual(data.ProfileStep().check(ctx).state, TODO)

    def test_a_dry_run_writes_no_settings(self):
        ctx, _ = self.ctx(ANSWERS, dry_run=True)
        data.ProfileStep().run(ctx)
        self.assertFalse((self.root / ".env").exists())


class PackagesStepTests(Temp):
    def effects_that_install(self, world, ok=True):
        effects = FakeEffects()

        def installed(command):
            if ok:
                world.missing.clear()
            return RunResult(0 if ok else 1, "Collecting x\nSuccessfully installed x")
        effects.when(lambda c: "install" in c and "-r" in c, installed)
        return effects

    def test_check_counts_what_is_missing(self):
        with World(packages_missing=["PyQt5", "yt_dlp"]):
            ctx, _ = self.ctx()
            check = install.PackagesStep().check(ctx)
        self.assertEqual(check.state, TODO)
        self.assertIn("2 missing, 1 of them essential", check.detail)
        with World():
            self.assertEqual(install.PackagesStep().check(ctx).state, OK)

    def test_it_installs_from_requirements_and_checks_the_window_and_voice_libraries_together(self):
        with World(packages_missing=["PyQt5", "faster_whisper"]) as world:
            effects = self.effects_that_install(world)
            ctx, out = self.ctx(effects=effects)
            outcome = install.PackagesStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        install_commands = [c for c in effects.runs if "install" in c]
        self.assertEqual(install_commands[0], [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r", "requirements.txt"])
        self.assertTrue(any("native_libs.preload()" in " ".join(c) for c in effects.runs))
        self.assertIn("All 30 packages are installed", out.getvalue())

    def test_a_flaky_connection_is_retried_then_the_packages_go_in_one_at_a_time(self):
        with World(packages_missing=["yt_dlp"]) as world:
            effects = FakeEffects()
            effects.when(lambda c: "-r" in c, RunResult(1, "ERROR: network trouble"))
            effects.when(lambda c: "install" in c and "-r" not in c, lambda c: (world.missing.clear(), RunResult(0, ""))[1])
            ctx, out = self.ctx(effects=effects)
            outcome = install.PackagesStep().run(ctx)
        self.assertEqual(len([c for c in effects.runs if "-r" in c]), 3)
        singles = [c[-1] for c in effects.runs if "install" in c and "-r" not in c]
        self.assertEqual(singles, ["python-dotenv>=1.0", "requests>=2.32", 'audioop-lts>=0.2.1; python_version >= "3.13"'])
        self.assertEqual(outcome.state, OK)
        self.assertIn("one at a time", out.getvalue())

    def test_a_missing_essential_package_is_a_failure_and_an_optional_one_a_warning(self):
        for missing, expected in ((["PyQt5"], FAIL), (["yt_dlp"], WARN)):
            with World(packages_missing=missing):
                effects = FakeEffects()
                effects.when(lambda c: "install" in c, RunResult(1, "ERROR"))
                ctx, out = self.ctx(effects=effects)
                outcome = install.PackagesStep().run(ctx)
            self.assertEqual(outcome.state, expected, missing)
            self.assertIn("is not installed - it is for", out.getvalue())

    def test_libraries_that_crash_together_are_reported(self):
        with World() as world:
            effects = FakeEffects()
            effects.when(lambda c: "native_libs.preload()" in " ".join(c), RunResult(-1073741819, "access violation"))
            ctx, out = self.ctx(effects=effects)
            outcome = install.PackagesStep().run(ctx)
        self.assertEqual(outcome.state, FAIL)
        self.assertIn("crashed when loaded together", out.getvalue())

    def test_without_internet_pip_is_not_even_started(self):
        with World(packages_missing=["PyQt5"]):
            effects = FakeEffects()
            ctx, out = self.ctx(effects=effects, facts=normal_facts(internet=False))
            outcome = install.PackagesStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertEqual(effects.runs, [])

    def test_a_missing_pip_is_added_first(self):
        with World(packages_missing=["PyQt5"]) as world:
            effects = self.effects_that_install(world)
            effects.when(lambda c: c[-1] == "--version", RunResult(1, "no pip"))
            ctx, _ = self.ctx(effects=effects)
            install.PackagesStep().run(ctx)
        self.assertTrue(any("ensurepip" in c for c in effects.runs))

    def test_requirement_lines_drop_comments_and_blank_lines(self):
        self.assertEqual(install.requirement_lines(self.root / "requirements.txt"), ["python-dotenv>=1.0", "requests>=2.32", 'audioop-lts>=0.2.1; python_version >= "3.13"'])

    def test_the_plan_lists_the_command_and_what_is_missing(self):
        with World(packages_missing=["PyQt5"]):
            ctx, _ = self.ctx()
            plan = install.PackagesStep().plan(ctx)
        self.assertIn("pip install -r requirements.txt", plan[0])
        self.assertIn("PyQt5", plan[1])


class ModelsStepTests(Temp):
    def models_run(self, answers=None, effects=None, **kwargs):
        effects = effects or FakeEffects()
        pretend_downloads(effects, self.root)
        ctx, out = self.ctx(answers, effects=effects, **kwargs)
        outcome = install.ModelsStep().run(ctx)
        return outcome, effects, ctx, out.getvalue()

    def test_a_fresh_pc_gets_the_voice_whisper_the_wake_word_and_the_voice_model(self):
        outcome, effects, ctx, _ = self.models_run()
        self.assertEqual(outcome.state, OK)
        commands = [" ".join(c[1:]) for c in effects.runs]
        self.assertIn("-m piper.download_voices en_GB-alan-medium --download-dir models/piper", commands)
        self.assertIn("stt.py --download", commands)
        self.assertIn("wakeword.py --download", commands)
        self.assertIn("speaker.py --download", commands)
        self.assertEqual(self.env(ctx)["STT_MODEL"], "base.en")                      # the light tier's model, saved
        self.assertEqual(install.ModelsStep().check(ctx).state, OK)

    def test_the_whisper_download_is_told_which_model_by_the_environment(self):
        _, effects, _, _ = self.models_run()
        index = next(i for i, c in enumerate(effects.runs) if "stt.py" in c)
        self.assertEqual(effects.envs[index], {"STT_MODEL": "base.en"})

    def test_a_stronger_pc_gets_the_more_accurate_model(self):
        _, effects, ctx, _ = self.models_run(facts=normal_facts("strong"))
        self.assertEqual(self.env(ctx)["STT_MODEL"], "small.en")

    def test_what_is_already_there_is_not_downloaded_again(self):
        self.models_run()
        outcome, effects, _, _ = self.models_run()
        self.assertEqual(outcome.state, OK)
        self.assertEqual(effects.runs, [] if not effects.runs else effects.runs)
        self.assertEqual([c for c in effects.runs if "download" in " ".join(c)], [])

    def test_in_custom_mode_you_choose_the_voices_and_the_speech_model(self):
        answers = {"STT_MODEL": "tiny.en", "download_voices": ["en_GB-alan-medium", "en_US-ryan-medium"]}
        _, effects, ctx, _ = self.models_run(answers, express=False)
        voices = [c[c.index("piper.download_voices") + 1] for c in effects.runs if "piper.download_voices" in c]
        self.assertEqual(voices, ["en_GB-alan-medium", "en_US-ryan-medium"])
        self.assertEqual(self.env(ctx)["STT_MODEL"], "tiny.en")

    def test_a_restored_speech_model_choice_is_kept(self):
        (self.root / ".env").write_text("STT_MODEL=small.en\n")
        _, _, ctx, _ = self.models_run(mode="restore")
        self.assertEqual(self.env(ctx)["STT_MODEL"], "small.en")

    def test_without_internet_nothing_is_attempted(self):
        outcome, effects, _, text = self.models_run(facts=normal_facts(internet=False))
        self.assertEqual(outcome.state, WARN)
        self.assertEqual(effects.runs, [])
        self.assertIn("cannot be reached", text)

    def test_a_download_that_fails_twice_is_reported_and_the_rest_carry_on(self):
        effects = FakeEffects()
        pretend_downloads(effects, self.root)
        effects.rules.insert(0, (has("stt.py", "--download"), RunResult(1, "Traceback\nConnectionError: no route")))
        outcome, effects, ctx, text = self.models_run(effects=effects)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("Whisper", outcome.detail)
        self.assertIn("ConnectionError", text)
        self.assertEqual(len([c for c in effects.runs if "stt.py" in c]), 2)         # tried once more
        self.assertTrue(system.model_facts(self.root)["wakeword_ready"])              # the others were still fetched

    def test_the_plan_names_each_download_with_its_size(self):
        ctx, _ = self.ctx()
        plan = install.ModelsStep().plan(ctx)
        self.assertEqual(len(plan), 4)
        self.assertIn("63 MB", plan[0])


def ollama_world(effects, running=False, models=()):
    effects.json = {"/api/version": {"version": "0.5"}, "/api/tags": {"models": [{"name": m} for m in models]}} if running else {}


class OllamaStepTests(Temp):
    FACTS = normal_facts()

    def make(self, effects=None, answers=None, choices=None, facts=None):
        effects = effects or FakeEffects()
        ctx, out = self.ctx(answers, effects=effects, facts=facts)
        ctx.choices.update(choices or {"install_ollama": True, "ollama_models": ["qwen2.5:1.5b"]})
        return ctx, effects, out

    def test_it_is_skipped_when_you_said_no(self):
        ctx, _, _ = self.make(choices={"install_ollama": False})
        self.assertFalse(install.OllamaStep().applies(ctx))

    def test_everything_already_there_is_ok_and_nothing_is_done(self):
        effects = FakeEffects()
        ollama_world(effects, running=True, models=["qwen2.5:1.5b", "llama3.2:3b"])
        with World(ollama_exe=r"C:\Ollama\ollama.exe"):
            ctx, effects, _ = self.make(effects)
            self.assertEqual(install.OllamaStep().check(ctx).state, OK)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual((effects.fetched, effects.visible, effects.detached), ([], [], []))

    def test_not_installed_it_downloads_checks_installs_starts_and_pulls(self):
        effects = FakeEffects()
        effects.signature_result = Signature("Valid", "CN=Ollama Inc., O=Ollama Inc.")
        with World(ollama_exe="") as world:
            def installer(command):
                world.ollama_exe = r"C:\Ollama\ollama.exe"
                effects.json = {"/api/version": {"version": "0.5"}, "/api/tags": {"models": []}}
                return RunResult(0, "installed")

            def pull(command):
                effects.json["/api/tags"] = {"models": [{"name": "qwen2.5:1.5b"}]}
                return RunResult(0, "")
            effects.when(lambda c: str(c[0]).endswith("OllamaSetup.exe"), installer)
            effects.when(has("pull"), pull)
            ctx, _, out = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual(effects.fetched[0][0], install.OLLAMA_URL)
        self.assertEqual(effects.runs[0][1:], ["/SILENT", "/NORESTART"])
        self.assertEqual(effects.visible[0][1:], ["pull", "qwen2.5:1.5b"])

    def test_an_installer_that_is_not_validly_signed_is_never_run(self):
        effects = FakeEffects()
        effects.signature_result = Signature("HashMismatch", "")
        with World(ollama_exe=""):
            ctx, _, out = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, FAIL)
        self.assertEqual(effects.runs, [])

    def test_a_valid_signature_from_an_unexpected_signer_needs_your_say_so(self):
        effects = FakeEffects()
        effects.signature_result = Signature("Valid", "CN=Somebody Else")
        with World(ollama_exe=""):
            ctx, _, _ = self.make(effects, answers={"ollama_signer_ok": False})
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)
        self.assertEqual(effects.runs, [])

    def test_without_internet_it_is_a_warning(self):
        with World(ollama_exe=""):
            ctx, effects, _ = self.make(facts=normal_facts(internet=False))
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertEqual(effects.fetched, [])

    def test_a_failed_download_is_reported(self):
        effects = FakeEffects()
        effects.fetch_error = DownloadError("could not download (timed out)")
        with World(ollama_exe=""):
            ctx, _, out = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, FAIL)
        self.assertIn("timed out", out.getvalue())

    def test_installed_but_not_running_it_is_started_and_the_model_pulled(self):
        effects = FakeEffects()
        started = []

        def start(command):
            started.append(command)
            effects.json = {"/api/version": {"version": "0.5"}, "/api/tags": {"models": []}}
            return True
        effects.start_detached = start
        effects.when(has("pull"), lambda c: (effects.json["/api/tags"].update({"models": [{"name": "qwen2.5:1.5b"}]}), RunResult(0, ""))[1])
        with World(ollama_exe=r"C:\Ollama\ollama.exe"):
            ctx, _, _ = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(started, [[r"C:\Ollama\ollama.exe", "serve"]])
        self.assertEqual(outcome.state, OK)

    def test_one_that_will_not_start_is_a_warning_with_what_to_do(self):
        effects = FakeEffects()
        with World(ollama_exe=r"C:\Ollama\ollama.exe"), mock.patch.object(install.time, "time", side_effect=[0, 0, 100, 100, 200]):
            ctx, _, out = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("did not start", out.getvalue())

    def test_a_model_that_cannot_be_pulled_is_reported_with_the_command_to_try_later(self):
        effects = FakeEffects()
        ollama_world(effects, running=True, models=[])
        effects.when(has("pull"), RunResult(1, ""))
        with World(ollama_exe=r"C:\Ollama\ollama.exe"):
            ctx, _, out = self.make(effects)
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("ollama pull qwen2.5:1.5b", out.getvalue())

    def test_saved_models_go_back_first_and_spare_the_download(self):
        backup = make_backup_folder(self.temp, with_ollama=True)
        saved = backup.parent / "ollama-models" / "models"
        home = self.temp / "home"
        effects = FakeEffects()
        ollama_world(effects, running=True, models=["qwen2.5:1.5b"])
        with World(ollama_exe=r"C:\Ollama\ollama.exe"), mock.patch.object(Path, "home", classmethod(lambda cls: home)):
            ctx, _, _ = self.make(effects, choices={"install_ollama": True, "ollama_restore_from": str(saved)})
            outcome = install.OllamaStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertTrue((home / ".ollama" / "models" / "blobs" / "sha256-abc").exists())
        self.assertEqual(effects.visible, [])                                          # nothing was downloaded

    def test_model_names_are_read_from_the_manifests(self):
        backup = make_backup_folder(self.temp, with_ollama=True)
        self.assertEqual(install.models_in(backup.parent / "ollama-models" / "models"), ["qwen2.5:1.5b"])

    def test_copying_is_additive(self):
        source, target = self.temp / "s", self.temp / "t"
        (source / "a").mkdir(parents=True)
        (source / "a" / "one.bin").write_text("12345")
        (source / "two.bin").write_text("abc")
        (target / "a").mkdir(parents=True)
        (target / "a" / "one.bin").write_text("12345")                                 # already there, same size
        self.assertEqual(install.copy_additively(source, target), 1)
        self.assertEqual((target / "two.bin").read_text(), "abc")

    def test_asked_directly_it_checks_whether_you_want_it(self):
        effects = FakeEffects()
        ctx, _ = self.ctx({"install_ollama": False}, effects=effects)
        self.assertEqual(install.OllamaStep().run(ctx).state, SKIP)

    def test_the_plan_says_what_would_be_done(self):
        effects = FakeEffects()
        with World(ollama_exe=""):
            ctx, _, _ = self.make(effects)
            plan = install.OllamaStep().plan(ctx)
        self.assertTrue(any("OllamaSetup.exe" in line for line in plan))
        self.assertTrue(any("qwen2.5:1.5b" in line for line in plan))


class VoiceStepTests(Temp):
    def install_voices(self, *names):
        folder = self.root / "models" / "piper"
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / f"{name}.onnx").write_text("x")
            (folder / f"{name}.onnx.json").write_text("{}")

    def test_express_picks_the_voice_the_waking_method_and_keeps_the_default_microphone(self):
        self.install_voices("en_GB-alan-medium", "en_US-ryan-medium")
        effects = FakeEffects()
        ctx, _ = self.ctx({"preview_voices": True, "PIPER_VOICE": "en_US-ryan-medium", "INPUT_MODE": "voice", "wake_method": "word", "test_microphone": False}, effects=effects)
        with World(microphones=["Mic A"]):
            outcome = personal.VoiceStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        values = self.env(ctx)
        self.assertEqual((values["PIPER_VOICE"], values["TTS_ENGINE"], values["INPUT_MODE"]), ("en_US-ryan-medium", "auto", "voice"))
        self.assertEqual((values["WAKE_WORD"], values["CLAP_WAKE"]), ("true", "false"))
        previews = [(c[1:], e) for c, e in zip(effects.runs, effects.envs) if "tts_piper.py" in " ".join(c)]
        self.assertEqual([env["PIPER_VOICE"] for _, env in previews], ["en_GB-alan-medium", "en_US-ryan-medium"])   # each voice was played

    def test_each_wake_method_sets_the_two_switches(self):
        for method, word, claps in (("both", "true", "true"), ("word", "true", "false"), ("claps", "false", "true"), ("buttons", "false", "false")):
            ctx, _ = self.ctx({"wake_method": method, "INPUT_MODE": "voice", "test_microphone": False})
            with World():
                personal.VoiceStep().run(ctx)
            self.assertEqual((self.env(ctx)["WAKE_WORD"], self.env(ctx)["CLAP_WAKE"]), (word, claps), method)

    def test_with_several_microphones_you_choose_one_by_name(self):
        ctx, _ = self.ctx({"MIC_DEVICE": "USB Headset", "INPUT_MODE": "voice", "test_microphone": False})
        with World(microphones=["Realtek", "USB Headset"]):
            personal.VoiceStep().run(ctx)
        self.assertEqual(self.env(ctx)["MIC_DEVICE"], "USB Headset")

    def test_typing_only_asks_nothing_about_the_microphone(self):
        ctx, _ = self.ctx({"INPUT_MODE": "text"})
        with World():
            personal.VoiceStep().run(ctx)
        self.assertEqual(self.env(ctx)["INPUT_MODE"], "text")
        asked = [key for key, _ in ctx.console.asked]
        self.assertNotIn("wake_method", asked)
        self.assertNotIn("MIC_DEVICE", asked)

    def test_custom_mode_also_asks_about_speed_greeting_clap_count_speech_and_the_voice_lock(self):
        answers = {"TTS_ENABLED": True, "TTS_RATE": "2", "STARTUP_GREETING": "full", "INPUT_MODE": "voice", "wake_method": "claps", "CLAP_COUNT": "3",
                   "STT_ENGINE": "whisper", "VOICE_LOCK": "owner", "test_microphone": False}
        self.install_voices("en_GB-alan-medium")
        ctx, _ = self.ctx(answers, express=False)
        with World():
            personal.VoiceStep().run(ctx)
        values = self.env(ctx)
        self.assertEqual((values["TTS_RATE"], values["STARTUP_GREETING"], values["CLAP_COUNT"], values["STT_ENGINE"], values["VOICE_LOCK"]), ("2", "full", "3", "whisper", "owner"))

    def test_speech_off_saves_that_and_asks_nothing_more_about_the_voice(self):
        ctx, _ = self.ctx({"TTS_ENABLED": False, "INPUT_MODE": "text"}, express=False)
        with World():
            personal.VoiceStep().run(ctx)
        self.assertEqual(self.env(ctx)["TTS_ENABLED"], "false")
        self.assertNotIn("PIPER_VOICE", [key for key, _ in ctx.console.asked])

    def test_with_no_natural_voice_installed_it_says_the_windows_voice_will_be_used(self):
        ctx, out = self.ctx({"INPUT_MODE": "text"})
        with World():
            personal.VoiceStep().run(ctx)
        self.assertIn("Windows voice", out.getvalue())

    def test_a_restored_microphone_that_is_not_on_this_pc_is_dropped(self):
        (self.root / ".env").write_text("MIC_DEVICE=Gone Microphone\nPIPER_VOICE=en_GB-alan-medium\n")
        ctx, out = self.ctx(mode="restore")
        with World(microphones=["Realtek"]):
            outcome = personal.VoiceStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual(self.env(ctx)["MIC_DEVICE"], "")
        self.assertIn("is not on this PC", out.getvalue())

    def test_a_restored_microphone_that_is_here_is_kept(self):
        (self.root / ".env").write_text("MIC_DEVICE=Realtek\n")
        ctx, _ = self.ctx(mode="restore")
        with World(microphones=["Realtek High Definition"]):
            personal.VoiceStep().run(ctx)
        self.assertEqual(self.env(ctx)["MIC_DEVICE"], "Realtek")

    def test_the_step_counts_as_done_once_chosen_or_for_a_hand_made_install(self):
        step = personal.VoiceStep()
        ctx, _ = self.ctx()
        self.assertEqual(step.check(ctx).state, TODO)
        (self.root / ".env").write_text("INPUT_MODE=voice\n")
        self.assertEqual(step.check(ctx).state, OK)
        ctx.state.save()
        self.assertEqual(step.check(ctx).state, TODO)


class PasswordStepTests(Temp):
    def values(self, ctx):
        return ctx.env.values()

    def test_check_tells_the_three_situations_apart(self):
        step = personal.PasswordStep()
        ctx, _ = self.ctx()
        self.assertEqual(step.check(ctx).state, TODO)
        (self.root / ".env").write_text("JARVIS_PASSWORD=plain\n")
        self.assertEqual(step.check(ctx).state, WARN)
        (self.root / ".env").write_text("JARVIS_PASSWORD_HASH=pbkdf2_sha256$1$ab$cd\nJARVIS_PASSWORD=\n")
        self.assertEqual(step.check(ctx).state, OK)

    def test_a_plain_password_is_scrambled_without_changing_it(self):
        (self.root / ".env").write_text("JARVIS_PASSWORD=my old password\n")
        ctx, out = self.ctx({"scramble_password": True})
        outcome = personal.PasswordStep().run(ctx)
        self.assertEqual(outcome, ("ok", "scrambled"))
        values = self.values(ctx)
        self.assertEqual(values["JARVIS_PASSWORD"], "")
        self.assertTrue(gate._matches_hash("my old password", values["JARVIS_PASSWORD_HASH"]))
        self.assertNotIn("my old password", out.getvalue())

    def test_a_new_password_is_stored_only_as_a_hash(self):
        ctx, out = self.ctx({"JARVIS_PASSWORD": "a fresh passphrase"})
        outcome = personal.PasswordStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        text = (self.root / ".env").read_text(encoding="utf-8")
        self.assertNotIn("a fresh passphrase", text)
        self.assertTrue(gate._matches_hash("a fresh passphrase", self.values(ctx)["JARVIS_PASSWORD_HASH"]))
        self.assertNotIn("a fresh passphrase", out.getvalue())

    def test_an_existing_password_is_kept_unless_you_say_change_it(self):
        (self.root / ".env").write_text("JARVIS_PASSWORD_HASH=pbkdf2_sha256$1$ab$cd\n")
        ctx, _ = self.ctx({"change_password": False})
        self.assertEqual(personal.PasswordStep().run(ctx), ("ok", "kept"))
        self.assertEqual(self.values(ctx)["JARVIS_PASSWORD_HASH"], "pbkdf2_sha256$1$ab$cd")
        ctx, _ = self.ctx({"change_password": True, "JARVIS_PASSWORD": "brand new one"})
        self.assertEqual(personal.PasswordStep().run(ctx).state, OK)
        self.assertTrue(gate._matches_hash("brand new one", self.values(ctx)["JARVIS_PASSWORD_HASH"]))

    def test_a_password_everybody_would_try_needs_confirming(self):
        ctx, out = self.ctx({"JARVIS_PASSWORD": "password", "weak_password_ok": False})
        outcome = personal.PasswordStep().run(ctx)
        self.assertEqual(outcome.state, WARN)                                        # refused, then nothing else to try in a scripted run
        self.assertNotIn("JARVIS_PASSWORD_HASH", self.values(ctx))
        ctx, _ = self.ctx({"JARVIS_PASSWORD": "password", "weak_password_ok": True})
        self.assertEqual(personal.PasswordStep().run(ctx).state, OK)

    def test_typing_it_twice_is_checked_and_nothing_typed_means_no_password(self):
        ctx, out = self.ctx(replies=["abcdef", "abcxyz", "abcdef", "abcdef"], interactive=True)
        self.assertEqual(personal.PasswordStep().run(ctx).state, OK)
        self.assertIn("different", out.getvalue())
        (self.root / ".env").unlink()
        ctx, out = self.ctx(replies=[""], interactive=True)
        outcome = personal.PasswordStep().run(ctx)
        self.assertEqual(outcome, ("warn", "no password"))
        self.assertIn("will let nobody in", out.getvalue())

    def test_unattended_with_no_password_given_it_warns_and_changes_nothing(self):
        ctx, _ = self.ctx(assume_yes=True)
        self.assertEqual(personal.PasswordStep().run(ctx).state, WARN)
        self.assertFalse((self.root / ".env").exists())

    def test_a_dry_run_stores_nothing(self):
        ctx, _ = self.ctx({"JARVIS_PASSWORD": "a fresh passphrase"}, dry_run=True)
        personal.PasswordStep().run(ctx)
        self.assertFalse((self.root / ".env").exists())


class IdentityStepTests(Temp):
    def with_models(self, speaker=True):
        if speaker:
            (self.root / "models" / "speaker").mkdir(parents=True)
            (self.root / "models" / "speaker" / "nemo_en_titanet_small.onnx").write_text("s")

    def test_the_voice_lesson_runs_when_you_say_yes_and_the_model_is_there(self):
        self.with_models()
        effects = FakeEffects()
        ctx, _ = self.ctx({"enroll_voice": True, "enroll_face": False}, effects=effects)
        with World(camera=False):
            outcome = personal.IdentityStep().run(ctx)
        self.assertEqual(effects.visible[0][1:], ["enroll_voice.py"])
        self.assertEqual(outcome, ("ok", "voice"))

    def test_without_the_voice_model_the_lesson_waits(self):
        ctx, out = self.ctx({"enroll_voice": True, "enroll_face": False})
        with World(camera=False):
            outcome = personal.IdentityStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)
        self.assertIn("has to wait", out.getvalue())

    def test_the_face_lesson_runs_both_tools_in_order(self):
        self.with_models()
        (self.root / "DataBase").mkdir()
        (self.root / "DataBase" / "voiceprint.npz").write_text("v")
        effects = FakeEffects()
        ctx, _ = self.ctx({"enroll_face": True}, effects=effects)
        with World(camera=True):
            outcome = personal.IdentityStep().run(ctx)
        self.assertEqual([c[1] for c in effects.visible], ["DataBase/FaceDetectionModule/SampleGenerator.py", "DataBase/FaceDetectionModule/ModelTrainer.py"])
        self.assertEqual(outcome, ("ok", "face"))

    def test_if_the_photo_tool_fails_the_trainer_does_not_run(self):
        self.with_models()
        (self.root / "DataBase").mkdir()
        (self.root / "DataBase" / "voiceprint.npz").write_text("v")
        effects = FakeEffects()
        effects.visible_code = 1
        effects.when(has("SampleGenerator"), RunResult(1, ""))
        ctx, out = self.ctx({"enroll_face": True}, effects=effects)
        with World(camera=True):
            personal.IdentityStep().run(ctx)
        self.assertEqual(len(effects.visible), 1)
        self.assertIn("did not finish", out.getvalue())

    def test_no_camera_means_no_question_about_a_face(self):
        self.with_models()
        (self.root / "DataBase").mkdir()
        (self.root / "DataBase" / "voiceprint.npz").write_text("v")
        ctx, out = self.ctx({"enroll_face": True})
        with World(camera=False):
            outcome = personal.IdentityStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)
        self.assertEqual(ctx.console.asked, [])

    def test_in_a_restore_a_voice_lesson_is_not_pushed(self):
        self.with_models()
        ctx, _ = self.ctx(assume_yes=True, mode="restore")
        with World(camera=False):
            outcome = personal.IdentityStep().run(ctx)
        self.assertEqual(outcome.state, SKIP)                                         # (the usual answer is no when restoring)

    def test_the_check_says_what_he_knows(self):
        ctx, _ = self.ctx()
        self.assertEqual(personal.IdentityStep().check(ctx).state, TODO)
        (self.root / "DataBase").mkdir()
        (self.root / "DataBase" / "voiceprint.npz").write_text("v")
        self.assertIn("voice", personal.IdentityStep().check(ctx).detail)


class LanguageModelStepTests(Temp):
    def test_it_trains_when_there_is_no_model(self):
        effects = FakeEffects()
        pretend_downloads(effects, self.root)
        ctx, _ = self.ctx(effects=effects)
        with World():
            outcome = personal.LanguageModelStep().run(ctx)
        self.assertEqual(outcome.state, OK)
        self.assertEqual(effects.runs[0][1:], ["training/train_nlu.py"])
        with World():
            self.assertEqual(personal.LanguageModelStep().check(ctx).state, OK)

    def test_it_waits_if_scikit_learn_is_missing(self):
        ctx, _ = self.ctx()
        with World(packages_missing=["sklearn"]):
            self.assertEqual(personal.LanguageModelStep().check(ctx).state, WARN)
            self.assertEqual(personal.LanguageModelStep().run(ctx).state, WARN)

    def test_a_failed_training_is_a_warning_with_the_end_of_its_output(self):
        effects = FakeEffects()
        effects.when(has("train_nlu"), RunResult(1, "Traceback\nValueError: bad phrase file"))
        ctx, out = self.ctx(effects=effects)
        with World():
            outcome = personal.LanguageModelStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("bad phrase file", out.getvalue())


class WindowsStepTests(Temp):
    def test_it_only_applies_when_there_is_something_to_do(self):
        ctx, _ = self.ctx()
        with World(startup=False):
            self.assertFalse(personal.WindowsStep().applies(ctx))                         # nothing chosen
            ctx.choices.update({"desktop_shortcut": False, "start_with_windows": False})
            self.assertFalse(personal.WindowsStep().applies(ctx))                         # both "no", and it was already off
            ctx.choices["desktop_shortcut"] = True
            self.assertTrue(personal.WindowsStep().applies(ctx))
            ctx.choices.update({"desktop_shortcut": False, "start_with_windows": True})
            self.assertTrue(personal.WindowsStep().applies(ctx))                          # off now, wanted on
        with World(startup=True):
            self.assertFalse(personal.WindowsStep().applies(ctx))                         # on now, wanted on: nothing to do
            ctx.choices["start_with_windows"] = False
            self.assertTrue(personal.WindowsStep().applies(ctx))                          # on now, wanted off

    def test_it_makes_the_chosen_shortcuts(self):
        ctx, out = self.ctx()
        ctx.choices.update({"desktop_shortcut": True, "start_with_windows": True})
        with World(startup=False) as world:
            outcome = personal.WindowsStep().run(ctx)
        self.assertEqual(outcome, ("ok", "desktop, startup"))
        self.assertTrue(world.desktop_shortcut_made)
        self.assertEqual(world.startup_calls, [True])
        self.assertIn("open when you log in", out.getvalue())

    def test_a_no_to_starting_with_windows_removes_it_only_if_it_was_on(self):
        ctx, _ = self.ctx()
        ctx.choices.update({"desktop_shortcut": False, "start_with_windows": False})
        with World(startup=True) as world:
            personal.WindowsStep().run(ctx)
        self.assertEqual(world.startup_calls, [False])
        with World(startup=False) as world:
            personal.WindowsStep().run(ctx)
        self.assertEqual(world.startup_calls, [])                                          # nothing to take out: nothing was touched

    def test_the_check_notices_a_missing_desktop_shortcut(self):
        ctx, _ = self.ctx()
        ctx.choices["desktop_shortcut"] = True
        with World():
            check = personal.WindowsStep().check(ctx)
        self.assertEqual(check.state, TODO)
        self.assertIn("desktop shortcut", check.detail)

    def test_a_shortcut_that_cannot_be_made_is_a_warning_not_a_stop(self):
        ctx, out = self.ctx()
        ctx.choices["desktop_shortcut"] = True
        with World():
            with mock.patch.object(windows, "desktop_shortcut", side_effect=RuntimeError("PowerShell failed")):
                outcome = personal.WindowsStep().run(ctx)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("Start-Jarvis.bat", out.getvalue())

    def test_the_plan_says_what_would_be_done(self):
        ctx, _ = self.ctx()
        ctx.choices.update({"desktop_shortcut": True, "start_with_windows": True})
        with World(startup=False):
            plan = personal.WindowsStep().plan(ctx)
        self.assertEqual(len(plan), 2)


class SelfCheckStepTests(Temp):
    def run_it(self, effects, answers=None, mode="fresh"):
        ctx, out = self.ctx(answers or {"test_voice": False, "run_tests": False}, effects=effects, mode=mode)
        with World():
            outcome = finish.SelfCheckStep().run(ctx)
        return outcome, out.getvalue()

    def test_when_everything_works_it_says_so(self):
        effects = FakeEffects()
        outcome, text = self.run_it(effects, {"test_voice": True, "run_tests": True})
        self.assertEqual(outcome.state, OK)
        self.assertTrue(effects.commands("speech.py"))
        self.assertTrue(effects.commands("unittest"))
        self.assertIn("Every part of Jarvis loads", text)

    def test_a_part_that_does_not_load_is_reported_with_the_reason(self):
        effects = FakeEffects()
        effects.when(lambda c: "import config" in " ".join(c), RunResult(1, "Traceback\nImportError: DLL load failed while importing onnxruntime"))
        outcome, text = self.run_it(effects)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("DLL load failed", text)

    def test_a_microphone_problem_is_reported_with_the_advice_lines(self):
        effects = FakeEffects()
        effects.when(has("microphone.py"), RunResult(1, "  [FAIL] winmm: no device\n  -> Plug in a microphone.\n"))
        outcome, text = self.run_it(effects)
        self.assertEqual(outcome.state, WARN)
        self.assertIn("Plug in a microphone", text)

    def test_speech_and_tests_are_only_run_when_you_agree(self):
        effects = FakeEffects()
        self.run_it(effects)
        self.assertEqual(effects.commands("speech.py"), [])
        self.assertEqual(effects.commands("unittest"), [])

    def test_failing_selftests_are_a_warning(self):
        effects = FakeEffects()
        effects.when(has("unittest"), RunResult(1, "Ran 10 tests in 1s\nFAILED (failures=2)"))
        outcome, text = self.run_it(effects, {"test_voice": False, "run_tests": True})
        self.assertEqual(outcome.state, WARN)
        self.assertIn("FAILED", text)

    def test_the_voice_that_does_not_speak_is_reported(self):
        effects = FakeEffects()
        effects.when(has("speech.py"), RunResult(1, "[FAIL] no sound"))
        outcome, _ = self.run_it(effects, {"test_voice": True, "run_tests": False})
        self.assertEqual(outcome.state, WARN)
        self.assertIn("voice needs attention", outcome.detail)

    def test_the_import_check_covers_every_part_of_jarvis(self):
        for name in ("config", "gate", "speech", "stt", "tts_piper", "wakeword", "speaker", "microphone", "listener", "LocalBrain", "gui.main_window"):
            self.assertIn(name, finish.IMPORT_CODE)


if __name__ == "__main__":
    unittest.main()
