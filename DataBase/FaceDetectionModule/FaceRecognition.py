import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from config import BASE_DIR

MODEL = BASE_DIR / "DataBase" / "FaceDetectionModule" / "trainer" / "trainer.yml"
CASCADE = BASE_DIR / "DataBase" / "FaceDetectionModule" / "haarcascade_frontalface.xml"
NAMES = ["", "Mr Khan"]        # index 0 unused; the trainer labels start at 1
MATCH_THRESHOLD = 70           # LBPH distance: LOWER means a better match; below this = a known face
VERIFY_SECONDS = 8             # stop looking after this long so it never loops forever


def FaceRocog(timeout=VERIFY_SECONDS, cancelled=None):
    """Best-effort webcam face check. Returns True if a known face is seen, else False.

    Never raises: if OpenCV, the trained model or the webcam isn't available it prints
    why and returns False, so the caller can decide what to do instead of crashing.
    ``cancelled`` is an optional function; once it returns True the check stops at once and lets go of the camera.
    """
    try:
        import cv2
    except ImportError:
        print(": OpenCV isn't installed (pip install opencv-contrib-python), so I can't check your face.")
        return False
    if not hasattr(cv2, "face"):
        print(": This OpenCV build lacks the face module (need opencv-contrib-python). Skipping the face check.")
        return False
    if not MODEL.exists() or not CASCADE.exists():
        print(": The face model or cascade file is missing, so I can't check your face.")
        return False

    import time
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(MODEL))
    cascade = cv2.CascadeClassifier(str(CASCADE))

    cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)   # CAP_DSHOW avoids a slow/warning backend on Windows
    if not cam.isOpened():
        print(": I couldn't open the webcam, so I'll skip the face check.")
        cam.release()
        return False

    font = cv2.FONT_HERSHEY_SIMPLEX
    recognized = False
    deadline = time.time() + timeout
    try:
        while time.time() < deadline and not (cancelled and cancelled()):
            ok, frame = cam.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            min_size = (int(0.1 * cam.get(3)), int(0.1 * cam.get(4)))
            for (x, y, w, h) in cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=min_size):
                person_id, distance = recognizer.predict(gray[y:y + h, x:x + w])
                known = distance <= MATCH_THRESHOLD and 0 < person_id < len(NAMES)
                label = NAMES[person_id] if known else "unknown"
                confidence = max(0, round(100 - distance))
                colour = (0, 255, 0) if known else (0, 0, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), colour, 2)
                cv2.putText(frame, f"{label} {confidence}%", (x + 5, y - 5), font, 0.8, (255, 255, 255), 2)
                if known:
                    recognized = True
            try:
                cv2.imshow("Face verification - press ESC to skip", frame)
                key = cv2.waitKey(10) & 0xFF
            except cv2.error:
                break   # no GUI backend for a preview window; stop quietly
            if recognized or key == 27:
                break
    finally:
        cam.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass
    return recognized


if __name__ == "__main__":
    print("Recognized:", FaceRocog())
