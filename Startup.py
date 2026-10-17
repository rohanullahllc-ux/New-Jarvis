"""Terminal launcher:  python Startup.py

Wake word -> password -> (optional) camera check -> the assistant session.

This is one of the two supported ways in (the other is JarvisGUI.py). Both go through
gate.py, so nothing here decides who is allowed in, and MainCode.py can no longer be
run on its own to skip the password.

Saying "sleep" ends the session and returns to the wake-word prompt (the password is asked
again next time, like a locked screen). Saying "quit" ends the program.
"""
import getpass
import re
import traceback

import gate
from config import FACE_CHECK, USER_NAME
from microphone import listen
from speech import Speak

WAKE_WORDS = ("hey jarvis", "wake up", "get up")
QUIT_COMMAND = re.compile(r"(?:quit|exit|terminate|good ?bye|bye)(?: jarvis)?")
MAX_ATTEMPTS = 3


def _read_password():
    """Read the password without echoing it (isolated so tests can supply one)."""
    try:
        return getpass.getpass("Enter the password: ")
    except OSError:                       # no real console to hide typing on (e.g. an IDE output pane)
        return input("Enter the password: ")


def authenticate():
    """Up to MAX_ATTEMPTS password tries, then the optional camera check. True if the user may enter."""
    if not gate.password_configured():
        Speak("No unlock password is set. Add JARVIS_PASSWORD to the dot env file, "
              "or run gate dot py with the set password option.")
        return False
    Speak("Jarvis is password protected. Kindly provide the password.")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            entered = _read_password()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if gate.check_password(entered):
            break
        Speak("Access not granted." + (" Try again." if attempt < MAX_ATTEMPTS else ""))
    else:
        return False

    Speak("Access granted.")
    if FACE_CHECK:
        # An extra confirmation, never a requirement: the password already granted access, so a
        # missing camera or model just means "could not confirm".
        Speak("I will take a quick look at the camera for extra confirmation.")
        if gate.face_check():
            Speak(f"Face confirmed. Welcome back, {USER_NAME}.")
        else:
            Speak("I couldn't confirm your face, but your password was correct, so I'll continue.")
    return True


def run():
    print("\n: Jarvis is asleep. Say or type a wake word to start: "
          + ", ".join(f"'{w}'" for w in WAKE_WORDS) + ". Say or type 'quit' to exit.\n")
    while True:
        heard = listen()
        if any(word in heard for word in WAKE_WORDS):
            if not authenticate():
                continue
            import MainCode                      # loaded only once someone has been let in
            try:
                outcome = MainCode.taskExe()
            except Exception:
                traceback.print_exc()            # show the real error rather than hiding it
                Speak("Something went wrong inside that session. Say a wake word to start again.")
                continue
            if outcome == "quit":
                return
            # "sleep": fall through to listening for the wake word again
        elif QUIT_COMMAND.fullmatch(heard.replace("jarvis", "").strip()):
            Speak("Ok sir, shutting down.")
            return


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n: Goodbye, sir.")
