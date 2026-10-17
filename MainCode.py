"""One assistant session: greet, then take commands until the user says sleep or quit.

This module has no way in of its own. Startup.py (terminal) and the GUI start it only after gate.py
has let the user in, and it cannot be run directly.
"""
import datetime
import re
import threading
import traceback

import psutil

from config import DEFAULT_CITY, STARTUP_GREETING, USER_NAME
from microphone import listen
from speech import Speak

SLEEP_COMMAND = re.compile(r"(?:you can |go to |take (?:a )?)?(?:sleep|rest)(?: mode)?(?: now)?")
STOP_COMMAND = re.compile(r"(?:quit|exit|terminate|good ?bye|bye)(?: jarvis)?")
RESET_COMMAND = re.compile(r"(?:start (?:a )?)?new conversation|forget everything|(?:clear|reset) (?:your |the )?memory")


class SessionStopped(Exception):
    """Raised by a listen() that the GUI supplies when its Stop button is pressed."""


def Listen():
    return listen()


def ask_user(question):
    """Ask a follow-up question and return the answer (spoken or typed)."""
    Speak(question)
    return Listen()


def handle_command(query, ask=None):
    """Carry out one command. Returns "sleep" or "quit" when the session should end, else None."""
    from JarvisAdvancedBot.JarvisAiBrain import ReplyBrain, ResetBrain, ai_available
    from JarvisAdvancedBot.LocalBrain import LocalReply
    ask = ask or ask_user
    command = query.replace("jarvis", "").strip()

    if len(query) < 3:
        return None
    if STOP_COMMAND.fullmatch(command):
        Speak("Goodbye, sir.")
        return "quit"
    if SLEEP_COMMAND.fullmatch(command):
        Speak("Going to sleep, sir. Say a wake word when you need me.")
        return "sleep"

    if ai_available():
        if RESET_COMMAND.fullmatch(command):
            ResetBrain()
            Speak("Fresh start, sir. I've cleared our conversation.")
        else:
            Speak(ReplyBrain(query))
        return None

    reply = LocalReply(query, ask)
    Speak(reply if reply is not None else "Sorry sir, I don't know how to do that yet. Say 'what can you do' to hear my skills.")
    return None


# ---------------------------------------------------------------- start-up

def _part_of_day(hour):
    return "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 17 else "Good evening"


def greeting(now=None):
    """One sentence: part of the day, the day, the date and the time."""
    now = now or datetime.datetime.now()
    return f"{_part_of_day(now.hour)} {USER_NAME}. It's {now:%A}, {now.day} {now:%B}, {now.strftime('%I:%M %p').lstrip('0')}."


def _timetable_line():
    from JarvisAdvancedBot import tools
    text = tools.get_timetable_block()
    return None if text.startswith("Your time table is empty") else text


def _todo_line():
    from JarvisAdvancedBot import tools
    text = tools.list_tasks()
    return None if "is empty" in text else text


def _battery_line():
    battery = psutil.sensors_battery()
    if battery and not battery.power_plugged and battery.percent < 30:
        return f"Your battery is at {battery.percent:.0f} percent, so you may want to plug in."
    return None


def briefing():
    """The longer start-up report (STARTUP_GREETING=full): weather, today's time table and to-do list, low battery.

    Each item is optional: one that fails (no internet, say) is left out and never stops the session.
    """
    from JarvisAdvancedBot import tools
    lines = []
    for build in (lambda: tools.weather_report(DEFAULT_CITY), _timetable_line, _todo_line, _battery_line):
        try:
            line = build()
        except Exception:
            line = None
        if line:
            lines.append(line)
    return lines


def _prewarm():
    """Load the command brain in the background while the greeting is spoken (importing it takes several seconds)."""
    def load():
        try:
            from JarvisAdvancedBot import LocalBrain  # noqa: F401  (this also imports every tool)
        except Exception:
            pass                                       # the real error will show when a command needs it
    threading.Thread(target=load, daemon=True, name="prewarm").start()


def _announce_brain():
    from JarvisAdvancedBot.JarvisAiBrain import ai_available
    print(": Brain:", "Claude (natural speech)" if ai_available() else "free local commands (no Anthropic API key)")


def taskExe(listen=None, ask=None):
    """Run one session: greet, then handle commands until the user says sleep or quit.

    ``listen`` returns the next command and ``ask`` answers follow-up questions; both default to the
    microphone (or the keyboard in text mode), and the GUI passes its own. Returns "sleep" or "quit" so
    the launcher knows whether to go back to listening for the wake word or to exit.
    """
    listen = listen or Listen
    ask = ask or (lambda question: (Speak(question), listen())[1])
    _prewarm()
    if STARTUP_GREETING != "silent":
        Speak(greeting())
        if STARTUP_GREETING == "full":
            report = briefing()
            if report:
                Speak(" ".join(report))
    _announce_brain()
    if STARTUP_GREETING == "silent":
        print(": Ready.")
    else:
        Speak("Ready for your command, sir.")

    while True:
        try:
            outcome = handle_command(str(listen()), ask)
        except SessionStopped:
            return "quit"
        except Exception:                              # one broken feature shouldn't stop Jarvis
            traceback.print_exc()
            Speak("Sorry sir, something went wrong with that command. The details are in the window.")
            continue
        if outcome in ("sleep", "quit"):
            return outcome
