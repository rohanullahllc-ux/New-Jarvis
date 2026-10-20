"""Tests for the safe .env editor:  python -m unittest tests.test_envfile -v"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import envfile  # noqa: E402
from envfile import EnvFile  # noqa: E402

SAMPLE = """# Jarvis settings
USER_NAME=Mr Khan

# the city
DEFAULT_CITY=Peshawar
# OLLAMA_URL=http://127.0.0.1:11434
RAPIDAPI_KEY=abc
"""


class Folder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".env"

    def env(self, text=SAMPLE):
        if text is not None:
            self.path.write_text(text, encoding="utf-8", newline="")
        return EnvFile(self.path)


class ReadingTests(Folder):
    def test_values_ignore_comments_and_blank_lines_and_the_last_repeat_wins(self):
        env = self.env("# A=1\nA=2\n\nB = 'x y'\nA=3\nexport C=4\n")
        self.assertEqual(env.values(), {"A": "3", "B": "x y", "C": "4"})

    def test_a_missing_file_has_no_settings(self):
        env = self.env(None)
        self.assertEqual(env.values(), {})
        self.assertFalse(env.exists())

    def test_a_byte_order_mark_at_the_start_is_ignored(self):
        self.path.write_bytes(b"\xef\xbb\xbfUSER_NAME=Ali\n")
        self.assertEqual(EnvFile(self.path).get("USER_NAME"), "Ali")

    def test_quotes_and_escapes_are_read(self):
        self.assertEqual(envfile.read_value('"say \\"hi\\"\\nnow"'), 'say "hi"\nnow')
        self.assertEqual(envfile.read_value("'it\\'s'"), "it's")
        self.assertEqual(envfile.read_value("plain   # a comment"), "plain")
        self.assertEqual(envfile.read_value("  spaced  "), "spaced")

    def test_masking_never_shows_a_secret_and_hides_its_length_a_little(self):
        self.assertEqual(envfile.mask(""), "")
        self.assertEqual(envfile.mask("abc"), "******")
        self.assertEqual(envfile.mask("a-long-password-1234", keep=4), "*" * 16 + "1234")
        self.assertNotIn("password", envfile.mask("a-long-password-1234"))


class WritingTests(Folder):
    def test_changing_a_setting_changes_only_its_line(self):
        env = self.env()
        changes = env.set("DEFAULT_CITY", "Lahore")
        self.assertEqual(changes, [("DEFAULT_CITY", "Peshawar", "Lahore")])
        self.assertEqual(self.path.read_text(encoding="utf-8"), SAMPLE.replace("Peshawar", "Lahore"))

    def test_a_new_setting_goes_right_after_its_commented_example(self):
        env = self.env()
        env.set("OLLAMA_URL", "http://10.0.0.5:11434")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        at = lines.index("# OLLAMA_URL=http://127.0.0.1:11434")
        self.assertEqual(lines[at + 1], "OLLAMA_URL=http://10.0.0.5:11434")

    def test_a_setting_with_no_example_is_added_at_the_end_under_a_note(self):
        env = self.env()
        env.set_many({"MIC_VOLUME": "70", "TTS_RATE": "-2"})
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(SAMPLE))
        self.assertIn("# ---- added by the Jarvis setup / admin panel", text)
        self.assertTrue(text.rstrip().endswith("MIC_VOLUME=70\nTTS_RATE=-2"))

    def test_nothing_changes_and_no_backup_is_made_when_the_value_is_the_same(self):
        env = self.env()
        self.assertEqual(env.set("DEFAULT_CITY", "Peshawar"), [])
        self.assertEqual(env.backups(), [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), SAMPLE)

    def test_a_change_first_saves_a_copy_of_the_old_file(self):
        env = self.env()
        env.set("USER_NAME", "Ali")
        saved = env.backups()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(encoding="utf-8"), SAMPLE)

    def test_only_the_ten_newest_copies_are_kept(self):
        env = self.env()
        for number in range(14):
            env.set("USER_NAME", f"name{number}")
        self.assertEqual(len(env.backups()), envfile.KEEP_BACKUPS)

    def test_the_latest_copy_can_be_put_back(self):
        env = self.env()
        env.set("USER_NAME", "Ali")
        self.assertIsNotNone(env.restore_latest_backup())
        self.assertEqual(env.get("USER_NAME"), "Mr Khan")

    def test_with_no_copy_there_is_nothing_to_put_back(self):
        self.assertIsNone(self.env().restore_latest_backup())

    def test_a_failed_write_leaves_the_old_file_untouched_and_no_litter(self):
        env = self.env()
        with mock.patch("envfile.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                env.set("USER_NAME", "Ali")
        self.assertEqual(self.path.read_text(encoding="utf-8"), SAMPLE)
        self.assertEqual([p.name for p in self.path.parent.glob(".env-*.tmp")], [])

    def test_the_file_is_created_when_there_is_none(self):
        env = self.env(None)
        env.set("USER_NAME", "Ali")
        self.assertEqual(env.get("USER_NAME"), "Ali")

    def test_windows_line_endings_are_kept(self):
        env = self.env("A=1\r\nB=2\r\n")
        env.set("A", "9")
        self.assertEqual(self.path.read_bytes(), b"A=9\r\nB=2\r\n")

    def test_remove_deletes_the_line_and_says_whether_there_was_one(self):
        env = self.env()
        self.assertTrue(env.remove("RAPIDAPI_KEY"))
        self.assertFalse(env.remove("RAPIDAPI_KEY"))
        self.assertNotIn("RAPIDAPI_KEY", env.values())

    def test_a_bad_setting_name_or_a_null_character_is_refused(self):
        env = self.env()
        for bad in ({"two words": "x"}, {"1ST": "x"}, {"A=B": "x"}, {"OK": "a\x00b"}):
            with self.assertRaises(ValueError):
                env.set_many(bad)
        self.assertEqual(self.path.read_text(encoding="utf-8"), SAMPLE)

    def test_a_missing_final_newline_does_not_join_lines(self):
        env = self.env("A=1")
        env.set("B", "2")
        self.assertEqual(env.values(), {"A": "1", "B": "2"})


class RoundTripTests(Folder):
    TRICKY = ["plain", "with space inside", " padded ", "has # hash", "has $dollar and ${braces}", "it's quoted", 'say "hi"',
              "back\\slash", "line one\nline two", "", "=starts with equals", "tab\there", "p@ss:w0rd/with?symbols&more=1",
              "both ' and \" quotes", "unicode é中", "pbkdf2_sha256$600000$ab12$cd34"]

    def test_a_scrambled_password_with_dollar_signs_is_written_without_quotes(self):
        env = self.env(None)
        env.set("JARVIS_PASSWORD_HASH", "pbkdf2_sha256$600000$ab12$cd34")
        self.assertIn("JARVIS_PASSWORD_HASH=pbkdf2_sha256$600000$ab12$cd34\n", self.path.read_text(encoding="utf-8"))

    def test_every_value_reads_back_exactly_with_this_module(self):
        env = self.env(None)
        env.set_many({f"K{n}": value for n, value in enumerate(self.TRICKY)})
        for number, value in enumerate(self.TRICKY):
            self.assertEqual(env.get(f"K{number}"), value, repr(value))

    def test_python_dotenv_reads_what_this_module_wrote_just_the_same(self):
        try:
            from dotenv import dotenv_values
        except ImportError:
            self.skipTest("python-dotenv is not installed")
        env = self.env(None)
        env.set_many({f"K{n}": value for n, value in enumerate(self.TRICKY)})
        theirs = dotenv_values(self.path, interpolate=False)
        for number, value in enumerate(self.TRICKY):
            self.assertEqual(theirs.get(f"K{number}"), value, repr(value))

    def test_config_reads_a_dollar_brace_value_literally(self):
        import config
        source = Path(config.__file__).read_text(encoding="utf-8")
        self.assertIn("interpolate=False", source)


class CommandLineTests(unittest.TestCase):
    def test_the_self_check_agrees_with_python_dotenv(self):
        try:
            import dotenv  # noqa: F401
        except ImportError:
            self.skipTest("python-dotenv is not installed")
        self.assertEqual(envfile._check_against_dotenv(), 0)


if __name__ == "__main__":
    unittest.main()
