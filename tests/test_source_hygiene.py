"""Checks on the source files themselves:  python -m unittest tests.test_source_hygiene -v

A backslash that gets mangled on its way into a file (for example "\\b" in a regular expression turning into an
invisible backspace character) breaks code without any error, so no text file may contain control characters.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "__pycache__", "dist", "build", ".claude"}
TEXT = {".py", ".md", ".txt", ".example", ".toml", ".json", ".gitignore", ".yml"}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def project_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not SKIP & set(path.relative_to(ROOT).parts) and (path.suffix.lower() in TEXT or path.name.startswith(".")):
            yield path


class SourceHygiene(unittest.TestCase):
    def test_no_text_file_contains_control_characters(self):
        problems = []
        for path in project_files():
            if path.name == ".env":
                continue                                    # the user's own settings are not ours to judge
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                problems.append(f"{path.relative_to(ROOT)}: not valid UTF-8")
                continue
            for number, line in enumerate(text.splitlines(), 1):
                found = CONTROL.findall(line)
                if found:
                    problems.append(f"{path.relative_to(ROOT)}:{number}: {sorted({hex(ord(c)) for c in found})} in {line.strip()[:70]!r}")
        self.assertEqual(problems, [])

    def test_every_python_file_compiles(self):
        failures = []
        for path in project_files():
            if path.suffix == ".py":
                try:
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
                except SyntaxError as error:
                    failures.append(f"{path.relative_to(ROOT)}: {error}")
        self.assertEqual(failures, [])

    def test_the_scan_really_sees_the_problem_it_looks_for(self):
        self.assertTrue(CONTROL.search("pattern = r'\x08why\x08'"))
        self.assertFalse(CONTROL.search("pattern = r'\\bwhy\\b'\tand a tab"))


if __name__ == "__main__":
    unittest.main()
