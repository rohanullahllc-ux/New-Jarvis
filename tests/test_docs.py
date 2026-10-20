"""Tests that the documents tell the truth:  python -m unittest tests.test_docs -v

* every example the manual shows in its "what you can say" boxes is still understood by Jarvis,
* the settings table in the manual and .env.example are written from the list of settings,
* every file named in the handover documents exists, and every Python file of the project is described in the guide.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MainCode  # noqa: E402
import settings_registry as registry  # noqa: E402
import speaker  # noqa: E402
from gui import admin_panel  # noqa: E402
from tests.isolation import isolated_database, no_personal_lists  # noqa: E402
from tests.test_localbrain import BrainCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANUAL = (ROOT / "MANUAL.md").read_text(encoding="utf-8")
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs" / "PROJECT_GUIDE.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def setUpModule():
    no_personal_lists()
    isolated_database()


def phrases():
    block = MANUAL[MANUAL.index("<!-- say:start -->"):MANUAL.index("<!-- say:end -->")]
    return re.findall(r'"([^"]+)"', block)


class ManualExamplesTests(BrainCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")), mock.patch("subprocess.Popen"), mock.patch("os.startfile", create=True),
                        mock.patch.object(speaker, "_override", [None]), mock.patch.object(speaker, "_last_ok", [0.0])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_boxes_hold_a_good_number_of_examples(self):
        found = phrases()
        self.assertGreater(len(found), 100)
        self.assertEqual(len(found), len(set(found)), "an example is listed twice")

    def test_every_example_in_the_manual_is_understood(self):
        not_understood = [phrase for phrase in phrases() if self.say(phrase) is None]
        self.assertEqual(not_understood, [])

    def test_the_session_words_it_names_are_handled_by_the_session(self):
        for phrase in ("new chat", "sleep", "go to sleep", "quit", "goodbye"):
            command = phrase.lower()
            self.assertTrue(MainCode.RESET_COMMAND.fullmatch(command) or MainCode.SLEEP_COMMAND.fullmatch(command) or MainCode.STOP_COMMAND.fullmatch(command), phrase)
            self.assertIn(f'"{phrase}"', MANUAL)


class GeneratedPartsTests(unittest.TestCase):
    def test_the_settings_table_and_the_example_file_are_up_to_date(self):
        self.assertEqual(registry.check(), [])

    def test_the_manual_has_the_markers_the_generator_needs(self):
        self.assertIn(registry.MANUAL_START, MANUAL)
        self.assertIn(registry.MANUAL_END, MANUAL)

    def test_every_admin_panel_page_is_explained_in_the_manual(self):
        for _, title in admin_panel.PAGES:
            self.assertIn(f"**{title}**", MANUAL, title)


class NamedFilesExistTests(unittest.TestCase):
    RUNTIME = {".env", "Logs/setup.log", "DataBase/setup_state.json", "DataBase/shortcuts.json", "DataBase/contacts.json", "DataBase/voiceprint.npz", "DataBase/memory.json",
               "answers.json", "memory.json", "contacts.json", "shortcuts.json", "setup_state.json", "voiceprint.npz", "nlu.joblib", "models/nlu.joblib", "tests/live_check.py", "DataBase/Notes", "DataBase/Tasks", "DataBase/TimeTable", "Backups"}

    def named(self, text):
        for token in re.findall(r"`([^`\n]+)`", text):
            token = token.strip()
            if re.fullmatch(r"[\w./\\-]+\.(?:bat|cmd|ps1|py|md|json|txt|toml|example)", token) and not token.startswith(("python", ".env.")):
                yield token.replace("\\", "/")

    def test_every_file_the_documents_name_exists(self):
        missing = []
        for label, text in (("MANUAL.md", MANUAL), ("CLAUDE.md", CLAUDE), ("docs/PROJECT_GUIDE.md", GUIDE), ("README.md", README)):
            for token in set(self.named(text)):
                if token in self.RUNTIME or "<" in token or token.endswith(("setup.log",)):
                    continue
                candidates = [ROOT / token, ROOT / "gui" / token, ROOT / "JarvisAdvancedBot" / token, ROOT / "JarvisAdvancedBot" / "tools" / token, ROOT / "jarvis_setup" / token,
                              ROOT / "jarvis_setup" / "steps" / token, ROOT / "training" / token, ROOT / "tests" / token, ROOT / "docs" / token, ROOT / "gui" / "utils" / token,
                              ROOT / "DataBase" / "FaceDetectionModule" / token]
                if not any(path.exists() for path in candidates):
                    missing.append(f"{label}: {token}")
        self.assertEqual(sorted(missing), [])

    def test_every_python_file_of_the_project_is_described_in_the_guide(self):
        skip = {"tests", ".venv", "__pycache__", "dist", "build", ".git", "models", "DataBase"}
        undocumented = []
        for path in sorted(ROOT.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if set(relative.parts[:-1]) & skip and relative.parts[0] != "DataBase" or path.name == "__init__.py":
                continue
            if relative.parts[0] == "DataBase" and "FaceDetectionModule" not in relative.parts:
                continue
            if "__pycache__" in relative.parts or relative.parts[0] == "tests":
                continue
            if path.name not in GUIDE:
                undocumented.append(str(relative))
        self.assertEqual(undocumented, [], "describe new files in docs/PROJECT_GUIDE.md")

    def test_the_handover_file_points_at_the_other_documents(self):
        for name in ("docs/PROJECT_GUIDE.md", "MANUAL.md", "ROADMAP.md", "README.md"):
            self.assertIn(name, CLAUDE)
        self.assertIn("CLAUDE.md", README)
        self.assertIn("MANUAL.md", README)

    def test_the_launchers_are_documented_where_users_look(self):
        for launcher in ("Setup-Jarvis.bat", "Start-Jarvis.bat", "Admin-Panel.bat"):
            self.assertIn(launcher, MANUAL)
            self.assertIn(launcher, README)
            self.assertTrue((ROOT / launcher).exists())


if __name__ == "__main__":
    unittest.main()
