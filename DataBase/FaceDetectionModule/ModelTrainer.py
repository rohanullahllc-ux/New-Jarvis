"""Teach the face check your face:  python DataBase/FaceDetectionModule/ModelTrainer.py

Reads every photo in the samples folder (named samples.<person>.<number>.jpg, which SampleGenerator.py makes) and learns them.
The result is trainer/trainer.yml, which the face check after the password uses. The model it replaces is kept as
trainer/trainer.previous.yml, in case the new photos turn out worse than the old ones.
"""
import collections
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from config import BASE_DIR  # noqa: E402

FOLDER = BASE_DIR / "DataBase" / "FaceDetectionModule"
SAMPLES = FOLDER / "samples"
CASCADE = FOLDER / "haarcascade_frontalface.xml"
MODEL = FOLDER / "trainer" / "trainer.yml"
NAME = re.compile(r"samples\.(\d+)\.(\d+)\.jpg")


def load_faces(folder=SAMPLES, detector=None):
    """([face picture], [person number], skipped) from the sample photos. The photos are already cut down to the face, so when
    the detector can't find a face inside one, the whole photo is used as long as it is big enough to be a face."""
    import numpy as np
    from PIL import Image
    faces, ids, skipped = [], [], 0
    if not pathlib.Path(folder).is_dir():
        return faces, ids, skipped
    for path in sorted(pathlib.Path(folder).iterdir()):
        found = NAME.fullmatch(path.name)
        if not found:
            continue
        try:
            picture = np.array(Image.open(path).convert("L"), "uint8")
        except OSError:
            skipped += 1
            continue
        boxes = detector.detectMultiScale(picture) if detector is not None else []
        if len(boxes):
            x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
            picture = picture[y:y + h, x:x + w]
        elif min(picture.shape) < 60:
            skipped += 1
            continue
        faces.append(picture)
        ids.append(int(found.group(1)))
    return faces, ids, skipped


def train(folder=SAMPLES, model_file=MODEL):
    """Learn the photos and save the model. Returns how many photos were learned (0 if it could not train)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("OpenCV isn't installed:  pip install \"opencv-contrib-python<5\"")
        return 0
    if not hasattr(getattr(cv2, "face", None), "LBPHFaceRecognizer_create") or not hasattr(cv2, "CascadeClassifier"):
        print(f"This OpenCV ({cv2.__version__}) can't learn faces. Use version 4:  pip install \"opencv-contrib-python<5\"")
        return 0
    print("Learning your face. This takes a few seconds...")
    faces, ids, skipped = load_faces(folder, cv2.CascadeClassifier(str(CASCADE)))
    if not faces:
        print(f"There are no usable photos in {folder}. Run SampleGenerator.py first.")
        return 0
    recognizer = cv2.face.LBPHFaceRecognizer_create()                 # Local Binary Patterns Histograms
    recognizer.train(faces, np.array(ids))
    model_file = pathlib.Path(model_file)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    if model_file.exists():
        shutil.copyfile(model_file, model_file.with_name("trainer.previous.yml"))
    recognizer.write(str(model_file))
    counts = collections.Counter(ids)
    print(f"Learned {len(faces)} photos ({', '.join(f'person {i}: {n}' for i, n in sorted(counts.items()))})"
          + (f"; {skipped} unusable photo(s) skipped." if skipped else "."))
    print("Done. Test it with:  python DataBase/FaceDetectionModule/FaceRecognition.py")
    return len(faces)


if __name__ == "__main__":
    sys.exit(0 if train() else 1)
