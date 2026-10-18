"""Tests for the face photo scripts:  python -m unittest tests.test_face_tools -v

No webcam is opened and nothing is written to the real samples or trainer folders: both scripts are pointed at temporary ones.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from DataBase.FaceDetectionModule import ModelTrainer, SampleGenerator  # noqa: E402


def picture(path, size=80, value=120):
    Image.fromarray(np.full((size, size), value, dtype="uint8")).save(path)


class NumberingTests(unittest.TestCase):
    def test_new_photos_are_numbered_after_the_highest_one_already_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("samples.1.1.jpg", "samples.1.10.jpg", "samples.1.2.jpg", "samples.2.5.jpg", "notes.txt", "samples.1.x.jpg"):
                (Path(folder) / name).write_bytes(b"x")
            self.assertEqual(SampleGenerator.next_number(1, folder), 11)         # 10 is higher than 9, 2: numbers, not text
            self.assertEqual(SampleGenerator.next_number(2, folder), 6)
            self.assertEqual(SampleGenerator.next_number(3, folder), 1)
        self.assertEqual(SampleGenerator.next_number(1, Path("no such folder")), 1)

    def test_taking_photos_without_opencv_or_a_camera_saves_nothing_and_says_why(self):
        out = io.StringIO()
        broken = SimpleNamespace(CascadeClassifier=lambda path: object(), CAP_DSHOW=700, __version__="4.14",
                                 VideoCapture=lambda *a: SimpleNamespace(isOpened=lambda: False, release=lambda: None))
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {"cv2": broken}), redirect_stdout(out):
            self.assertEqual(SampleGenerator.take(5, 1, folder), 0)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertIn("couldn't open the webcam", out.getvalue())
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"cv2": SimpleNamespace(__version__="5.0")}), redirect_stdout(out):
            self.assertEqual(SampleGenerator.take(5), 0)
        self.assertIn("no face detector", out.getvalue())


class TrainerTests(unittest.TestCase):
    def test_every_photo_of_a_face_is_loaded_with_the_number_of_its_person(self):
        with tempfile.TemporaryDirectory() as folder:
            picture(Path(folder) / "samples.1.1.jpg")
            picture(Path(folder) / "samples.1.2.jpg")
            picture(Path(folder) / "samples.3.1.jpg")
            picture(Path(folder) / "samples.1.3.jpg", size=30)                  # too small to be a face
            (Path(folder) / "samples.1.4.jpg").write_bytes(b"not a picture")
            (Path(folder) / "readme.txt").write_text("not a sample", encoding="utf-8")
            faces, ids, skipped = ModelTrainer.load_faces(folder, detector=None)
        self.assertEqual(sorted(ids), [1, 1, 3])
        self.assertEqual(len(faces), 3)
        self.assertEqual(skipped, 2)

    def test_when_the_detector_finds_a_face_inside_the_photo_only_that_part_is_used(self):
        detector = SimpleNamespace(detectMultiScale=lambda picture: [(10, 10, 40, 40), (0, 0, 20, 20)])
        with tempfile.TemporaryDirectory() as folder:
            picture(Path(folder) / "samples.1.1.jpg", size=100)
            faces, ids, skipped = ModelTrainer.load_faces(folder, detector)
        self.assertEqual((faces[0].shape, ids, skipped), ((40, 40), [1], 0))        # the largest box

    def test_training_without_a_face_recogniser_says_how_to_fix_it(self):
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"cv2": SimpleNamespace(__version__="5.0", face=SimpleNamespace())}), redirect_stdout(out):
            self.assertEqual(ModelTrainer.train(), 0)
        self.assertIn("opencv-contrib-python<5", out.getvalue())

    def test_training_with_no_photos_says_to_take_some_first_and_keeps_the_old_model(self):
        recognizer = SimpleNamespace(train=mock.Mock(), write=mock.Mock())
        fake = SimpleNamespace(__version__="4.14", CascadeClassifier=lambda path: object(),
                               face=SimpleNamespace(LBPHFaceRecognizer_create=lambda: recognizer))
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {"cv2": fake}), redirect_stdout(out):
            self.assertEqual(ModelTrainer.train(Path(folder) / "samples", Path(folder) / "trainer" / "trainer.yml"), 0)
        self.assertIn("SampleGenerator.py", out.getvalue())
        recognizer.write.assert_not_called()

    def test_training_keeps_the_model_it_replaces(self):
        recognizer = SimpleNamespace(train=mock.Mock(), write=lambda path: Path(path).write_text("new model", encoding="utf-8"))
        fake = SimpleNamespace(__version__="4.14", CascadeClassifier=lambda path: SimpleNamespace(detectMultiScale=lambda picture: []),
                               face=SimpleNamespace(LBPHFaceRecognizer_create=lambda: recognizer))
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {"cv2": fake}), redirect_stdout(out):
            samples, model = Path(folder) / "samples", Path(folder) / "trainer" / "trainer.yml"
            samples.mkdir()
            model.parent.mkdir()
            model.write_text("old model", encoding="utf-8")
            picture(samples / "samples.1.1.jpg")
            picture(samples / "samples.1.2.jpg")
            self.assertEqual(ModelTrainer.train(samples, model), 2)
            self.assertEqual(model.read_text(encoding="utf-8"), "new model")
            self.assertEqual(model.with_name("trainer.previous.yml").read_text(encoding="utf-8"), "old model")
        recognizer.train.assert_called_once()
        self.assertIn("Learned 2 photos (person 1: 2)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
