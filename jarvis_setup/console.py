"""What the wizard prints and asks.

Every question has a key (the name of the setting it fills, or a name of its own). A key found in the scripted answers is used
without asking, so the same wizard runs interactively, unattended (--answers file.json, --yes) and in tests. Anything secret
(a password) is never echoed and never written to the log.

Plain ASCII markers are used on purpose ([ OK ], [WARN]): an old Windows console shows fancier symbols as rubbish.
"""
import getpass
import os
import sys
import time

OK, WARN, FAIL, INFO, TODO = "[ OK ]", "[WARN]", "[FAIL]", "[ .. ]", "[TODO]"
_COLOURS = {"ok": "32", "warn": "33", "fail": "31", "info": "36", "dim": "90", "bold": "1", "head": "1;36"}


def _enable_ansi():
    """Turn on colour codes in the Windows console (Windows 10 and later understand them once asked). False if not possible."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:                                     # noqa: BLE001 - colour is a nicety
        return False


def _utf8(stream):
    """Make the stream write anything (a path with an unusual letter) without a crash: what it cannot show becomes a '?'."""
    try:
        stream.reconfigure(errors="replace")
    except Exception:                                     # noqa: BLE001
        pass


class Console:
    """Output, questions and a log file. ``answers`` is a dict of ready answers; ``assume_yes`` takes every recommended answer."""

    def __init__(self, answers=None, assume_yes=False, colour=None, log_path=None, out=None, read=None, read_secret=None, interactive=None):
        self.out = out or sys.stdout
        _utf8(self.out)
        self.answers = dict(answers or {})
        self.assume_yes = assume_yes
        self.used_answers = set()
        self._read = read or input
        self._read_secret = read_secret or getpass.getpass
        if interactive is None:
            interactive = bool(read) or (sys.stdin is not None and sys.stdin.isatty())
        self.interactive = interactive
        if colour is None:
            colour = bool(getattr(self.out, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ and _enable_ansi()
        self.colour = colour
        self.log_path = log_path
        self._log_file = None
        self.asked = []                                   # (key, answer) of every question, for the tests and the summary

    # ---- the log

    def _log(self, text):
        if not self.log_path:
            return
        try:
            if self._log_file is None:
                os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
                self._log_file = open(self.log_path, "a", encoding="utf-8", buffering=1)
                self._log_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} setup started ===\n")
            self._log_file.write(f"{time.strftime('%H:%M:%S')} {text}\n")
        except OSError:
            self.log_path = None                          # a log that cannot be written must never stop the wizard

    def close(self):
        if self._log_file:
            self._log_file.close()
            self._log_file = None

    # ---- output

    def _paint(self, text, kind):
        return f"\033[{_COLOURS[kind]}m{text}\033[0m" if self.colour else text

    def write(self, text="", kind=None):
        self.out.write((self._paint(text, kind) if kind else text) + "\n")
        self.out.flush()
        self._log(text)

    def blank(self):
        self.write("")

    def log(self, text):
        """Put a line in the log file only (the full output of a program that is too long to show)."""
        self._log(text)

    def title(self, text):
        self.write("")
        self.write("=" * 74, "head")
        self.write(f"  {text}", "head")
        self.write("=" * 74, "head")

    def step(self, number, total, text):
        self.write("")
        self.write(f"--- Step {number} of {total}: {text} " + "-" * max(3, 56 - len(text)), "bold")

    def say(self, text):
        self.write("  " + text.replace("\n", "\n  "))

    def note(self, text):
        self.write("  " + text.replace("\n", "\n  "), "dim")

    def good(self, text):
        self.write(f"  {OK} {text}", "ok")

    def warn(self, text):
        self.write(f"  {WARN} {text}", "warn")

    def bad(self, text):
        self.write(f"  {FAIL} {text}", "fail")

    def info(self, text):
        self.write(f"  {INFO} {text}", "info")

    def todo(self, text):
        self.write(f"  {TODO} {text}", "warn")

    def progress(self, text):
        """A line that is replaced by the next one (a download's percentage). Not written to the log."""
        if self.out.isatty() if hasattr(self.out, "isatty") else False:
            self.out.write("\r  " + text.ljust(70)[:70])
            self.out.flush()

    def end_progress(self):
        if self.out.isatty() if hasattr(self.out, "isatty") else False:
            self.out.write("\r" + " " * 74 + "\r")
            self.out.flush()

    # ---- questions

    def _ready(self, key):
        if key in self.answers:
            self.used_answers.add(key)
            return True, self.answers[key]
        return False, None

    def _take(self, key, shown):
        self.asked.append((key, shown))
        self._log(f"  > {key}: {shown}")

    def ask(self, key, question, default="", validate=None, help=""):
        """Ask for some text. Enter keeps the default. ``validate(text)`` returns (ok, cleaned, message); a wrong answer is asked again."""
        ready, value = self._ready(key)
        if ready:
            value = "" if value is None else str(value)
            if validate:
                ok, cleaned, message = validate(value)
                if not ok:
                    self.warn(f"{key}: {message} (the answer given was not used)")
                    value = default
                else:
                    value = cleaned
            self._take(key, value)
            return value
        if self.assume_yes or not self.interactive:
            self._take(key, default)
            return default
        for _ in range(5):
            self.write("")
            self.say(question)
            if help:
                self.note(help)
            shown = f" [{default}]" if default != "" else ""
            reply = self._read(f"  > {shown} " if shown else "  > ").strip()
            value = reply if reply != "" else default
            if validate:
                ok, cleaned, message = validate(value)
                if not ok:
                    self.warn(message)
                    continue
                value = cleaned
            self._take(key, value)
            return value
        self.warn("Too many tries; using the usual answer.")
        self._take(key, default)
        return default

    def confirm(self, key, question, default=True, help=""):
        """A yes/no question. Enter takes the default."""
        ready, value = self._ready(key)
        if ready:
            result = str(value).strip().lower() in ("1", "true", "yes", "y", "on") if not isinstance(value, bool) else value
            self._take(key, "yes" if result else "no")
            return result
        if self.assume_yes or not self.interactive:
            self._take(key, "yes" if default else "no")
            return default
        self.write("")
        self.say(question)
        if help:
            self.note(help)
        for _ in range(5):
            reply = self._read(f"  > (y/n) [{'Y' if default else 'N'}] ").strip().lower()
            if reply == "":
                result = default
            elif reply in ("y", "yes", "yeah", "yep", "ok", "sure", "1", "true"):
                result = True
            elif reply in ("n", "no", "nope", "0", "false"):
                result = False
            else:
                self.warn("Please type y for yes or n for no.")
                continue
            self._take(key, "yes" if result else "no")
            return result
        self._take(key, "yes" if default else "no")
        return default

    def choose(self, key, question, options, default=None, help=""):
        """Pick one of ``options`` = [(value, description)]. Type its number, or its value. Enter takes the default (a value)."""
        values = [value for value, _ in options]
        default = default if default in values else values[0]
        ready, value = self._ready(key)
        if ready:
            if value in values:
                self._take(key, value)
                return value
            self.warn(f"{key}: '{value}' is not one of {', '.join(map(str, values))}; using {default}")
            self._take(key, default)
            return default
        if self.assume_yes or not self.interactive:
            self._take(key, default)
            return default
        self.write("")
        self.say(question)
        if help:
            self.note(help)
        for number, (value, description) in enumerate(options, 1):
            self.write(f"   {number}) {description}" + ("   <- usual" if value == default else ""))
        for _ in range(5):
            reply = self._read(f"  > [{values.index(default) + 1}] ").strip()
            if reply == "":
                chosen = default
            elif reply.isdigit() and 1 <= int(reply) <= len(values):
                chosen = values[int(reply) - 1]
            elif reply in values:
                chosen = reply
            else:
                self.warn(f"Type a number from 1 to {len(values)}.")
                continue
            self._take(key, chosen)
            return chosen
        self._take(key, default)
        return default

    def choose_many(self, key, question, options, defaults=(), help=""):
        """Pick any of ``options`` = [(value, description)]: type numbers separated by commas, 'all', or 'none'. Returns a list of values."""
        values = [value for value, _ in options]
        ready, value = self._ready(key)
        if ready:
            picked = [v for v in (value if isinstance(value, (list, tuple)) else [value]) if v in values]
            self._take(key, ",".join(map(str, picked)))
            return picked
        if self.assume_yes or not self.interactive:
            picked = [v for v in defaults if v in values]
            self._take(key, ",".join(map(str, picked)))
            return picked
        self.write("")
        self.say(question)
        if help:
            self.note(help)
        for number, (item, description) in enumerate(options, 1):
            self.write(f"   {number}) {description}" + ("   <- usual" if item in defaults else ""))
        usual = ",".join(str(values.index(v) + 1) for v in defaults if v in values) or "none"
        for _ in range(5):
            reply = self._read(f"  > numbers like 1,3 or all or none [{usual}] ").strip().lower()
            if reply == "":
                picked = [v for v in defaults if v in values]
            elif reply == "all":
                picked = list(values)
            elif reply == "none":
                picked = []
            else:
                try:
                    numbers = [int(part) for part in reply.replace(" ", ",").split(",") if part]
                except ValueError:
                    self.warn("Type numbers separated by commas, for example 1,3.")
                    continue
                if not all(1 <= n <= len(values) for n in numbers):
                    self.warn(f"Use numbers from 1 to {len(values)}.")
                    continue
                picked = [values[n - 1] for n in numbers]
            self._take(key, ",".join(map(str, picked)))
            return picked
        return [v for v in defaults if v in values]

    def secret(self, key, question, confirm_again=True, minimum=0):
        """Ask for a password or key without showing it. Returns the text ('' if nothing was given). Never logged."""
        ready, value = self._ready(key)
        if ready:
            self._take(key, "(given)")
            return "" if value is None else str(value)
        if self.assume_yes or not self.interactive:
            self._take(key, "(not given)")
            return ""
        self.write("")
        self.say(question)
        for _ in range(5):
            first = self._read_secret("  > (typing is hidden) ").strip()
            if first == "":
                self._take(key, "(left empty)")
                return ""
            if minimum and len(first) < minimum:
                self.warn(f"Please use at least {minimum} characters.")
                continue
            if confirm_again and self._read_secret("  > once more: ").strip() != first:
                self.warn("The two entries are different; try again.")
                continue
            self._take(key, "(given)")
            return first
        return ""

    def pause(self, text="Press Enter to continue"):
        if self.assume_yes or not self.interactive:
            return
        self._read(f"  {text} ")
