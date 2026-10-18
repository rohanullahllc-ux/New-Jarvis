"""Tests for the access gate:  python -m unittest tests.test_gate -v"""
import io
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy

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

    def test_the_cancel_function_reaches_the_camera_loop(self):
        seen = []
        stop = lambda: False  # noqa: E731
        with mock.patch("DataBase.FaceDetectionModule.FaceRecognition.FaceRocog",
                        side_effect=lambda **kwargs: seen.append(kwargs) or True):
            self.assertTrue(gate.face_check(cancelled=stop))
            self.assertTrue(gate.face_check())
        self.assertEqual(seen, [{"cancelled": stop}, {"cancelled": None}])


class FakeCamera:
    """A webcam that always sees one face."""
    instances = []

    def __init__(self, index, backend):
        self.released, self.reads = False, 0
        FakeCamera.instances.append(self)

    def isOpened(self):
        return True

    def get(self, prop):
        return 640

    def read(self):
        self.reads += 1
        time.sleep(0.005)
        return True, numpy.zeros((100, 100), dtype="uint8")

    def release(self):
        self.released = True


def fake_cv2(distance=30, key=-1, opens=True, faces=True):
    """Just enough of OpenCV for FaceRecognition.FaceRocog."""
    cv2 = types.ModuleType("cv2")
    cv2.CAP_DSHOW, cv2.COLOR_BGR2GRAY, cv2.FONT_HERSHEY_SIMPLEX = 700, 6, 0
    cv2.error = type("error", (Exception,), {})
    recognizer = mock.Mock()
    recognizer.predict.return_value = (1, distance)               # id 1 is "Mr Khan"; a LOWER distance is a better match
    cv2.face = types.SimpleNamespace(LBPHFaceRecognizer_create=lambda: recognizer)
    cv2.CascadeClassifier = lambda path: types.SimpleNamespace(detectMultiScale=lambda *a, **k: [(10, 10, 40, 40)] if faces else [])
    camera = FakeCamera
    if not opens:
        camera = type("ClosedCamera", (FakeCamera,), {"isOpened": lambda self: False})
    cv2.VideoCapture = camera
    cv2.cvtColor = lambda frame, code: frame
    cv2.rectangle = cv2.putText = lambda *a, **k: None
    cv2.imshow = lambda *a: None
    cv2.waitKey = lambda ms: key
    cv2.destroyAllWindows = lambda: None
    return cv2


class CameraLoop(unittest.TestCase):
    """FaceRocog with a stand-in for OpenCV: the loop, the exits and letting go of the webcam."""

    def setUp(self):
        FakeCamera.instances.clear()
        from DataBase.FaceDetectionModule import FaceRecognition
        self.module = FaceRecognition
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and folder.rmdir())
        for name in ("model.yml", "cascade.xml"):
            (folder / name).write_text("x", encoding="utf-8")
        patch = mock.patch.multiple(self.module, MODEL=folder / "model.yml", CASCADE=folder / "cascade.xml")
        patch.start()
        self.addCleanup(patch.stop)
        self.output = io.StringIO()

    def run_check(self, cv2, **kwargs):
        with mock.patch.dict(sys.modules, {"cv2": cv2}), redirect_stdout(self.output):
            return self.module.FaceRocog(**kwargs)

    def test_a_known_face_is_recognised_at_once_and_the_camera_is_released(self):
        started = time.time()
        self.assertTrue(self.run_check(fake_cv2(distance=30), timeout=5))
        self.assertLess(time.time() - started, 1)
        self.assertTrue(FakeCamera.instances[0].released)

    def test_a_stranger_is_not_recognised_and_the_check_ends_by_itself(self):
        self.assertFalse(self.run_check(fake_cv2(distance=90), timeout=0.3))          # 90 is worse than the 70 threshold
        self.assertTrue(FakeCamera.instances[0].released)

    def test_nobody_in_front_of_the_camera(self):
        self.assertFalse(self.run_check(fake_cv2(faces=False), timeout=0.2))

    def test_cancelling_stops_the_check_straight_away_and_releases_the_camera(self):
        cancel = threading.Event()
        threading.Timer(0.15, cancel.set).start()
        started = time.time()
        self.assertFalse(self.run_check(fake_cv2(distance=90), timeout=30, cancelled=cancel.is_set))
        self.assertLess(time.time() - started, 2)
        self.assertTrue(FakeCamera.instances[0].released)

    def test_a_check_that_is_already_cancelled_never_even_reads_a_frame(self):
        self.assertFalse(self.run_check(fake_cv2(distance=90), timeout=30, cancelled=lambda: True))
        self.assertEqual(FakeCamera.instances[0].reads, 0)

    def test_escape_in_the_camera_window_skips_it(self):
        started = time.time()
        self.assertFalse(self.run_check(fake_cv2(distance=90, key=27), timeout=30))
        self.assertLess(time.time() - started, 1)
        self.assertTrue(FakeCamera.instances[0].released)

    def test_a_webcam_that_will_not_open_is_reported_not_crashed(self):
        self.assertFalse(self.run_check(fake_cv2(opens=False), timeout=1))
        self.assertIn("couldn't open the webcam", self.output.getvalue())
        self.assertTrue(FakeCamera.instances[0].released)

    def test_a_missing_opencv_or_face_module_is_reported(self):
        self.assertFalse(self.run_check(None))                          # None in sys.modules means "cannot be imported"
        self.assertIn("OpenCV isn't installed", self.output.getvalue())
        no_face = fake_cv2()
        del no_face.face
        self.assertFalse(self.run_check(no_face))
        self.assertIn("can't recognise faces", self.output.getvalue())

    def test_opencv_5_which_removed_the_face_check_is_explained_with_the_fix(self):
        """OpenCV 5.0 still has cv2.face but it is empty, and it has no CascadeClassifier: the check used to fail with
        "module 'cv2.face' has no attribute 'LBPHFaceRecognizer_create'", which meant nothing to anyone."""
        opencv_5 = fake_cv2()
        opencv_5.__version__ = "5.0.0"
        opencv_5.face = types.SimpleNamespace()
        del opencv_5.CascadeClassifier
        self.assertFalse(self.run_check(opencv_5))
        printed = self.output.getvalue()
        self.assertIn("OpenCV (5.0.0) can't recognise faces", printed)
        self.assertIn('pip install "opencv-contrib-python<5"', printed)
        self.assertEqual(FakeCamera.instances, [])                       # it never touched the camera

    def test_a_missing_model_is_reported(self):
        with mock.patch.object(self.module, "MODEL", Path("no/such/model.yml")):
            self.assertFalse(self.run_check(fake_cv2()))
        self.assertIn("model or cascade file is missing", self.output.getvalue())


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
