"""One assistant session: greet, then take commands until the user says sleep or quit.

This module has no way in of its own. Startup.py (terminal) and the GUI start it only after gate.py
has let the user in, and it cannot be run directly.
"""
import datetime
import re
import threading
import traceback

import psutil

import transcript
from config import CHAT_PRELOAD, DEFAULT_CITY, INPUT_MODE, STARTUP_GREETING, USER_NAME
from microphone import listen
from speech import Speak, SpeakStream, add_listener, remove_listener

# Questions about the user's own list, schedule or reminders. Only Jarvis's tools know those; a chat model asked about them invents
# them ("Your list for tomorrow includes: wake up, breakfast, lunch...").
PERSONAL_DATA = re.compile(r"(?=.*\b(?:my|today'?s|tomorrow'?s|today|tomorrow|tonight|i have|do i have)\b)"
                           r"(?=.*\b(?:to[- ]?do|todo|tasks?|schedule[ds]?|reminders?|time ?table|appointments?|calendar|list)\b)", re.I)
EDIT_DATA = re.compile(r"(?=.*\b(?:clear|delete|remove|erase|wipe|cross off|tick off|mark)\b)"
                       r"(?=.*\b(?:notes?|tasks?|to[- ]?do|todo|list|reminders?)\b)", re.I)
DELETE_THINGS = re.compile(r"(?=.*\b(?:delete|remove|erase|wipe|uninstall|format)\b)"
                           r"(?=.*\b(?:files?|folders?|documents?|photos?|pictures?|downloads?|apps?|programs?|videos?|songs?|screenshots?|"
                           r"history|cache|drive|disk)\b)", re.I)
SLEEP_COMMAND = re.compile(r"(?:you can )?(?:go to |take (?:a )?)?(?:sleep|rest)(?: mode)?(?: now)?")
GREETING_LEAD = re.compile(r"(?:hello|hi|hey|ok|okay|alright|please)[ ,]+(?=\S)")
STOP_COMMAND = re.compile(r"(?:you can |you may |go ahead and )?(?:(?:quit|exit|terminate|good ?bye|bye)(?: jarvis)?(?: exit)?"
                          r"(?: (?:the |this |your )?(?:program|application|app|jar|jarvis|yourself|assistant)(?: application)?)?"
                          r"|(?:close|stop|end|shut down|turn off)(?: exit)? (?:the |this |your )?(?:program|application|jar|yourself|jarvis application))")
RESET_COMMAND = re.compile(r"(?:start (?:a )?)?(?:new|fresh) (?:chat|conversation)|start over|forget everything|"
                           r"(?:clear|reset|delete|wipe|erase)(?: out)? (?:your |the |this |our |my )?(?:memory|chat|conversation|history)")


class SessionStopped(Exception):
    """Raised by a listen() that the GUI supplies when its Stop button is pressed."""


def Listen():
    return listen()


def ask_user(question):
    """Ask a follow-up question and return the answer (spoken or typed)."""
    Speak(question)
    return Listen()


def _recorded(ask):
    """``ask`` with the user's answers added to the conversation record."""
    def asking(question):
        answer = ask(question)
        transcript.record("you", answer, kind="answer")
        return answer
    return asking


def handle_command(query, ask=None):
    """Carry out one command, or several joined by "then". Returns "sleep" or "quit" when the session should end, else None."""
    from JarvisAdvancedBot.JarvisAiBrain import ai_available
    from JarvisAdvancedBot.LocalBrain import split_commands
    ask = _recorded(ask or ask_user)
    if len(query) < 3:
        return None
    transcript.record("you", query)
    parts = [query] if ai_available() else split_commands(query)       # Claude copes with "do this, then that" by itself
    for part in parts:
        outcome = _handle_one(part, ask)
        if outcome in ("sleep", "quit"):
            return outcome                                             # "...then go to sleep": nothing after that
    return None


def _handle_one(query, ask):
    from JarvisAdvancedBot.JarvisAiBrain import ReplyBrain, ResetBrain, ai_available
    from JarvisAdvancedBot.LocalBrain import LocalReply, normalize
    command = query.lower().replace("jarvis", "").strip()
    polite = normalize(query)                           # "ok can you clear the chat, please" -> "clear the chat"
    polite = GREETING_LEAD.sub("", polite)              # "hello start a new chat" -> "start a new chat"

    if len(query) < 3:
        return None
    transcript.source("command")                        # the paths below change this to say what really answered
    if STOP_COMMAND.fullmatch(command) or STOP_COMMAND.fullmatch(polite):
        Speak("Goodbye, sir.")
        return "quit"
    if SLEEP_COMMAND.fullmatch(command) or SLEEP_COMMAND.fullmatch(polite):
        Speak("Going to sleep, sir. Say a wake word when you need me.")
        return "sleep"

    if ai_available():
        if RESET_COMMAND.fullmatch(polite):
            transcript.source("reset")
            ResetBrain()
            Speak("Fresh start, sir. I've cleared our conversation.")
        else:
            transcript.source("claude")
            Speak(ReplyBrain(query))
        return None

    if RESET_COMMAND.fullmatch(polite):
        from JarvisAdvancedBot import ChatBrain
        transcript.source("reset")
        ChatBrain.forget()
        Speak("Fresh start, sir. I've cleared our conversation.")
        return None

    reply = LocalReply(query, ask)
    if reply is None:
        from JarvisAdvancedBot import ChatBrain
        if ChatBrain.is_fragment(ChatBrain.clean_question(query)):          # "can you", "the square root of": cut off mid-sentence
            transcript.source("fragment")
            Speak("Sorry sir, I only caught part of that. Could you say it again?")
            return None
    if reply is None and EDIT_DATA.match(query):
        transcript.source("fallback")
        Speak("Sorry sir, I couldn't make that out, so I haven't changed anything. Try: clear all notes, clear all tasks, "
              "remove task 2, remove buy bread from my to do list, or delete the last note.")
        return None
    if reply is None and DELETE_THINGS.match(query):
        transcript.source("fallback")
        Speak("Sorry sir, I can't delete files, folders or programs, and I haven't touched anything. That is too risky to do by "
              "voice. I can clear your notes and your to-do list if you like.")
        return None
    if reply is None and PERSONAL_DATA.match(query):
        transcript.source("fallback")
        Speak("Sorry sir, I couldn't make that out as a command about your list or schedule, and I won't guess what is on it. "
              "Try: what's on my to do list, add buy bread to my to do list, or schedule dentist for tomorrow.")
        return None
    if reply is None and _chat(query):
        return None                                    # the chat model has already said its answer, sentence by sentence
    if reply is None:
        transcript.source("fallback")
        reply = _answer_anything(query)
    Speak(reply)
    return None


