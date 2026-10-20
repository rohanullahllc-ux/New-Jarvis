"""Reading and changing the .env file safely. Used by the setup wizard, the admin panel and gate.py.

A hand-edited .env has comments, blank lines and settings this program does not know about. Everything here keeps all of that
exactly as it was and changes only the lines it is asked to change:

* a setting that is already there is changed on its own line (the last one, because the last one wins when a key is repeated);
* a setting that is not there yet is added, right after its commented-out example if the file has one, otherwise at the end;
* the file is written to a temporary file first and then swapped in, so a crash or a full disk can never leave half a .env;
* before the first change a copy is kept as .env.bak-<date and time> (the ten newest are kept), so a wrong change can be undone.

It uses only the standard library, because the setup wizard runs before anything is installed.

    python envfile.py show           the settings in .env, with passwords and keys hidden
    python envfile.py check          say whether python-dotenv (which config.py uses) reads every value the way this module does
"""
import datetime
import os
import re
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
KEEP_BACKUPS = 10

_LINE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n?)$")
_LINES = re.compile(r"[^\n]*\n|[^\n]+")          # a line with its line ending (a line feed, and the carriage return before it if there is one)
_COMMENTED = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_PLAIN = re.compile(r"(?:[^\s'\"#$\\=`]|\$(?!\{))(?:[^'\"#$\\`\r\n]|\$(?!\{))*")          # a value that can be written as it is, with no quotes ($ is fine; ${ is not)


