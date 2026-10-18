"""Take photos of your face for the face check:  python DataBase/FaceDetectionModule/SampleGenerator.py

    python DataBase/FaceDetectionModule/SampleGenerator.py             30 photos of face number 1 (that is you)
    python DataBase/FaceDetectionModule/SampleGenerator.py --count 50  more photos

Look at the camera and, while it takes the photos, slowly turn your head a little, smile, look up and down. The more different the
photos, the better the check recognises you in daylight, at night, and with glasses on or off. The new photos are ADDED to the
ones already in the samples folder (nothing is overwritten). Press ESC to stop early. Then run ModelTrainer.py.
"""
import argparse
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from config import BASE_DIR  # noqa: E402

FOLDER = BASE_DIR / "DataBase" / "FaceDetectionModule"
SAMPLES = FOLDER / "samples"
CASCADE = FOLDER / "haarcascade_frontalface.xml"
PAUSE = 0.35                    # seconds between photos, so they are not 30 copies of the same moment
GIVE_UP_AFTER = 25              # seconds without seeing a face before it stops


def next_number(face_id, folder=SAMPLES):
    """The number the next photo of this person should have, one after the highest already saved."""
    numbers = [int(found.group(1)) for path in pathlib.Path(folder).glob(f"samples.{face_id}.*.jpg")
               if (found := re.fullmatch(rf"samples\.{face_id}\.(\d+)\.jpg", path.name))]
    return max(numbers, default=0) + 1


def take(count=30, face_id=1, folder=SAMPLES):
    """Save ``count`` photos of the largest face the camera sees. Returns how many were saved."""
    try:
        import cv2
    except ImportError:
        print("OpenCV isn't installed:  pip install \"opencv-contrib-python<5\"")
        return 0
    if not hasattr(cv2, "CascadeClassifier"):
        print(f"This OpenCV ({cv2.__version__}) has no face detector. Use version 4:  pip install \"opencv-contrib-python<5\"")
        return 0
    detector = cv2.CascadeClassifier(str(CASCADE))
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera.release()
        print("I couldn't open the webcam. Close any program that is using it (Zoom, Teams, the browser) and try again.")
        return 0
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    number, saved = next_number(face_id, folder), 0
    last_photo, last_seen = 0.0, time.time()
    print(f"Taking {count} photos. Look at the camera and slowly move your head a little...")
    try:
        while saved < count:
            ok, frame = camera.read()
            if not ok:
                print("The camera stopped giving pictures.")
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5,
                                              minSize=(int(0.15 * gray.shape[1]), int(0.15 * gray.shape[0])))
            if len(faces):
                last_seen = time.time()
                x, y, w, h = max(faces, key=lambda face: face[2] * face[3])
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                if time.time() - last_photo >= PAUSE:
                    cv2.imwrite(str(folder / f"samples.{face_id}.{number}.jpg"), gray[y:y + h, x:x + w])
                    number, saved, last_photo = number + 1, saved + 1, time.time()
            elif time.time() - last_seen > GIVE_UP_AFTER:
                print("I can't see a face. Sit in front of the camera with light on your face and try again.")
                break
            try:
                cv2.putText(frame, f"{saved}/{count}  (ESC to stop)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.imshow("Face photos", frame)
                if cv2.waitKey(30) & 0xFF == 27:
                    break
            except cv2.error:
                time.sleep(0.03)                      # no preview window available: keep going without one
    finally:
        camera.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
    print(f"Saved {saved} photo{'s' if saved != 1 else ''} in {folder}.")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take photos of your face for Jarvis's face check.")
    parser.add_argument("--count", type=int, default=30, help="how many photos to take (default 30)")
    parser.add_argument("--id", type=int, default=1, help="the number of the person; 1 is you (default 1)")
    arguments = parser.parse_args()
    sys.exit(0 if take(arguments.count, arguments.id) else 1)
