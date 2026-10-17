"""Runs the assistant session on a background thread and turns what happens into Qt signals.

The window never calls into the assistant itself: it submits commands here and reacts to signals, so
it stays responsive while Jarvis is thinking, speaking or listening. The session thread is a daemon,
so closing the window can never be held up by a microphone or a network call that is stuck.
"""
import io
import queue
import sys
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout

from PyQt5.QtCore import QObject, pyqtSignal

import speech

_STOP = object()
LISTEN_TIMEOUT = 4            # hands-free: seconds to wait for speech to begin before checking for typed commands
PHRASE_LIMIT = 10             # seconds of speech taken as one command


class _Tee(io.TextIOBase):
    """Passes everything printed during a session on to the window's log, and to the real console if there is one."""

    def __init__(self, emit, original):
        self._emit, self._original, self._partial = emit, original, ""

    def writable(self):
        return True

    def write(self, text):
        if self._original:
            try:
                self._original.write(text)
            except Exception:
                pass
        *lines, self._partial = (self._partial + text).split("\n")
        for line in lines:
            if line.strip():
                self._emit(line.rstrip())
        return len(text)

    def flush(self):
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass


def _default_run(listen, ask):
    import MainCode                               # imported here, on the session thread: it takes a few seconds
    return MainCode.taskExe(listen=listen, ask=ask)


def _default_listen_voice(timeout, phrase_time_limit):
    from microphone import listen_voice
    return listen_voice(timeout=timeout, phrase_time_limit=phrase_time_limit)


class SessionController(QObject):
    state_changed = pyqtSignal(str)       # locked | starting | ready | listening | working
    said = pyqtSignal(str)                # something Jarvis said
    heard = pyqtSignal(str)               # a command from the user, typed or spoken
    log = pyqtSignal(str)                 # a line of console output
    problem = pyqtSignal(str)             # something the user should be told
    ended = pyqtSignal(str)               # sleep | quit | stopped | error
    hands_free_changed = pyqtSignal(bool)

    def __init__(self, run_session=None, listen_voice=None, parent=None):
        super().__init__(parent)
        self._run_session = run_session or _default_run
        self._listen_voice = listen_voice or _default_listen_voice
        self._commands = queue.Queue()
        self._thread = None
        self._stopping = threading.Event()
        self._hands_free = threading.Event()
        self._voice_busy = threading.Lock()
        self._phase = "ended"                 # starting | waiting | working | ended
        self._listening = False
        self._state = "locked"
        self._state_lock = threading.Lock()
        self._speech_listener = lambda text: self.said.emit(text)

    # ---- what the window can ask for

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self):
        return self._state

    @property
    def hands_free(self):
        return self._hands_free.is_set()

    def start(self):
        """Begin a session. False if one is already running."""
        if self.running:
            return False
        self._stopping.clear()
        while not self._commands.empty():
            self._commands.get_nowait()
        self._phase = "starting"
        self._refresh()
        self._thread = threading.Thread(target=self._run, name="jarvis-session", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stopping.set()
        self._commands.put(_STOP)

    def submit(self, text):
        """Hand a typed command to the session. False if there is no session to receive it."""
        text = (text or "").strip()
        if not text or not self.running:
            return False
        self.heard.emit(text)
        self._commands.put(text)
        return True

    def set_hands_free(self, on):
        if on:
            self._hands_free.set()
        else:
            self._hands_free.clear()
        self.hands_free_changed.emit(bool(on))

    def talk(self):
        """Push to talk: listen once by voice and submit what was said. False if already listening or not running."""
        if not self.running or not self._voice_busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._talk, name="jarvis-push-to-talk", daemon=True).start()
        return True

    # ---- the session thread

    def _run(self):
        speech.add_listener(self._speech_listener)
        outcome = "stopped"
        tee = _Tee(self.log.emit, sys.stdout)
        try:
            with redirect_stdout(tee), redirect_stderr(tee):
                outcome = self._run_session(listen=self._next_command, ask=self._ask) or "stopped"
        except BaseException:                        # includes SystemExit from a closed console
            for line in traceback.format_exc().splitlines():
                self.log.emit(line)
            self.problem.emit("Jarvis stopped because of an error. The details are in the log.")
            outcome = "error"
        finally:
            speech.remove_listener(self._speech_listener)
            self._phase = "ended"
            self._refresh()
            self.ended.emit(outcome)

    def _next_command(self):
        """What the session calls to get the next command (it blocks until there is one)."""
        from MainCode import SessionStopped
        self._phase = "waiting"
        self._refresh()
        while True:
            if self._stopping.is_set():
                raise SessionStopped()
            if self._hands_free.is_set() and self._commands.empty():
                text = self._capture(LISTEN_TIMEOUT, PHRASE_LIMIT)
                if text is None:                     # the push-to-talk button has the microphone
                    time.sleep(0.2)
                    continue
                if not text:
                    continue
                self.heard.emit(text)
                item = text
            else:
                try:
                    item = self._commands.get(timeout=0.2)
                except queue.Empty:
                    continue
            if item is _STOP:
                raise SessionStopped()
            self._phase = "working"
            self._refresh()
            return item

    def _ask(self, question):
        """What the session calls to ask a follow-up question: say it, then take the next thing typed or spoken."""
        speech.Speak(question)
        return self._next_command()

    def _capture(self, timeout, phrase_limit, locked=False):
        """Listen once by voice. Returns the words, "" if nothing was understood or the microphone failed, or None
        if another capture already has the microphone."""
        if not locked and not self._voice_busy.acquire(blocking=False):
            return None
        try:
            self._listening = True
            self._refresh()
            try:
                return self._listen_voice(timeout, phrase_limit)
            except Exception as error:               # MicrophoneError, or anything a driver throws
                self.problem.emit(f"I can't use the microphone: {error}")
                if self._hands_free.is_set():
                    self.set_hands_free(False)
                return ""
        finally:
            self._listening = False
            self._voice_busy.release()
            self._refresh()

    def _talk(self):
        text = self._capture(8, PHRASE_LIMIT, locked=True)           # talk() already took the microphone lock
        if text:
            self.heard.emit(text)
            self._commands.put(text)
        elif self.running:
            self.problem.emit("I didn't hear anything. Click the microphone and try again.")

    def _refresh(self):
        with self._state_lock:
            if self._phase == "ended":
                state = "locked"
            elif self._listening:
                state = "listening"
            else:
                state = {"starting": "starting", "waiting": "ready", "working": "working"}[self._phase]
            changed, self._state = state != self._state, state
        if changed:
            self.state_changed.emit(state)
