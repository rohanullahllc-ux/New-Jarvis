"""The command line of the wizard.

    python setup_jarvis.py                    the wizard (asks what to do)
    python setup_jarvis.py --check            only look and report; change nothing
    python setup_jarvis.py --dry-run          show what the wizard would do; change nothing
    python setup_jarvis.py --yes              take every recommended answer without asking
    python setup_jarvis.py --answers a.json   answers prepared in a file (for an unattended setup)
    python setup_jarvis.py --set USER_NAME=Ali --set DEFAULT_CITY=Lahore
    python setup_jarvis.py --mode restore --restore-from F:\\Backup-2026-10-20
    python setup_jarvis.py --only models,voice          just these steps  (--list-steps shows their names)
    python setup_jarvis.py --mode reset                 start completely fresh (a checked copy of your things is saved first; asks before clearing)
"""
import argparse
import json
import sys
from pathlib import Path

from .console import Console
from .context import Context
from .effects import Effects
from .runner import Runner
from .steps import all_steps


def parse(argv):
    p = argparse.ArgumentParser(prog="setup_jarvis.py", description="Get Jarvis ready on this PC and set him up the way you like.")
    p.add_argument("--check", action="store_true", help="only look and report; change nothing")
    p.add_argument("--dry-run", action="store_true", help="show what would be done; change nothing")
    p.add_argument("--yes", action="store_true", help="take the recommended answer to every question")
    p.add_argument("--custom", action="store_true", help="ask about every setting, not only the ones that matter")
    p.add_argument("--force", action="store_true", help="run steps again even if they look finished")
    p.add_argument("--mode", choices=["auto", "fresh", "restore", "repair", "reset"], default="auto")
    p.add_argument("--restore-from", metavar="FOLDER", help="a backup folder to restore from (with --mode restore)")
    p.add_argument("--answers", metavar="FILE", help="a JSON file of ready answers")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a ready answer (repeatable)")
    p.add_argument("--only", metavar="STEPS", help="run only these steps, separated by commas")
    p.add_argument("--skip", metavar="STEPS", help="leave out these steps, separated by commas")
    p.add_argument("--project", metavar="FOLDER", help="the Jarvis folder to set up (default: the folder this file is in)")
    p.add_argument("--list-steps", action="store_true", help="list the steps and exit")
    p.add_argument("--no-color", action="store_true")
    return p.parse_args(argv)


def load_answers(args):
    answers = {}
    if args.answers:
        loaded = json.loads(Path(args.answers).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise SystemExit("The answers file must hold a JSON object like {\"USER_NAME\": \"Ali\"}.")
        answers.update(loaded)
    for pair in args.set:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--set needs KEY=VALUE, not '{pair}'")
        answers[key.strip()] = value
    if args.restore_from:
        answers["restore_from"] = args.restore_from
    return answers


def main(argv=None, console=None, effects=None, root=None):
    args = parse(argv if argv is not None else sys.argv[1:])
    root = Path(args.project or root or Path(__file__).resolve().parent.parent)
    if args.list_steps:
        for step in all_steps():
            print(f"  {step.id:15} {step.title}")
        return 0
    answers = load_answers(args)
    console = console or Console(answers, assume_yes=args.yes, colour=False if args.no_color else None, log_path=root / "Logs" / "setup.log")
    mode = args.mode if not args.restore_from or args.mode != "auto" else "restore"
    express = False if args.custom else (True if (args.yes or mode == "repair") else None)
    ctx = Context(root, console, effects or Effects(), mode=mode, dry_run=args.dry_run, express=express, force=args.force)
    runner = Runner(ctx, only=args.only.split(",") if args.only else None, skip=args.skip.split(",") if args.skip else ())
    try:
        if args.check:
            return runner.check_only()
        return runner.run()
    except KeyboardInterrupt:
        console.blank()
        console.warn("Stopped. Nothing is half-finished: run Setup-Jarvis.bat again and it carries on from here.")
        return 130
    finally:
        console.close()