def quote(value):
    """``value`` written so that python-dotenv (and read_value below) gives back exactly the same text."""
    value = str(value)
    if value == "" or (_PLAIN.fullmatch(value) and value == value.strip()):
        return value
    if "\n" in value or "\r" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'
    if "'" not in value:
        return "'" + value + "'"                                # single quotes keep everything literal, including $ and #
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_value(raw):
    """The text a value written in a .env line stands for (quotes taken off, escapes read, a trailing " # comment" ignored)."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        out, chars, index = [], raw[1:-1], 0
        while index < len(chars):
            if chars[index] == "\\" and index + 1 < len(chars):
                nxt = chars[index + 1]
                out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "'": "'"}.get(nxt, "\\" + nxt))
                index += 2
            else:
                out.append(chars[index])
                index += 1
        return "".join(out)
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def mask(value, keep=0):
    """A password or key as stars, so that it can be shown in a list or a log: '******' (the last ``keep`` characters may stay)."""
    value = str(value or "")
    if not value:
        return ""
    return "*" * max(6, len(value) - keep) + (value[-keep:] if keep else "")


class EnvFile:
    """One .env file. Nothing is read or written until you ask."""

    def __init__(self, path=None):
        self.path = Path(path) if path else ENV_PATH

    # ---- reading

    def lines(self):
        """The file's lines, each with the line ending it has (split at line feeds only, so an odd character inside a value is safe)."""
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8-sig", newline="") as handle:         # (a byte order mark is dropped; line endings are kept)
            return _LINES.findall(handle.read())

    def values(self):
        """{setting: value} for every setting in the file (the last one wins when a key is repeated)."""
        found = {}
        for line in self.lines():
            match = _LINE.match(line)
            if match and not line.lstrip().startswith("#"):
                found[match.group(2)] = read_value(match.group(4))
        return found

    def get(self, key, default=""):
        return self.values().get(key, default)

    def exists(self):
        return self.path.exists()

    # ---- writing

    def set(self, key, value):
        return self.set_many({key: value})

    def set_many(self, updates):
        """Change or add settings. Returns [(key, old, new)] for the ones whose value really changed (old is None if it was new)."""
        updates = {key: "" if value is None else str(value) for key, value in updates.items()}
        for key in updates:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"{key!r} is not a valid setting name")
            if "\x00" in updates[key]:
                raise ValueError(f"the value of {key} contains a null character")
        lines = self.lines()
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        last_line = {}
        commented_example = {}
        for number, line in enumerate(lines):
            match = _LINE.match(line)
            if match and not line.lstrip().startswith("#"):
                last_line[match.group(2)] = number
            else:
                example = _COMMENTED.match(line)
                if example:
                    commented_example.setdefault(example.group(1), number)
        old_values = self.values()
        changes, to_append, after_example = [], [], {}
        for key, new in updates.items():
            written = f"{key}={quote(new)}\n"
            if key in last_line:
                if old_values.get(key) == new:
                    continue
                match = _LINE.match(lines[last_line[key]])
                lines[last_line[key]] = match.group(1) + written.rstrip("\n") + (match.group(5) or "\n")       # (keeps the line ending the file uses)
                changes.append((key, old_values.get(key), new))
            elif key in commented_example:
                after_example[commented_example[key]] = written
                changes.append((key, None, new))
            else:
                to_append.append(written)
                changes.append((key, None, new))
        if not changes:
            return []
        for number in sorted(after_example, reverse=True):
            lines.insert(number + 1, after_example[number])
        if to_append:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.append("# ---- added by the Jarvis setup / admin panel " + datetime.date.today().isoformat() + "\n")
            lines.extend(to_append)
        self._write("".join(lines))
        return changes

    def remove(self, key):
        """Delete a setting's line(s). True if there was one."""
        lines = self.lines()
        kept = [line for line in lines if not (_LINE.match(line) and not line.lstrip().startswith("#") and _LINE.match(line).group(2) == key)]
        if len(kept) == len(lines):
            return False
        self._write("".join(kept))
        return True

    def _write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._backup()
        handle, temporary = tempfile.mkstemp(prefix=".env-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _backup(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        number = 1
        while target.exists():
            number += 1
            target = self.path.with_name(f"{self.path.name}.bak-{stamp}-{number}")
        target.write_bytes(self.path.read_bytes())
        old = sorted(self.path.parent.glob(self.path.name + ".bak-*"))
        for stale in old[:-KEEP_BACKUPS]:
            try:
                stale.unlink()
            except OSError:
                pass

    def backups(self):
        """The saved copies of this file, newest first."""
        return sorted(self.path.parent.glob(self.path.name + ".bak-*"), reverse=True)

    def restore_latest_backup(self):
        """Put the newest saved copy back. Returns its path, or None if there is none."""
        found = self.backups()
        if not found:
            return None
        with open(found[0], encoding="utf-8-sig", newline="") as handle:
            self._write(handle.read())
        return found[0]


def _check_against_dotenv():
    try:
        from dotenv import dotenv_values
    except ImportError:
        print("python-dotenv is not installed, so there is nothing to compare with.")
        return 0
    probes = ["plain", "with space inside", " padded ", "has # hash", "has $dollar and ${braces}", "it's quoted", 'say "hi"',
              "back\\slash", "line one\nline two", "", "=starts with equals", "tab\there", "p@ss:w0rd/with?symbols&more=1"]
    folder = Path(tempfile.mkdtemp(prefix="envcheck-"))
    env = EnvFile(folder / ".env")
    env.set_many({f"K{n}": value for n, value in enumerate(probes)})
    theirs = dotenv_values(env.path, interpolate=False)       # (config.py reads it the same way: a value is never "expanded")
    bad = 0
    for n, value in enumerate(probes):
        mine, other = env.get(f"K{n}"), theirs.get(f"K{n}")
        if not (mine == value == other):
            bad += 1
            print(f"DIFFERENT for {value!r}: this module reads {mine!r}, python-dotenv reads {other!r}")
    print("python-dotenv reads every value exactly as written." if not bad else f"{bad} value(s) differ.")
    return 1 if bad else 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "show"
    if command == "check":
        sys.exit(_check_against_dotenv())
    shown = EnvFile().values()
    if not shown:
        print(f"{ENV_PATH} has no settings (or does not exist).")
    for name, value in shown.items():
        secret = re.search(r"PASSWORD|API_KEY|APP_ID|SECRET|TOKEN", name)
        print(f"{name}={mask(value) if secret and value else value}")