def _chat(query):
    """Let the AI model on this PC answer, speaking sentence by sentence as its words arrive. False if it can't."""
    from JarvisAdvancedBot import ChatBrain
    if not ChatBrain.available():
        return False
    # A model that has to be loaded first keeps Jarvis silent for 10 to 25 seconds, so that gets a polite word early; one that is
    # already loaded only gets it if the answer is unusually slow, or every single answer would start with it.
    wait = 8.0 if ChatBrain.is_loaded() else 3.0
    transcript.source("chat")
    spoke = SpeakStream(ChatBrain.reply_sentences(query), if_slow="One moment, sir.", after=wait)
    if spoke and ChatBrain.last_timing:
        print(ChatBrain.last_timing)
        transcript.record("system", "timing", kind="timing", **ChatBrain.last_stats)
    return spoke


def _answer_anything(query):
    """Nothing matched a command and the local model couldn't answer: try a cloud key or the web, then admit it, with ideas."""
    from JarvisAdvancedBot import ChatBrain, FreeBrain
    from JarvisAdvancedBot.LocalBrain import suggest
    reply = FreeBrain.answer(query)
    if reply:
        return reply
    ideas = suggest(query)
    hint = (" Did you mean: " + "; or ".join(f"'{idea}'" for idea in ideas) + "?") if ideas else " Say 'what can you do' to hear my skills."
    setup = "" if (FreeBrain.available() or ChatBrain.available()) else (
        " To let me chat about anything, install the free Ollama program, or add a free key as LLM API KEY in the dot env "
        "file; the README explains how.")
    return "Sorry sir, I didn't understand that as a command." + hint + setup


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
        if INPUT_MODE == "voice":
            try:
                import microphone
                microphone.check_windows_volume()      # a muted or very quiet Windows microphone is put right before the first listen
            except Exception:
                pass
        try:
            from JarvisAdvancedBot import LocalBrain, NLU  # noqa: F401  (importing LocalBrain also imports every tool)
            NLU.warm_up()                              # the trained language model, if there is one
        except Exception:
            pass                                       # the real error will show when a command needs it
        if CHAT_PRELOAD:
            from JarvisAdvancedBot import ChatBrain
            ChatBrain.warm_up()                        # never raises
    threading.Thread(target=load, daemon=True, name="prewarm").start()


def _announce_brain():
    """Print which brain this session uses, and return that in a few words for the conversation record."""
    from JarvisAdvancedBot import ChatBrain
    from JarvisAdvancedBot.JarvisAiBrain import ai_available
    if ai_available():
        print(": Brain: Claude (natural speech)")
        return "Claude"
    if ChatBrain.available():
        model = ChatBrain.choose_model()
        print(f": Brain: free local commands, and chat with {model} (Ollama, on this PC)")
        return f"commands + chat with {model}"
    print(": Brain: free local commands (no Anthropic API key, and no chat model running)")
    return "commands only"


def taskExe(listen=None, ask=None):
    """Run one session: greet, then handle commands until the user says sleep or quit.

    ``listen`` returns the next command and ``ask`` answers follow-up questions; both default to the
    microphone (or the keyboard in text mode), and the GUI passes its own. Returns "sleep" or "quit" so
    the launcher knows whether to go back to listening for the wake word or to exit.
    """
    listen = listen or Listen
    ask = ask or (lambda question: (Speak(question), listen())[1])
    add_listener(transcript.on_speech, streaming=True)     # everything Jarvis says goes into the conversation record
    outcome = "error"
    try:
        outcome = _run_session(listen, ask)
        return outcome
    finally:
        remove_listener(transcript.on_speech)
        transcript.end(outcome)


def _run_session(listen, ask):
    _prewarm()
    transcript.begin(_announce_brain())
    if STARTUP_GREETING == "silent":
        print(": Ready.")
    else:
        what_to_say = [greeting()] + (briefing() if STARTUP_GREETING == "full" else []) + ["Ready for your command, sir."]
        Speak(" ".join(what_to_say))               # one utterance: every separate Speak() costs the speech engine a round trip

    while True:
        transcript.source("system")                    # anything said before the next command is not an answer to the last one
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
