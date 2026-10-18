"""A private record of every conversation, so you can look back at what was said and Jarvis can be improved from it.

Each day gets one file, Logs/conversations/YYYY-MM-DD.jsonl, with one line for each thing said:

    {"at": "2026-10-18T15:46:02", "who": "you", "text": "why is the sky blue"}
    {"at": "2026-10-18T15:46:09", "who": "jarvis", "text": "Because ...", "by": "chat"}

``by`` says what answered: command (a built-in command), chat (the model on this PC), fallback (a free online key, a web
answer or "did you mean"), reset, claude, or system (start-up lines, reminders).

The files stay on this PC (Logs/ is not in version control). LOG_CONVERSATIONS=false in .env switches the record off,
and files older than CONVERSATION_LOG_DAYS days are deleted at the start of each session (0 keeps everything).

    python transcript.py              today's conversations, in plain reading form
    python transcript.py --days 3     the last three days
    python transcript.py --you        only what you said (handy for seeing what Jarvis didn't understand)
    python transcript.py --delete     delete every saved conversation (asks first)
"""
import argparse
import datetime
import json
import sys
import threading

import config

LOG_DIR = config.LOGS_DIR / "conversations"
_lock = threading.Lock()
_context = threading.local()           # what is answering the command this thread is working on


def source(name):
    """Say what is answering the current command (command, chat, fallback, reset, claude), so replies can be labelled."""
    _context.by = name


def record(who, text, **extra):
    """Add one line to today's file. Never raises: a full disk must not stop Jarvis from talking."""
    if not config.LOG_CONVERSATIONS:
        return
    text = " ".join(str(text).split())
    if not text:
        return
    now = datetime.datetime.now()
    event = {"at": now.isoformat(timespec="seconds"), "who": who, "text": text}
    event.update({key: value for key, value in extra.items() if value not in (None, "", False)})
    try:
        with _lock:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def on_speech(text, first=True):
    """A speech.py listener (add it with streaming=True): every sentence Jarvis says, joined into replies."""
    record("jarvis", text, by=getattr(_context, "by", None) or "system", more=not first)


def begin(brain=""):
    """Start of a session: delete conversations older than CONVERSATION_LOG_DAYS and note the start."""
    prune()
    source("system")
    record("system", "session started", brain=brain)


def end(outcome):
    record("system", "session ended", outcome=outcome)


def prune(days=None, today=None):
    """Delete the daily files older than ``days`` (CONVERSATION_LOG_DAYS if not given; 0 keeps everything). Returns how many."""
    days = config.CONVERSATION_LOG_DAYS if days is None else days
    if days <= 0 or not LOG_DIR.is_dir():
        return 0
    cutoff = (today or datetime.date.today()) - datetime.timedelta(days=days)
    removed = 0
    for path in LOG_DIR.glob("*.jsonl"):
        try:
            if datetime.date.fromisoformat(path.stem) < cutoff:
                path.unlink()
                removed += 1
        except (ValueError, OSError):
            continue                                    # not one of ours, or in use: leave it
    return removed


def read(days=1, today=None):
    """The saved events of the last ``days`` days (1 = today only), oldest first."""
    today = today or datetime.date.today()
    events = []
    for back in range(days - 1, -1, -1):
        path = LOG_DIR / f"{today - datetime.timedelta(days=back):%Y-%m-%d}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue                                # a half-written line must not hide the rest
            if isinstance(event, dict) and isinstance(event.get("at"), str) and "T" in event["at"]:
                events.append(event)
    return events


def format_events(events, only_you=False):
    """The events as plain text: one line per thing said, with a heading for each day."""
    lines, day_shown, last_who = [], None, None
    for event in events:
        day, _, clock = event["at"].partition("T")
        who, text = event.get("who"), str(event.get("text", ""))
        if only_you and who != "you":
            continue
        if day != day_shown:
            try:
                heading = f"{datetime.date.fromisoformat(day):%A %d %B %Y}"
            except ValueError:
                heading = day
            lines.append(f"\n=== {heading} ===")
            day_shown = day
        if who == "jarvis" and event.get("more") and last_who == "jarvis" and lines:
            lines[-1] += " " + text                     # the next sentence of the reply above
            continue
        last_who = who
        if who == "you":
            lines.append(f"{clock}  YOU    : {'(answer) ' if event.get('kind') == 'answer' else ''}{text}")
        elif who == "jarvis":
            by = event.get("by")
            lines.append(f"{clock}  JARVIS : {'[' + by + '] ' if by and by != 'system' else ''}{text}")
        elif event.get("kind") == "timing":
            lines.append(f"{'':10}   ({event.get('model', '?')}: first words after {event.get('first_words', '?')}s, "
                         f"whole answer {event.get('total', '?')}s)")
        else:
            detail = ", ".join(f"{key} {value}" for key, value in event.items() if key in ("brain", "outcome"))
            lines.append(f"{clock}  --     : {text}{f' ({detail})' if detail else ''}")
    return "\n".join(lines).strip("\n")


def delete_all():
    """Delete every saved conversation. Returns how many files went."""
    removed = 0
    for path in LOG_DIR.glob("*.jsonl") if LOG_DIR.is_dir() else ():
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read the saved conversations with Jarvis.")
    parser.add_argument("--days", type=int, default=1, help="how many days back to show (1 = today)")
    parser.add_argument("--you", action="store_true", help="only what you said")
    parser.add_argument("--delete", action="store_true", help="delete every saved conversation")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")        # a console that can't show Urdu prints ? instead of crashing
    if args.delete:
        files = list(LOG_DIR.glob("*.jsonl")) if LOG_DIR.is_dir() else []
        if not files:
            print("There are no saved conversations.")
            return 0
        if input(f"Delete {len(files)} saved conversation file(s) for good? Type yes: ").strip().lower() != "yes":
            print("Nothing was deleted.")
            return 1
        print(f"Deleted {delete_all()} file(s).")
        return 0
    text = format_events(read(max(1, args.days)), only_you=args.you)
    print(text or ("Nothing has been saved " + ("today." if args.days <= 1 else f"in the last {args.days} days.")
                   + ("" if config.LOG_CONVERSATIONS else " (LOG_CONVERSATIONS is false in .env, so nothing is being recorded.)")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
