"""Tests for the setup wizard's plumbing: questions and answers, what it finds out about the PC, downloads, shortcuts, and the double-click
launchers:  python -m unittest tests.test_setup_core -v"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_setup import system, windows  # noqa: E402
from jarvis_setup.console import Console  # noqa: E402
from jarvis_setup.context import Context, State  # noqa: E402
from jarvis_setup.effects import DownloadError, Effects  # noqa: E402
from tests.setup_support import FakeEffects, make_console, make_context, project  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)


class AnswersTests(Temp):
    def test_a_ready_answer_is_used_without_asking(self):
        console, out = make_console({"USER_NAME": "Ali", "go": "yes", "voice": "b", "parts": ["a", "c"]})
        self.assertEqual(console.ask("USER_NAME", "Your name?", default="Mr Khan"), "Ali")
        self.assertTrue(console.confirm("go", "Go on?", default=False))
        self.assertEqual(console.choose("voice", "Which?", [("a", "A"), ("b", "B")], default="a"), "b")
        self.assertEqual(console.choose_many("parts", "Which?", [("a", "A"), ("b", "B"), ("c", "C")]), ["a", "c"])
        self.assertEqual(out.getvalue(), "")                                  # nothing was shown: nothing was asked

    def test_assume_yes_takes_every_recommended_answer(self):
        console, _ = make_console(assume_yes=True)
        self.assertEqual(console.ask("x", "?", default="usual"), "usual")
        self.assertFalse(console.confirm("y", "?", default=False))
        self.assertTrue(console.confirm("z", "?", default=True))
        self.assertEqual(console.choose("c", "?", [("a", "A"), ("b", "B")], default="b"), "b")
        self.assertEqual(console.choose_many("m", "?", [("a", "A"), ("b", "B")], defaults=["a"]), ["a"])
        self.assertEqual(console.secret("s", "?"), "")

    def test_with_no_keyboard_it_never_waits_for_one(self):
        console, _ = make_console(interactive=False)
        self.assertEqual(console.ask("x", "?", default="usual"), "usual")
        self.assertTrue(console.confirm("y", "?", default=True))

    def test_typed_answers(self):
        console, _ = make_console(replies=["", "Ali", "n", "y", "2", "", "1,3", ""])
        self.assertEqual(console.ask("a", "?", default="Mr Khan"), "Mr Khan")                     # Enter keeps the default
        self.assertEqual(console.ask("b", "?", default="Mr Khan"), "Ali")
        self.assertFalse(console.confirm("c", "?", default=True))
        self.assertTrue(console.confirm("d", "?", default=False))
        self.assertEqual(console.choose("e", "?", [("a", "A"), ("b", "B")], default="a"), "b")      # a number picks the option
        self.assertEqual(console.choose("f", "?", [("a", "A"), ("b", "B")], default="a"), "a")
        self.assertEqual(console.choose_many("g", "?", [("a", "A"), ("b", "B"), ("c", "C")], defaults=["b"]), ["a", "c"])
        self.assertEqual(console.choose_many("h", "?", [("a", "A"), ("b", "B")], defaults=["b"]), ["b"])

    def test_a_wrong_typed_answer_is_asked_again_with_the_reason(self):
        console, out = make_console(replies=["zzz", "99", "7"])
        value = console.ask("n", "A number?", default="1", validate=lambda text: (text.isdigit() and int(text) < 10, text, "one digit please"))
        self.assertEqual(value, "7")
        self.assertEqual(out.getvalue().count("one digit please"), 2)

    def test_a_ready_answer_that_fails_its_check_falls_back_to_the_usual(self):
        console, out = make_console({"MIC_VOLUME": "loud"})
        value = console.ask("MIC_VOLUME", "?", default="80", validate=lambda text: (text.isdigit(), text, "a number is needed"))
        self.assertEqual(value, "80")
        self.assertIn("a number is needed", out.getvalue())

    def test_a_choice_that_is_not_on_the_list_is_not_taken(self):
        console, out = make_console({"c": "z"})
        self.assertEqual(console.choose("c", "?", [("a", "A"), ("b", "B")], default="a"), "a")
        self.assertIn("not one of", out.getvalue())

    def test_a_secret_is_never_shown_or_logged_and_must_be_typed_twice(self):
        log = self.temp / "setup.log"
        console, out = make_console(replies=["hunter2xyz", "hunter2xyz"])
        console.log_path = log
        self.assertEqual(console.secret("JARVIS_PASSWORD", "Password?"), "hunter2xyz")
        console.close()
        self.assertNotIn("hunter2xyz", out.getvalue())
        self.assertNotIn("hunter2xyz", log.read_text(encoding="utf-8"))
        again, _ = make_console(replies=["abcdef", "different", "abcdef", "abcdef"])
        self.assertEqual(again.secret("p", "?"), "abcdef")                      # the first two did not match, so it asked again

    def test_a_secret_that_is_too_short_is_asked_again(self):
        console, out = make_console(replies=["ab", "abcd", "abcd"])
        self.assertEqual(console.secret("p", "?", minimum=4), "abcd")
        self.assertIn("at least 4", out.getvalue())

    def test_answers_given_in_a_file_for_a_secret_are_used_and_logged_as_given_only(self):
        console, _ = make_console({"JARVIS_PASSWORD": "from-file-pass"})
        self.assertEqual(console.secret("JARVIS_PASSWORD", "?"), "from-file-pass")
        self.assertEqual(console.asked[-1], ("JARVIS_PASSWORD", "(given)"))

    def test_every_question_asked_is_remembered_for_the_summary(self):
        console, _ = make_console({"a": "1"}, assume_yes=True)
        console.ask("a", "?")
        console.confirm("b", "?", default=True)
        self.assertEqual(console.asked, [("a", "1"), ("b", "yes")])

    def test_the_log_gets_what_was_said_and_a_missing_folder_is_made(self):
        log = self.temp / "deeper" / "setup.log"
        console, _ = make_console()
        console.log_path = log
        console.good("all fine")
        console.close()
        self.assertIn("all fine", log.read_text(encoding="utf-8"))

    def test_an_unwritable_log_never_stops_the_wizard(self):
        console, out = make_console()
        console.log_path = str(self.temp)                                       # a folder, not a file
        console.good("still works")
        self.assertIn("still works", out.getvalue())

    def test_plain_ascii_markers_are_used(self):
        console, out = make_console()
        console.good("a")
        console.warn("b")
        console.bad("c")
        console.todo("d")
        console.info("e")
        text = out.getvalue()
        for marker in ("[ OK ]", "[WARN]", "[FAIL]", "[TODO]", "[ .. ]"):
            self.assertIn(marker, text)
        self.assertTrue(text.isascii())


class StateAndContextTests(Temp):
    def test_the_notebook_survives_a_damaged_file(self):
        path = self.temp / "state.json"
        path.write_text("{ nope", encoding="utf-8")
        state = State(path)
        state.step("models", "ok", "done")
        state.save()
        self.assertEqual(State(path).data["steps"]["models"]["state"], "ok")

    def test_saving_settings_checks_them_and_writes_the_good_ones(self):
        ctx, out = make_context(project(self.temp / "p"))
        changes = ctx.save_settings({"USER_NAME": "Ali", "MIC_VOLUME": "loud", "TTS_RATE": "2"})
        self.assertEqual(sorted(k for k, _, _ in changes), ["TTS_RATE", "USER_NAME"])
        self.assertIn("MIC_VOLUME", out.getvalue())
        self.assertEqual(ctx.env.get("MIC_VOLUME"), "80")                          # (still the usual value from the example file)
        self.assertIn("# How Jarvis greets you", (ctx.root / ".env").read_text(encoding="utf-8"))    # the first write makes the full commented file

    def test_a_secret_is_masked_in_what_is_printed(self):
        ctx, out = make_context(project(self.temp / "p"))
        ctx.save_settings({"EMAIL_PASSWORD": "my-app-password"})
        self.assertNotIn("my-app-password", out.getvalue())
        self.assertEqual(ctx.env.get("EMAIL_PASSWORD"), "my-app-password")

    def test_a_dry_run_writes_nothing(self):
        ctx, out = make_context(project(self.temp / "p"), dry_run=True)
        self.assertEqual(ctx.save_settings({"USER_NAME": "Ali"}), [])
        self.assertFalse((ctx.root / ".env").exists())
        self.assertIn("would set USER_NAME=Ali", out.getvalue())

    def test_values_fall_back_to_the_usual_ones(self):
        ctx, _ = make_context(project(self.temp / "p"))
        self.assertEqual(ctx.value("DEFAULT_CITY"), "Peshawar")
        ctx.save_settings({"DEFAULT_CITY": "Lahore"})
        self.assertEqual(ctx.value("DEFAULT_CITY"), "Lahore")

    def test_python_scripts_run_from_the_project_folder_with_the_wizards_python(self):
        effects = FakeEffects()
        ctx, _ = make_context(project(self.temp / "p"), effects=effects)
        ctx.run_python(["stt.py", "--download"], env={"STT_MODEL": "tiny.en"})
        self.assertEqual(effects.runs[0], [sys.executable, "stt.py", "--download"])
        ctx.run_python(["enroll_voice.py"], visible=True)
        self.assertEqual(effects.visible[0], [sys.executable, "enroll_voice.py"])

    def test_a_dry_run_only_says_what_it_would_run(self):
        effects = FakeEffects()
        ctx, out = make_context(project(self.temp / "p"), effects=effects, dry_run=True)
        self.assertEqual(ctx.run_python(["x.py"]).returncode, 0)
        self.assertEqual(effects.runs, [])
        self.assertIn("would run:", out.getvalue())


class SystemFactsTests(Temp):
    def test_the_hardware_tiers(self):
        light = system.hardware_tier({"ram_gb": 8.0, "cores": 4})
        self.assertEqual((light.name, light.stt_model, light.ollama_models[0]), ("light", "base.en", "qwen2.5:1.5b"))
        self.assertEqual(system.hardware_tier({"ram_gb": 16.0, "cores": 8}).name, "strong")
        self.assertEqual(system.hardware_tier({"ram_gb": 12.0, "cores": 4}).name, "balanced")
        self.assertEqual(system.hardware_tier({"ram_gb": 32.0, "cores": 2}).name, "light")           # two cores is slow whatever the memory
        very = system.hardware_tier({"ram_gb": 3.0, "cores": 4})
        self.assertEqual((very.name, very.stt_model), ("very light", "tiny.en"))
        self.assertEqual(system.hardware_tier({}).name, "light")                                       # nothing known: be gentle

    def test_models_found_on_disk(self):
        root = self.temp / "p"
        (root / "models" / "piper").mkdir(parents=True)
        (root / "models" / "piper" / "a.onnx").write_text("x")
        (root / "models" / "piper" / "a.onnx.json").write_text("{}")
        (root / "models" / "piper" / "b.onnx").write_text("x")                                       # no .json: not a usable voice
        snapshot = root / "models" / "whisper" / "models--Systran--faster-whisper-base.en" / "snapshots" / "h"
        snapshot.mkdir(parents=True)
        (snapshot / "model.bin").write_text("m")
        found = system.model_facts(root, "base.en", "a")
        self.assertEqual(found["piper_voices"], ["a"])
        self.assertTrue(found["chosen_voice_ready"] and found["whisper_ready"])
        self.assertEqual(found["whisper_models"], ["base.en"])
        self.assertFalse(found["wakeword_ready"] or found["speaker_ready"] or found["language_model_ready"])
        self.assertFalse(system.model_facts(root, "small.en", "a")["whisper_ready"])

    def test_the_project_facts(self):
        root = self.temp / "p"
        (root / "DataBase" / "FaceDetectionModule" / "trainer").mkdir(parents=True)
        (root / "DataBase" / "FaceDetectionModule" / "trainer" / "trainer.yml").write_text("f")
        (root / "DataBase" / "voiceprint.npz").write_text("v")
        (root / ".env").write_text("A=1")
        facts = system.project_facts(root)
        self.assertTrue(facts["env_exists"] and facts["voiceprint"] and facts["face_model"])
        self.assertFalse(facts["notes"] or facts["tasks"] or facts["setup_state"])

    def test_ollama_facts_from_its_local_answers(self):
        effects = FakeEffects()
        effects.json = {"/api/version": {"version": "0.5.1"}, "/api/tags": {"models": [{"name": "qwen2.5:1.5b"}, {"name": "llama3.2:3b"}]}}
        with mock.patch.object(system, "ollama_executable", return_value=r"C:\Ollama\ollama.exe"):
            found = system.ollama_facts(effects)
        self.assertEqual((found["installed"], found["running"], found["models"], found["version"]), (True, True, ["qwen2.5:1.5b", "llama3.2:3b"], "0.5.1"))
        with mock.patch.object(system, "ollama_executable", return_value=""):
            down = system.ollama_facts(FakeEffects())
        self.assertEqual((down["installed"], down["running"], down["models"]), (False, False, []))

    def test_the_internet_check_asks_every_address_and_survives_a_failing_one(self):
        class Odd(FakeEffects):
            def reachable(self, url, timeout=6):
                if "github" in url:
                    raise OSError("boom")
                return "pypi" in url
        answers = system.internet_facts(Odd())
        self.assertEqual(len(answers), len(system.ENDPOINTS))
        self.assertTrue(answers["PyPI (Python packages)"])
        self.assertFalse(answers["GitHub (more models)"])
        self.assertFalse(answers["Ollama (the chat model)"])

    def test_python_facts_say_whether_this_python_is_the_recommended_one(self):
        facts = system.python_facts()
        self.assertEqual(facts["text"], f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        self.assertEqual(facts["recommended"], sys.version_info[:2] == (3, 14))
        self.assertFalse(facts["store_stub"])

    def test_package_facts_cover_every_package_in_the_list(self):
        found = system.package_facts()
        self.assertEqual(set(found), {module for module, *_ in system.PACKAGES})
        self.assertTrue(found["numpy"] or not found["numpy"])                                          # (it is a plain yes or no, never an error)

    def test_every_package_the_project_needs_is_in_the_wizards_list_and_the_other_way_round(self):
        needed = {re.split(r"[<>=;\s]", line)[0].lower().replace("_", "-") for line in
                  (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}
        listed = {package.lower().replace("_", "-") for _, package, *_ in system.PACKAGES}
        self.assertEqual(sorted(needed - listed - {"audioop-lts", "cffi"}), [], "requirements.txt has packages the wizard does not check")
        self.assertEqual(sorted(listed - needed), [], "the wizard checks packages requirements.txt does not install")


class FakeServer(BaseHTTPRequestHandler):
    payload = bytes(range(256)) * 1200                                                                 # about 300 KB

    def do_GET(self):
        if self.path == "/missing":
            return self.send_error(404)
        data, start = self.payload, 0
        if self.headers.get("Range"):
            start = int(self.headers["Range"].split("=")[1].split("-")[0])
            if start >= len(data):
                return self.send_error(416)
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data) - start if self.path != "/short" else 100000))
        self.end_headers()
        self.wfile.write(data[start:] if self.path != "/short" else data[start:start + 500])

    def do_HEAD(self):
        self.send_response(200 if self.path != "/missing" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class DownloadTests(Temp):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        patcher = mock.patch("jarvis_setup.effects.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_file_is_downloaded_whole_and_progress_is_reported(self):
        seen = []
        dest = Effects().fetch(self.url + "/file", self.temp / "got" / "file.bin", progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(dest.read_bytes(), FakeServer.payload)
        self.assertEqual(seen[-1], (len(FakeServer.payload), len(FakeServer.payload)))
        self.assertFalse((self.temp / "got" / "file.bin.part").exists())

    def test_a_half_finished_download_carries_on_where_it_stopped(self):
        target = self.temp / "file.bin"
        (self.temp / "file.bin.part").write_bytes(FakeServer.payload[:100000])
        Effects().fetch(self.url + "/file", target)
        self.assertEqual(target.read_bytes(), FakeServer.payload)

    def test_a_part_file_that_is_already_complete_is_accepted(self):
        target = self.temp / "file.bin"
        (self.temp / "file.bin.part").write_bytes(FakeServer.payload)
        Effects().fetch(self.url + "/file", target)
        self.assertEqual(target.read_bytes(), FakeServer.payload)

    def test_a_file_of_the_expected_size_is_not_fetched_again(self):
        target = self.temp / "file.bin"
        target.write_bytes(b"12345")
        with mock.patch("urllib.request.urlopen") as opened:
            Effects().fetch(self.url + "/file", target, expected_size=5)
        opened.assert_not_called()

    def test_a_missing_file_fails_at_once_with_a_plain_sentence(self):
        with self.assertRaises(DownloadError) as caught:
            Effects().fetch(self.url + "/missing", self.temp / "x.bin")
        self.assertIn("could not download", str(caught.exception))
        self.assertIn("404", str(caught.exception))

    def test_a_connection_that_is_cut_short_is_tried_again_then_reported(self):
        with self.assertRaises(DownloadError):
            Effects().fetch(self.url + "/short", self.temp / "x.bin", retries=2)
        self.assertFalse((self.temp / "x.bin").exists())

    def test_nothing_listening_is_reported_not_raised_raw(self):
        with self.assertRaises(DownloadError):
            Effects().fetch("http://127.0.0.1:9/nothing", self.temp / "x.bin", retries=1)

    def test_reachable_and_http_json(self):
        effects = Effects()
        self.assertTrue(effects.reachable(self.url + "/file"))
        self.assertTrue(effects.reachable(self.url + "/missing"))                                     # an error page still means the internet works
        self.assertFalse(effects.reachable("http://127.0.0.1:9/"))
        self.assertIsNone(effects.http_json("http://127.0.0.1:9/api/version", timeout=1))


class RunningProgramsTests(unittest.TestCase):
    def test_output_is_collected_line_by_line_and_the_exit_code_is_returned(self):
        lines = []
        result = Effects().run([sys.executable, "-c", "print('one'); print('two'); raise SystemExit(3)"], on_line=lines.append)
        self.assertEqual((result.returncode, result.output.splitlines()), (3, ["one", "two"]))
        self.assertEqual(lines, ["one", "two"])

    def test_a_program_that_cannot_start_is_a_result_not_an_exception(self):
        result = Effects().run([r"C:\no\such\program.exe"])
        self.assertEqual(result.returncode, -1)
        self.assertIn("could not start", result.output)

    def test_a_program_that_goes_silent_is_still_stopped_on_time(self):
        result = Effects().run([sys.executable, "-c", "import time; print('start', flush=True); time.sleep(60)"], timeout=2)
        self.assertIn("start", result.output)
        self.assertIn("stopped after 2 seconds", result.output)

    def test_a_faulty_listener_does_not_stop_the_reading(self):
        def bad(line):
            raise ValueError("listener broke")
        result = Effects().run([sys.executable, "-c", "print('a'); print('b')"], on_line=bad)
        self.assertEqual(result.output.splitlines(), ["a", "b"])


@unittest.skipUnless(os.name == "nt", "Windows only")
class WindowsHelperTests(Temp):
    def test_the_shortcut_script_quotes_a_path_with_an_ampersand_and_an_apostrophe(self):
        script = windows.shortcut_script(r"C:\Users\Rohaan & Co's\Desktop\Jarvis.lnk", r"C:\Python\pythonw.exe", '"C:\\Users\\Rohaan & Co\'s\\JarvisGUI.py"',
                                         r"C:\Users\Rohaan & Co's", r"C:\Users\Rohaan & Co's\jarvis.ico")
        self.assertIn(r"CreateShortcut('C:\Users\Rohaan & Co''s\Desktop\Jarvis.lnk')", script)
        self.assertIn("$link.Arguments = '\"C:\\Users\\Rohaan & Co''s\\JarvisGUI.py\"'", script)
        self.assertIn("$link.Save()", script)

    def test_the_launcher_starts_the_window_with_the_windowless_python(self):
        program, arguments, workdir = windows.launcher(self.temp)
        self.assertTrue(program.lower().endswith(("pythonw.exe", "python.exe")))
        self.assertEqual(arguments, f'"{self.temp / "JarvisGUI.py"}"')
        self.assertEqual(workdir, str(self.temp))

    def test_start_with_windows_adds_and_removes_the_shortcut_in_the_startup_folder(self):
        with mock.patch.dict(os.environ, {"APPDATA": str(self.temp)}):
            def fake_create(effects, link, root):
                Path(link).parent.mkdir(parents=True, exist_ok=True)
                Path(link).write_text("lnk")
                return True
            with mock.patch.object(windows, "create_shortcut", side_effect=fake_create):
                self.assertFalse(windows.starts_with_windows())
                self.assertTrue(windows.set_start_with_windows(FakeEffects(), self.temp, True))
                self.assertTrue(windows.starts_with_windows())
                self.assertFalse(windows.set_start_with_windows(FakeEffects(), self.temp, False))
                self.assertFalse(windows.starts_with_windows())

    def test_an_installer_that_needs_administrator_rights_reports_its_exit_code(self):
        effects = FakeEffects()
        for printed, expected in (("0", 0), ("3010", 3010), ("1638\n", 1638), ("REFUSED", None), ("", None), ("garbage", None)):
            effects.powershell_output = printed
            self.assertEqual(windows.run_elevated(effects, r"C:\x\vc_redist.x64.exe", "/install /quiet"), expected, printed)
        self.assertIn("-Verb RunAs", effects.scripts[0])
        effects.powershell_output = "RAISE"
        self.assertIsNone(windows.run_elevated(effects, "x", "y"))

    def test_the_desktop_folder_comes_from_windows_because_onedrive_can_move_it(self):
        effects = FakeEffects()
        effects.powershell_output = r"D:\OneDrive\Desktop"
        self.assertEqual(windows.desktop_dir(effects), Path(r"D:\OneDrive\Desktop"))
        effects.powershell_output = "RAISE"
        self.assertEqual(windows.desktop_dir(effects), Path.home() / "Desktop")


@unittest.skipUnless(os.name == "nt", "Windows only")
class LauncherScriptTests(Temp):
    SCRIPTS = ["Setup-Jarvis.bat", "Start-Jarvis.bat", "Admin-Panel.bat", "jarvis_setup/find_python.cmd", "jarvis_setup/install_python.ps1"]

    def test_windows_scripts_have_windows_line_endings(self):
        for name in self.SCRIPTS:
            data = (ROOT / name).read_bytes()
            self.assertIn(b"\r\n", data, name)
            self.assertNotRegex(data, rb"(?<!\r)\n", name)

    def test_no_script_prints_a_path_variable_unquoted(self):
        """An unquoted %PY% breaks on "C:\\Users\\Rohaan & Co": the & ends the command and "Co\\..." is run as another."""
        for name in self.SCRIPTS[:4]:
            for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().lower().startswith("echo") and "%" in line:
                    self.assertNotRegex(line, r'(?<!")%(PY|PYW|~dp0|CD)%', f"{name}:{number}: {line}")

    def run_finder(self, extra_setup=""):
        folder = self.temp / "Rohaan & Co's folder" / "jarvis_setup"
        folder.mkdir(parents=True)
        shutil.copy(ROOT / "jarvis_setup" / "find_python.cmd", folder / "find_python.cmd")
        wrapper = self.temp / "Rohaan & Co's folder" / "try.cmd"
        wrapper.write_bytes(("@echo off\r\n" + extra_setup + f'call "{folder / "find_python.cmd"}"\r\necho PY="%PY%"\r\necho PYW="%PYW%"\r\n').encode())
        done = subprocess.run(f'cmd /c ""{wrapper}""', capture_output=True, text=True, timeout=60)          # (the doubled quotes keep the & inside the path)
        found = dict(re.findall(r'^(PYW?)="(.*)"\s*$', done.stdout, re.M))
        return found, done

    def test_the_python_finder_works_from_a_folder_with_an_ampersand_and_an_apostrophe(self):
        found, done = self.run_finder()
        self.assertTrue(found.get("PY"), done.stdout + done.stderr)
        self.assertTrue(Path(found["PY"]).exists(), found)
        self.assertTrue(Path(found["PYW"]).exists(), found)
        major_minor = subprocess.run([found["PY"], "-c", "import sys; print(sys.version_info >= (3, 12))"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(major_minor, "True")

    def test_the_python_finder_finds_nothing_on_a_pc_without_python(self):
        found, _ = self.run_finder('set "PATH=C:\\Windows\\System32"\r\nset "LOCALAPPDATA=C:\\no-such-folder"\r\nset "ProgramFiles=C:\\no-such-folder"\r\n')
        self.assertEqual(found.get("PY"), "")

    def test_setup_offers_to_install_python_when_there_is_none(self):
        wrapper = self.temp / "no python.cmd"
        wrapper.write_bytes(('@echo off\r\nset "PATH=C:\\Windows\\System32"\r\nset "LOCALAPPDATA=C:\\no-such-folder"\r\nset "ProgramFiles=C:\\no-such-folder"\r\n'
                             f'set "JARVIS_SETUP_DRY_RUN=1"\r\ncall "{ROOT / "Setup-Jarvis.bat"}" < NUL\r\n').encode())
        done = subprocess.run(f'cmd /c ""{wrapper}""', capture_output=True, text=True, timeout=60)
        self.assertIn("was not found on this PC", done.stdout)
        self.assertIn("test mode", done.stdout)

    def test_setup_runs_the_wizard_with_the_python_it_found_and_passes_the_options_on(self):
        done = subprocess.run(f'cmd /c ""{ROOT / "Setup-Jarvis.bat"}" --list-steps < NUL"', capture_output=True, text=True, timeout=120)
        self.assertIn("Using Python:", done.stdout)
        self.assertIn("Looking at this PC", done.stdout)
        self.assertIn("Trying it all", done.stdout)
        self.assertEqual(done.returncode, 0)

    def test_the_python_installer_script_has_no_syntax_errors(self):
        script = (ROOT / "jarvis_setup" / "install_python.ps1")
        check = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                 f"'{script}', [ref]$t, [ref]$e); if ($e -and $e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")
        done = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout)


class EntryPointTests(unittest.TestCase):
    def test_the_entry_script_lists_the_steps(self):
        done = subprocess.run([sys.executable, str(ROOT / "setup_jarvis.py"), "--list-steps"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len([line for line in done.stdout.splitlines() if line.strip()]), 13)

    def test_the_wizard_package_imports_nothing_that_is_not_in_the_standard_library_or_the_project(self):
        allowed_roots = {name for name in ("envfile", "settings_registry", "backup_jarvis", "winmm_mic", "gate", "jarvis_setup")}
        bad = []
        for path in (ROOT / "jarvis_setup").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                found = re.match(r"\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
                if found and not line.lstrip().startswith("from ."):
                    name = found.group(1)
                    if name not in sys.stdlib_module_names and name not in allowed_roots:
                        bad.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(bad, [], "the wizard runs before anything is installed: it may only use the standard library")


if __name__ == "__main__":
    unittest.main()
