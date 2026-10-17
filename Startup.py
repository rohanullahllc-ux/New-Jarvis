import gate
from MainCode import Speak
from microphone import listen

WakeWord1 = "hey jarvis"
WakeWord2 = "wake up"
WakeWord3 = "get up"


def Listen():
    return listen()


def _start_assistant():
    """Hand control to the main assistant loop (voice or typed, per INPUT_MODE)."""
    import MainCode
    MainCode.taskExe()


def Pass(pass_inp):
    """Check the password, then run a best-effort face check. Returns True to grant access."""
    if not gate.check_password(pass_inp):
        Speak("Access Not Granted .")
        return False

    Speak("Access Granted .")
    # The password already granted access; the face check is extra confirmation and must never
    # block entry or crash (no camera, model, or OpenCV is a "skip", not a failure).
    try:
        Speak("For more confirmation I will look at the camera...")
        if gate.face_check():
            Speak("Face confirmed. Welcome back, sir.")
        else:
            Speak("I couldn't confirm your face, but your password was correct, so I'll continue.")
    except Exception as e:
        print(f": Face check skipped ({e})")
    return True


def Wake():
    print("\n: Jarvis is asleep. Say or type a wake word to start: "
          f"'{WakeWord1}', '{WakeWord2}' or '{WakeWord3}'. Type 'quit' to exit.\n")
    while True:
        q = Listen()
        if WakeWord1 in q or WakeWord2 in q or WakeWord3 in q:
            Speak("Jarvis program is password protected...")
            Speak("Kindly provide the correct password to access.")
            try:
                passs = input("Enter the correct password: ")
            except (EOFError, KeyboardInterrupt):
                print("\n: Goodbye, sir.")
                return
            if Pass(passs):
                _start_assistant()
                return

        elif "terminate" in q or "quit" in q or "exit" in q:
            Speak("Ok sir terminating")
            return


if __name__ == "__main__":
    try:
        Wake()
    except KeyboardInterrupt:
        print("\n: Goodbye, sir.")
