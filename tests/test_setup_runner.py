"""Tests for the wizard as a whole (the order of the steps, running it twice, a dry run, the health check) and its command line:
python -m unittest tests.test_setup_runner -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate  # noqa: E402
from jarvis_setup import cli, system, windows  # noqa: E402
from jarvis_setup.effects import RunResult  # noqa: E402
from jarvis_setup.runner import Runner  # noqa: E402
from jarvis_setup.steps import all_steps  # noqa: E402
from jarvis_setup.steps.base import FAIL, OK, Outcome, Step  # noqa: E402
from tests.setup_support import FakeEffects, World, has, install_models, make_context, normal_facts, pretend_downloads, project  # noqa: E402

EVERYTHING = {"USER_NAME": "Ali", "ADDRESS_AS": "boss", "DEFAULT_CITY": "Lahore", "HOME_CURRENCY": "PKR", "install_ollama": False, "desktop_shortcut": False,
              "start_with_windows": False, "fix_mic_level": True, "install_vc_runtime": True, "INPUT_MODE": "voice", "wake_method": "both", "test_microphone": False,
              "JARVIS_PASSWORD": "a fresh passphrase", "enroll_voice": False, "enroll_face": False, "test_voice": False, "run_tests": False}


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.root = project(self.temp / "jarvis")
        for patcher in (mock.patch("jarvis_setup.steps.install.time.sleep"), mock.patch.object(system, "gather", side_effect=lambda *a, **k: normal_facts())):
            patcher.start()
            self.addCleanup(patcher.stop)


class FullRunTests(Temp):
    def fresh_run(self, answers=None, effects=None, world=None, **kwargs):
        effects = effects or FakeEffects()
        pretend_downloads(effects, self.root)
        world = world or World(packages_missing=["PyQt5", "faster_whisper", "piper"])
        effects.when(lambda c: "install" in c and "-r" in c, lambda c: (world.missing.clear(), RunResult(0, "Successfully installed"))[1])
        ctx, out = make_context(self.root, answers or dict(EVERYTHING), mode="fresh", effects=effects, **kwargs)
        with world:
            code = Runner(ctx).run()
        return code, ctx, effects, out.getvalue()

    def test_a_brand_new_folder_ends_up_set_up_the_way_the_answers_say(self):
        code, ctx, effects, text = self.fresh_run()
        self.assertEqual(code, 0, text)
        values = ctx.env.values()
        self.assertEqual((values["USER_NAME"], values["ADDRESS_AS"], values["DEFAULT_CITY"]), ("Ali", "boss", "Lahore"))
        self.assertTrue(gate._matches_hash("a fresh passphrase", values["JARVIS_PASSWORD_HASH"]))
        self.assertEqual((values["WAKE_WORD"], values["CLAP_WAKE"], values["STT_MODEL"]), ("true", "true", "base.en"))
        found = system.model_facts(self.root, "base.en", "en_GB-alan-medium")
        self.assertTrue(found["piper_ready"] and found["whisper_ready"] and found["wakeword_ready"] and found["speaker_ready"] and found["language_model_ready"])
        self.assertIn("Jarvis is ready", text)
        self.assertIn("Start-Jarvis.bat", text)

    def test_the_steps_run_in_the_documented_order(self):
        _, ctx, _, text = self.fresh_run()
        order = [step.id for step in all_steps() if step.id in ctx.results]
        self.assertEqual(order, ["system", "profile", "runtime", "packages", "models", "voice", "password", "identity", "language_model", "selfcheck"])
        positions = [text.index(f"Step {n} of") for n in range(1, 11)]
        self.assertEqual(positions, sorted(positions))

    def test_the_steps_that_do_not_apply_are_left_out(self):
        _, ctx, _, _ = self.fresh_run()
        for left_out in ("restore", "ollama", "windows"):
            self.assertNotIn(left_out, ctx.results)

    def test_nothing_secret_is_written_in_the_notebook_or_the_log(self):
        log = self.root / "Logs" / "setup.log"
        _, ctx, _, text = self.fresh_run()
        notebook = (self.root / "DataBase" / "setup_state.json").read_text(encoding="utf-8")
        self.assertNotIn("a fresh passphrase", notebook)
        self.assertNotIn("a fresh passphrase", text)
        data = json.loads(notebook)
        self.assertEqual(data["mode"], "fresh")
        self.assertTrue(data["finished"])
        self.assertEqual(data["answers"]["USER_NAME"], "Ali")
        self.assertEqual(data["steps"]["packages"]["state"], "ok")
        self.assertFalse(log.exists())                                                  # (the console in these tests has no log file)

    def test_running_it_again_does_nothing_twice(self):
        self.fresh_run()
        effects = FakeEffects()
        pretend_downloads(effects, self.root)
        ctx, out = make_context(self.root, dict(EVERYTHING), mode="fresh", effects=effects)
        with World():
            code = Runner(ctx).run()
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertGreaterEqual(text.count("Already done"), 6)
        self.assertEqual([c for c in effects.runs if "install" in c or "download" in " ".join(c) or "train_nlu" in " ".join(c)], [])
        self.assertEqual(ctx.env.get("USER_NAME"), "Ali")

    def test_a_step_that_fails_is_recorded_and_the_others_still_run(self):
        effects = FakeEffects()
        effects.when(has("stt.py", "--download"), RunResult(1, "Traceback\nboom"))
        code, ctx, _, text = self.fresh_run(effects=effects)
        self.assertEqual(ctx.results["models"].state, "warn")
        self.assertEqual(ctx.results["password"].state, OK)                              # later steps went on
        self.assertIn("Summary", text)
        self.assertIn("Jarvis should work, but some things need a look", text)

    def test_a_step_that_blows_up_is_a_failed_step_not_a_crashed_wizard(self):
        with mock.patch("jarvis_setup.steps.install.ModelsStep.run", side_effect=RuntimeError("something odd")):
            code, ctx, _, text = self.fresh_run()
        self.assertEqual(ctx.results["models"].state, FAIL)
        self.assertIn("RuntimeError: something odd", text)
        self.assertIn("Logs/setup.log", text)
        self.assertEqual(code, 1)
        self.assertEqual(ctx.results["selfcheck"].state, OK)

    def test_if_the_pc_itself_is_unusable_it_stops_after_the_look_around(self):
        bad = normal_facts()
        bad["python"] = dict(bad["python"], store_stub=True)
        with mock.patch.object(system, "gather", return_value=bad):
            code, ctx, effects, text = self.fresh_run()
        self.assertEqual(code, 1)
        self.assertIn("I cannot go on until that is fixed", text)
        self.assertEqual(list(ctx.results), ["system"])
        self.assertEqual(effects.runs, [])

    def test_only_and_skip_pick_the_steps(self):
        effects = FakeEffects()
        pretend_downloads(effects, self.root)
        ctx, _ = make_context(self.root, dict(EVERYTHING), effects=effects)
        with World():
            Runner(ctx, only=["models"]).run()
        self.assertEqual(sorted(ctx.results), ["models", "system"])
        ctx, _ = make_context(self.root, dict(EVERYTHING), effects=FakeEffects())
        steps = [s.id for s in Runner(ctx, skip=["packages", "selfcheck"]).chosen_steps()]
        self.assertNotIn("packages", steps)
        self.assertNotIn("selfcheck", steps)
        self.assertEqual(steps[0], "system")

    def test_a_step_that_returns_nothing_counts_as_done(self):
        class Quiet(Step):
            id, title, read_only = "quiet", "A quiet step", True

            def run(self, ctx):
                return None
        ctx, _ = make_context(self.root, dict(EVERYTHING))
        runner = Runner(ctx, steps=[all_steps()[0], Quiet()])
        runner.run()
        self.assertEqual(ctx.results["quiet"], Outcome(OK, ""))


class DryRunTests(Temp):
    def test_a_dry_run_describes_everything_and_changes_nothing(self):
        effects = FakeEffects()
        ctx, out = make_context(self.root, dict(EVERYTHING), dry_run=True, effects=effects)
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        with World(packages_missing=["PyQt5"]):
            code = Runner(ctx).run()
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("would: Run:", text)
        self.assertIn("only a preview", text)
        self.assertEqual(effects.runs, [])
        self.assertEqual(effects.fetched, [])

    def test_a_dry_run_says_which_steps_are_already_done(self):
        (self.root / ".env").write_text("USER_NAME=Ali\nJARVIS_PASSWORD_HASH=pbkdf2_sha256$1$ab$cd\n")
        ctx, out = make_context(self.root, dict(EVERYTHING), dry_run=True)
        with World():
            Runner(ctx).run()
        self.assertIn("Already done: all 30 installed - nothing to do", out.getvalue())


class HealthCheckTests(Temp):
    def test_the_check_reports_each_step_and_changes_nothing(self):
        (self.root / ".env").write_text("USER_NAME=Ali\nJARVIS_PASSWORD=plain\n")
        ctx, out = make_context(self.root)
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        with World():
            code = Runner(ctx).check_only()
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")))
        text = out.getvalue()
        self.assertIn("health check (nothing is changed)", text)
        self.assertIn("[WARN] The password - set, but stored as readable text", text)
        self.assertIn("[ OK ] Installing the Python packages", text)
        self.assertEqual(code, 1)                                                         # the models are not there

    def test_a_healthy_install_gets_a_clean_bill(self):
        (self.root / ".env").write_text("USER_NAME=Ali\nJARVIS_PASSWORD_HASH=pbkdf2_sha256$1$ab$cd\n")
        install_models(self.root)
        (self.root / "DataBase" / "FaceDetectionModule" / "trainer").mkdir(parents=True)
        (self.root / "DataBase" / "FaceDetectionModule" / "trainer" / "t.yml").write_text("f")
        (self.root / "DataBase" / "voiceprint.npz").write_text("v")
        effects = FakeEffects()
        effects.json = {"/api/version": {"version": "1"}, "/api/tags": {"models": [{"name": "qwen2.5:1.5b"}]}}
        ctx, out = make_context(self.root, effects=effects)
        with World(ollama_exe="x"):
            code = Runner(ctx).check_only()
        self.assertIn("Everything is in order", out.getvalue())
        self.assertEqual(code, 0)


class ModeAndStyleTests(Temp):
    def test_an_existing_env_means_repair_and_no_env_means_fresh(self):
        ctx, _ = make_context(self.root)
        self.assertEqual(Runner(ctx).guess_mode(), "fresh")
        (self.root / ".env").write_text("USER_NAME=Ali\n")
        self.assertEqual(Runner(ctx).guess_mode(), "repair")

    def test_the_wizard_asks_what_to_do_and_how_much_to_be_asked(self):
        ctx, out = make_context(self.root, {"mode": "restore", "style": "custom"}, mode="auto", express=None)
        Runner(ctx).welcome()
        self.assertEqual((ctx.mode, ctx.express), ("restore", False))

    def test_repair_never_bothers_you_with_the_long_questionnaire(self):
        ctx, _ = make_context(self.root, {"mode": "repair"}, mode="auto", express=None)
        Runner(ctx).welcome()
        self.assertEqual((ctx.mode, ctx.express), ("repair", True))

    def test_yes_means_express(self):
        ctx, _ = make_context(self.root, mode="auto", express=None, assume_yes=True)
        Runner(ctx).welcome()
        self.assertEqual((ctx.mode, ctx.express), ("fresh", True))


class StartOverModeTests(Temp):
    def personal_things(self):
        (self.root / ".env").write_text("USER_NAME=Ali\nJARVIS_PASSWORD=plain\n")
        (self.root / "DataBase" / "Notes").mkdir(parents=True)
        (self.root / "DataBase" / "Notes" / "n.txt").write_text("buy bread")
        (self.root / "DataBase" / "voiceprint.npz").write_text("voice")

    def welcome(self, answers, **kwargs):
        ctx, out = make_context(self.root, answers, mode="auto", express=None, **kwargs)
        Runner(ctx).welcome()
        return ctx, out.getvalue()

    def test_saying_yes_saves_a_checked_copy_clears_everything_and_sets_up_fresh(self):
        self.personal_things()
        (self.root / "DataBase" / "setup_state.json").write_text("{}")
        ctx, text = self.welcome({"mode": "reset", "start_over": True, "style": "express"})
        self.assertEqual(ctx.mode, "fresh")
        self.assertIn("Done: 3 files cleared", text)
        self.assertFalse((self.root / ".env").exists())
        self.assertFalse((self.root / "DataBase" / "voiceprint.npz").exists())
        saved = list((self.root / "Backups").iterdir())
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0] / "files" / "DataBase" / "Notes" / "n.txt").read_text(), "buy bread")
        self.assertEqual(ctx.state.data["steps"], {})                                            # the wizard's notebook starts again too

    def test_saying_no_changes_nothing_and_goes_back_to_the_usual_mode(self):
        self.personal_things()
        ctx, text = self.welcome({"mode": "reset", "start_over": False})
        self.assertEqual(ctx.mode, "repair")
        self.assertIn("Nothing was changed", text)
        self.assertTrue((self.root / ".env").exists())
        self.assertFalse((self.root / "Backups").exists())

    def test_an_unattended_run_never_clears_anything_unless_told_so_by_name(self):
        self.personal_things()
        ctx, _ = self.welcome({"mode": "reset"}, assume_yes=True)
        self.assertTrue((self.root / ".env").exists())
        self.assertEqual(ctx.mode, "repair")

    def test_a_folder_with_nothing_of_yours_is_already_brand_new(self):
        ctx, text = self.welcome({"mode": "reset", "style": "express"})
        self.assertEqual(ctx.mode, "fresh")
        self.assertIn("already brand new", text)

    def test_a_dry_run_only_describes_it(self):
        self.personal_things()
        ctx, text = self.welcome({"mode": "reset", "style": "express"}, dry_run=True)
        self.assertEqual(ctx.mode, "fresh")
        self.assertIn("dry run: nothing was copied or cleared", text)
        self.assertTrue((self.root / ".env").exists())

    def test_a_copy_that_cannot_be_trusted_clears_nothing(self):
        self.personal_things()
        with mock.patch("backup_jarvis.verify_backup", return_value=["missing: .env"]):
            ctx, text = self.welcome({"mode": "reset", "start_over": True})
        self.assertIn("Nothing was cleared", text)
        self.assertTrue((self.root / ".env").exists())
        self.assertEqual(ctx.mode, "repair")

    def test_the_command_line_accepts_the_mode(self):
        self.assertEqual(cli.parse(["--mode", "reset"]).mode, "reset")


class CommandLineTests(Temp):
    def run_cli(self, *argv, answers_file=None):
        effects = FakeEffects()
        pretend_downloads(effects, self.root)
        from tests.setup_support import make_console
        full_argv = ["--project", str(self.root), *argv]
        answers = dict(EVERYTHING)
        answers.update(cli.load_answers(cli.parse(full_argv)))    # honour --set / --answers / --restore-from, as a real run does
        console, out = make_console(answers, assume_yes=True)
        with World():
            code = cli.main(full_argv, console=console, effects=effects)
        return code, out.getvalue(), effects

    def test_it_parses_the_flags(self):
        args = cli.parse(["--check", "--yes", "--custom", "--mode", "restore", "--only", "a,b", "--skip", "c", "--set", "USER_NAME=Ali", "--dry-run", "--force"])
        self.assertTrue(args.check and args.yes and args.custom and args.dry_run and args.force)
        self.assertEqual((args.mode, args.only, args.skip, args.set), ("restore", "a,b", "c", ["USER_NAME=Ali"]))

    def test_answers_come_from_a_file_and_from_set_flags_and_set_wins(self):
        path = self.temp / "answers.json"
        path.write_text(json.dumps({"USER_NAME": "FromFile", "DEFAULT_CITY": "Lahore"}), encoding="utf-8-sig")
        args = cli.parse(["--answers", str(path), "--set", "USER_NAME=FromFlag", "--restore-from", "F:\\Backup"])
        self.assertEqual(cli.load_answers(args), {"USER_NAME": "FromFlag", "DEFAULT_CITY": "Lahore", "restore_from": "F:\\Backup"})

    def test_a_bad_answers_file_or_flag_is_refused_plainly(self):
        path = self.temp / "bad.json"
        path.write_text("[1, 2]")
        with self.assertRaises(SystemExit) as caught:
            cli.load_answers(cli.parse(["--answers", str(path)]))
        self.assertIn("JSON object", str(caught.exception))
        with self.assertRaises(SystemExit) as caught:
            cli.load_answers(cli.parse(["--set", "nonsense"]))
        self.assertIn("KEY=VALUE", str(caught.exception))

    def test_restore_from_implies_restore_mode(self):
        copy = Path(self.temp) / "Backup" / "Jarvis" / "New Jarvis"
        copy.mkdir(parents=True)
        (copy / "config.py").write_text("#")
        (copy / "Startup.py").write_text("#")
        (copy / ".env").write_text("USER_NAME=Restored\n")
        code, text, _ = self.run_cli("--restore-from", str(copy.parent.parent), "--skip", "packages,models,selfcheck,language_model", "--set", "restore_parts=settings")
        self.assertIn("Restored", text)

    def test_list_steps_prints_each_step(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["--list-steps"]), 0)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 13)

    def test_check_dry_run_and_a_normal_run_through_the_command_line(self):
        code, text, _ = self.run_cli("--check")
        self.assertIn("health check", text)
        self.assertFalse((self.root / ".env").exists())
        code, text, effects = self.run_cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertFalse((self.root / ".env").exists())
        code, text, effects = self.run_cli("--skip", "selfcheck")
        self.assertEqual(code, 0, text)
        self.assertTrue((self.root / ".env").exists())

    def test_ctrl_c_ends_it_politely_and_cleanly(self):
        from tests.setup_support import make_console
        console, out = make_console(assume_yes=True)
        with mock.patch.object(Runner, "run", side_effect=KeyboardInterrupt), World():
            code = cli.main(["--project", str(self.root)], console=console, effects=FakeEffects())
        self.assertEqual(code, 130)
        self.assertIn("carries on from here", out.getvalue())


if __name__ == "__main__":
    unittest.main()
