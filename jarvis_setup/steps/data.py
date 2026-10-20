"""Your data and your preferences: bringing an earlier Jarvis back from a backup, and asking what you like."""
import shutil
from pathlib import Path

import backup_jarvis

from .. import questions
from .base import OK, SKIP, TODO, WARN, Check, Outcome, Step


def _describe(backup):
    when = f"{backup.created:%d %b %Y %H:%M}" if backup.created else "date unknown"
    return f"{backup.label} - {when} - {backup.path}"


def _as_backup(text):
    """A Backup for a folder the user typed, or None if it is neither one of our backups nor a copy of the Jarvis folder."""
    path = Path(text.strip().strip('"'))
    if (path / "BACKUP.json").is_file() and (path / "files").is_dir():
        return backup_jarvis.Backup(path, "package", backup_jarvis._read_made(path), f"Jarvis backup {path.name}")
    if backup_jarvis._looks_like_project(path):
        return backup_jarvis.Backup(path, "project", None, f"A copy of the Jarvis folder ({path.name})")
    nested = path / "Jarvis" / "New Jarvis"                  # the layout of the full backup made by hand: <backup>\Jarvis\New Jarvis
    if backup_jarvis._looks_like_project(nested):
        return backup_jarvis.Backup(nested, "project", None, f"A copy of the Jarvis folder ({path.name})")
    return None


class RestoreStep(Step):
    id = "restore"
    title = "Bringing your data back from a backup"
    why = ("If you had Jarvis before, this brings back your settings and password, notes and tasks, voice print, face model and (to save "
           "downloads) the models. Nothing of yours is overwritten without first saving a copy.")

    def applies(self, ctx):
        return ctx.mode == "restore"

    def check(self, ctx):
        done = ctx.state.data.get("restored_from")
        return Check(OK if done else TODO, f"from {done}" if done else "no backup restored yet")

    def plan(self, ctx):
        return ["Look for backups on this PC's drives (or use the folder you give)",
                "Show what is in the one you choose and what would change",
                "Copy it back; a file of yours that would be replaced is first moved to Backups/replaced-before-restore-..."]

    def run(self, ctx):
        c = ctx.console
        given = c.answers.get("restore_from")
        backup = _as_backup(str(given)) if given else None
        if backup is None:
            c.say("Looking for backups on your drives...")
            found = backup_jarvis.find_backups()
            if found:
                options = [(str(i), _describe(b)) for i, b in enumerate(found)] + [("other", "Another folder (I will ask for it)"), ("none", "None: set up a brand-new Jarvis instead")]
                pick = c.choose("restore_pick", "Which backup should I use?", options, default="0")
                backup = found[int(pick)] if pick.isdigit() else None
                if pick == "other":
                    backup = None
            else:
                c.info("No backup was found on the drives.")
                pick = "other"
            if backup is None and pick != "none":
                for _ in range(3):
                    text = c.ask("restore_from", "Type the folder that holds your backup (for example F:\\Backup-2026-10-20 or F:\\Jarvis-Backup-2026-10-20_2130).\n"
                                 "Leave empty to skip.", default="")
                    if not text:
                        break
                    backup = _as_backup(text)
                    if backup:
                        break
                    c.warn("That folder is not a Jarvis backup or a copy of the Jarvis folder.")
                    c.answers.pop("restore_from", None)
        if backup is None:
            c.warn("No backup chosen, so Jarvis will be set up fresh.")
            ctx.mode = "fresh"
            return Outcome(SKIP, "no backup chosen")
        c.good("Using: " + _describe(backup))

        base = backup_jarvis.source_folder(backup)
        available = backup_jarvis.inventory(source_files=base)
        if not available:
            c.warn("That backup holds none of the things I know how to bring back.")
            return Outcome(WARN, "empty backup")
        options = [(part, f"{info['label']}  ({info['files']} files, {backup_jarvis.human(info['bytes'])})") for part, info in available.items()]
        parts = c.choose_many("restore_parts", "Which parts should I bring back?", options, defaults=[part for part in available if part != "files"],
                              help="The models are big but saving them spares you the downloads.")
        if not parts:
            return Outcome(SKIP, "nothing chosen")
        plan = backup_jarvis.plan_restore(backup, ctx.root, parts)
        c.say(f"{len(plan['copy'])} files to bring back, {plan['same']} already the same, {len(plan['differ'])} that differ from the ones here.")
        conflict = "keep_newer"
        if plan["differ"]:
            conflict = c.choose("restore_conflict", "For the files that differ, what should win?",
                                [("keep_newer", "Whichever was changed last (usual)"), ("replace", "The backup's"), ("keep", "The ones here")], default="keep_newer",
                                help="Either way a file that is replaced is first saved under Backups/.")
        if ctx.dry_run:
            c.note("(dry run: nothing was copied)")
            return Outcome(OK, "dry run")
        done = backup_jarvis.restore(backup, ctx.root, parts, conflict=conflict, progress=c.note)
        c.good(f"Restored {done['copied'] + done['replaced']} files.")
        ollama = backup_jarvis.ollama_models_beside(backup.path)
        if ollama is not None:
            ctx.choices["ollama_restore_from"] = str(ollama)
            c.info(f"The chat models saved with this backup ({ollama}) will be put back when Ollama is set up.")
        ctx.restored_from = str(backup.path)
        ctx.state.data["restored_from"] = str(backup.path)
        ctx.state.save()
        return Outcome(OK, f"restored from {backup.path}")


class ProfileStep(Step):
    id = "profile"
    title = "About you"
    why = "So that Jarvis greets you the way you like, uses your city and currency, and is set up the way you want."

    def check(self, ctx):
        if self.done_before(ctx):
            return Check(OK, "already answered")
        if self.hand_made(ctx):
            return Check(OK, "your settings are already in .env")
        if ctx.mode == "restore" and ctx.restored_from and ctx.env_values().get("USER_NAME") and not ctx.force:
            return Check(OK, "your settings came back with the backup")
        return Check(TODO, "")

    def plan(self, ctx):
        return ["Ask your name, what to call you, your city and currency, whether you want the chat brain, and how he fits into Windows",
                "Save the answers in the .env file (a complete, commented copy of the settings is made first if there is none)"]

    def run(self, ctx):
        c = ctx.console
        if not ctx.root.joinpath(".env").exists() and not ctx.dry_run:
            example = ctx.root / ".env.example"
            if example.exists():
                shutil.copyfile(example, ctx.root / ".env")
                c.note("Made .env from .env.example (every setting, with its explanation).")
                ctx.state.step("profile", "partial", "started")           # (so an interrupted run asks again rather than trusting the copy)
                ctx.state.save()
        questions.about_you(ctx)
        questions.brain(ctx)
        questions.privacy(ctx)
        questions.email(ctx)
        questions.windows_choices(ctx)
        return Outcome(OK, "answers saved" if not ctx.dry_run else "dry run")
