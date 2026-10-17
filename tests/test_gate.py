"""Tests for the access gate:  python -m unittest tests.test_gate -v"""
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import gate  # noqa: E402

FAST = 1000   # PBKDF2 iterations for tests; the stored value records its own count, so this is valid


def configured(plain="", hashed=""):
    return mock.patch.multiple(config, JARVIS_PASSWORD=plain, JARVIS_PASSWORD_HASH=hashed)


class PasswordChecks(unittest.TestCase):
    def test_plain_password_must_match_exactly(self):
        with configured(plain="s3cret"):
            self.assertTrue(gate.check_password("s3cret"))
            self.assertTrue(gate.check_password("  s3cret \n"))     # stray whitespace from typing/voice
            self.assertFalse(gate.check_password("S3cret"))
            self.assertFalse(gate.check_password("s3cret!"))
            self.assertFalse(gate.check_password(""))
            self.assertFalse(gate.check_password(None))

    def test_hashed_password_round_trip(self):
        with configured(hashed=gate.hash_password("hunter2", iterations=FAST)):
            self.assertTrue(gate.check_password("hunter2"))
            self.assertFalse(gate.check_password("hunter3"))

    def test_hash_takes_priority_over_a_leftover_plain_password(self):
        with configured(plain="old", hashed=gate.hash_password("new", iterations=FAST)):
            self.assertTrue(gate.check_password("new"))
            self.assertFalse(gate.check_password("old"))

    def test_with_nothing_configured_nobody_gets_in(self):
        with configured():
            self.assertFalse(gate.password_configured())
            for attempt in ("", "python", "password", None):
                self.assertFalse(gate.check_password(attempt))

    def test_a_malformed_stored_hash_never_lets_anyone_in(self):
        for bad in ("garbage", "pbkdf2_sha256$x$y$z", "md5$1$00$00", "pbkdf2_sha256$1000$zz$zz", "$$$"):
            with self.subTest(stored=bad), configured(hashed=bad):
                self.assertFalse(gate.check_password(""))
                self.assertFalse(gate.check_password("anything"))

    def test_hashes_are_salted_and_self_describing(self):
        a, b = gate.hash_password("same", iterations=FAST), gate.hash_password("same", iterations=FAST)
        self.assertNotEqual(a, b)                                    # different salt each time
        self.assertTrue(re.fullmatch(r"pbkdf2_sha256\$1000\$[0-9a-f]{32}\$[0-9a-f]{64}", a))
        self.assertNotIn("same", a)


class StoringAPassword(unittest.TestCase):
    def test_store_writes_a_hash_clears_the_plain_password_and_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("USER_NAME=Mr Khan\nJARVIS_PASSWORD=python\nJARVIS_PASSWORD_HASH=\nDEFAULT_CITY=Lahore\n",
                           encoding="utf-8")
            gate.store_password("brand-new-pass", env_path=env)
            text = env.read_text(encoding="utf-8")
        self.assertIn("USER_NAME=Mr Khan", text)
        self.assertIn("DEFAULT_CITY=Lahore", text)
        self.assertRegex(text, r"(?m)^JARVIS_PASSWORD=$")            # plain password cleared
        self.assertNotIn("brand-new-pass", text)                     # the password itself is never stored
        stored = re.search(r"(?m)^JARVIS_PASSWORD_HASH=(.+)$", text).group(1)
        self.assertTrue(gate._matches_hash("brand-new-pass", stored))
        self.assertFalse(gate._matches_hash("python", stored))

    def test_store_creates_the_lines_when_the_env_file_lacks_them(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("USER_NAME=x\n", encoding="utf-8")
            gate.store_password("abcd", env_path=env)
            self.assertIn("JARVIS_PASSWORD_HASH=pbkdf2_sha256$", env.read_text(encoding="utf-8"))


class FaceCheck(unittest.TestCase):
    def test_face_check_never_raises(self):
        with mock.patch.dict(sys.modules, {"DataBase.FaceDetectionModule.FaceRecognition": None}):
            self.assertFalse(gate.face_check())


class NoPasswordInSourceCode(unittest.TestCase):
    def test_no_launcher_hardcodes_a_password(self):
        for name in ("Startup.py", "MainCode.py", "JarvisGUI.py", "gate.py"):
            path = ROOT / name
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertNotRegex(source, r"""(?i)PASSWORD\s*=\s*["'][^"']+["']""")
                self.assertNotIn('"python"', source)


if __name__ == "__main__":
    unittest.main()
