"""Runs the steps in order, says what each is for, copes with a step that goes wrong, and ends with a plain summary.

Modes:  fresh (a brand-new Jarvis), restore (bring back an earlier one from a backup first), repair (look at an installed one and
fix what is missing). Running it again never repeats finished work: each step first looks at the PC to see if its work is done.
"""
import datetime
import traceback

import backup_jarvis

from .context import State
from .steps import all_steps
from .steps.base import FAIL, OK, SKIP, TODO, WARN, Outcome

MARK = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", TODO: "[TODO]", SKIP: "[SKIP]"}
KIND = {OK: "ok", WARN: "warn", FAIL: "fail", TODO: "warn", SKIP: "dim"}


class Runner:
    def __init__(self, ctx, only=None, skip=(), steps=None):
        self.ctx = ctx
        self.steps = steps or all_steps()
        self.only = set(only) if only else None
        self.skip = set(skip)

    # ---- which steps

    def chosen_steps(self):
        """The steps that --only and --skip leave in. Whether one applies is decided when its turn comes (wanted() below), because
        what you answer in the early steps (no chat model, no shortcuts) decides whether the later ones are needed."""
        picked = []
        for step in self.steps:
            if step.id in self.skip:
                continue
            if self.only is not None and step.id not in self.only and step.id != "system":
                continue
            picked.append(step)
        return picked

    def wanted(self, step):
        """True if the step should run now: the look-around always; any step named with --only; otherwise the ones that apply."""
        return step.id == "system" or self.only is not None or step.applies(self.ctx)

    # ---- the parts of a run

    def welcome(self):
        c, ctx = self.ctx.console, self.ctx
        c.title("Jarvis setup")
        c.say("I will get Jarvis ready on this PC and set him up the way you like. It checks what is already done, so you can run it\n"
              "again any time and it only does what is missing. You can press Ctrl+C to stop; running it again carries on.")
        if ctx.mode == "auto":
            ctx.mode = self.guess_mode()
            ctx.mode = c.choose("mode", "What would you like to do?", [
                ("fresh", "Set up a brand-new Jarvis"),
                ("restore", "Bring back my earlier Jarvis from a backup (settings, password, notes, voice print, models), then finish the setup"),
                ("repair", "Check this Jarvis and fix whatever is missing"),
                ("reset", "Start completely fresh: save a copy of everything of mine that is here now, clear it, and set up as if Jarvis were brand new")],
                default=ctx.mode)
        if ctx.mode == "reset":
            self.start_over()
        if ctx.mode != "repair" and ctx.express is None:
            ctx.express = c.choose("style", "How much do you want to be asked?", [
                ("express", "Only the questions that matter; I choose sensible answers for the rest (recommended)"),
                ("custom", "Everything: I want to choose each setting myself")], default="express") == "express"
        if ctx.express is None:
            ctx.express = True

    def start_over(self):
        """The "reset" mode: copy what is the owner's into Backups/, check the copy, clear it, and carry on as a fresh setup."""
        ctx, c = self.ctx, self.ctx.console
        found = backup_jarvis.inventory(ctx.root)
        present = {part: found[part] for part in backup_jarvis.START_OVER_PARTS if part in found}
        if not present:
            c.say("There is nothing of yours in this folder yet, so it is already brand new.")
            ctx.mode = "fresh"
            return
        c.say("Starting over clears: " + "; ".join(f"{info['label']} ({info['files']} files)" for info in present.values()) + ".")
        c.note("First all of that is copied into the Backups folder here and every file of the copy is checked; nothing is cleared unless the copy is perfect. "
               "Your books, screenshots and the downloaded models stay.")
        if ctx.dry_run:
            c.note("(dry run: nothing was copied or cleared)")
            ctx.mode = "fresh"
            return
        if not c.confirm("start_over", "Save the copy and clear all of that now?", default=False):
            c.say("Nothing was changed.")
            ctx.mode = self.guess_mode()
            return
        try:
            saved, removed = backup_jarvis.start_over(ctx.root, progress=c.note)
        except (RuntimeError, OSError) as error:
            c.bad(str(error))
            c.say("Nothing was cleared.")
            ctx.mode = self.guess_mode()
            return
        c.good(f"Done: {removed} files cleared. Your copy is in {saved}.")
        ctx.state = State(ctx.root / "DataBase" / "setup_state.json")
        ctx.mode = "fresh"

    def guess_mode(self):
        """repair when there is already a .env here (a Jarvis that was set up before), otherwise fresh."""
        return "repair" if self.ctx.env.exists() else "fresh"

    def show_plan(self, steps):
        c, ctx = self.ctx.console, self.ctx
        c.blank()
        c.say("Here is what this run will look at:")
        for step in steps:
            if step.id == "system" or not self.wanted(step):
                continue
            check = step.check(ctx)
            c.write(f"   {MARK.get(check.state, '[ .. ]')} {step.title}" + (f" - {check.detail}" if check.detail else ""), KIND.get(check.state))

    def run_one(self, step, number, total):
        c, ctx = self.ctx.console, self.ctx
        c.step(number, total, step.title)
        check = step.check(ctx)
        if check.state == OK and not ctx.force and not step.read_only:
            c.good("Already done" + (f": {check.detail}" if check.detail else ""))
            return Outcome(OK, check.detail)
        if step.why:
            c.note(step.why)
        try:
            outcome = step.run(ctx)
        except KeyboardInterrupt:
            raise
        except Exception as error:                              # noqa: BLE001 - one step's trouble must not hide the others
            c.log(traceback.format_exc())
            c.bad(f"Something unexpected went wrong in this step: {type(error).__name__}: {error}")
            c.note("The details are in Logs/setup.log. Run the setup again to retry just this part.")
            return Outcome(FAIL, f"{type(error).__name__}: {error}")
        if outcome is None:
            outcome = Outcome(OK, "")
        if not step.read_only and not ctx.dry_run:
            ctx.state.step(step.id, outcome.state, outcome.detail)          # (a step whose check is "the wizard finished me" must see that now)
            ctx.state.save()
            if outcome.state in (OK, WARN):
                after = step.check(ctx)                                     # the step said it worked: does the PC agree?
                if after.state == TODO and outcome.state == OK:
                    outcome = Outcome(WARN, after.detail or outcome.detail)
        return outcome

    def run(self):
        ctx, c = self.ctx, self.ctx.console
        steps = self.chosen_steps()
        if not ctx.dry_run:
            ctx.state.data["started"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.welcome()
        # the look-around always runs first: everything else uses what it found
        system_step = next((s for s in steps if s.id == "system"), None)
        if system_step is not None:
            ctx.results["system"] = self.run_one(system_step, 1, len([s for s in steps if self.wanted(s)]))
            if ctx.results["system"].state == FAIL:
                c.bad("I cannot go on until that is fixed.")
                return self.finish(steps)
        rest = [s for s in steps if s.id != "system"]
        if not ctx.dry_run:
            self.show_plan(steps)
        done = 0
        for index, step in enumerate(rest):
            if not self.wanted(step):                      # (decided now: your earlier answers may have made it unnecessary)
                continue
            number = 2 + done
            total = number + len([s for s in rest[index + 1:] if self.wanted(s)])
            done += 1
            if ctx.dry_run:
                c.step(number, total, step.title)
                check = step.check(ctx)
                if check.state == OK and not ctx.force and not step.read_only:
                    c.good("Already done" + (f": {check.detail}" if check.detail else "") + " - nothing to do")
                else:
                    for line in step.plan(ctx) or ["(nothing to do)"]:
                        c.say("would: " + line)
                continue
            ctx.results[step.id] = self.run_one(step, number, total)
            ctx.state.step(step.id, ctx.results[step.id].state, ctx.results[step.id].detail)
            ctx.state.save()
        return self.finish(steps)

    def check_only(self):
        """The doctor: look at everything, change nothing. Returns 0 if nothing is wrong, 1 otherwise."""
        ctx, c = self.ctx, self.ctx.console
        c.title("Jarvis health check (nothing is changed)")
        system_step = next((s for s in self.steps if s.id == "system"), None)
        if system_step is not None:
            system_step.run(ctx)
        c.blank()
        bad = 0
        for step in self.steps:
            if step.id in ("system", "selfcheck") or not step.applies(ctx):
                continue
            check = step.check(ctx)
            c.write(f"   {MARK.get(check.state, '[ .. ]')} {step.title}" + (f" - {check.detail}" if check.detail else ""), KIND.get(check.state))
            if check.state in (TODO, FAIL):
                bad += 1
        c.blank()
        c.say("Everything is in order." if not bad else f"{bad} thing(s) need doing. Run Setup-Jarvis.bat (or  python setup_jarvis.py ) and it will do them.")
        return 1 if bad else 0

    # ---- the end

    def finish(self, steps):
        ctx, c = self.ctx, self.ctx.console
        c.title("Summary" + (" (dry run: nothing was changed)" if ctx.dry_run else ""))
        failed, warned = [], []
        for step in steps:
            outcome = ctx.results.get(step.id)
            if outcome is None:
                continue
            c.write(f"   {MARK.get(outcome.state, '[ .. ]')} {step.title}" + (f" - {outcome.detail}" if outcome.detail else ""), KIND.get(outcome.state))
            (failed if outcome.state == FAIL else warned if outcome.state in (WARN, TODO) else []).append(step)
        if not ctx.dry_run:
            ctx.state.data["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
            ctx.state.data["mode"] = ctx.mode
            ctx.state.data["answers"] = {key: value for key, value in c.asked if value not in ("(given)", "(not given)", "(left empty)")}
            ctx.state.save()
        c.blank()
        if ctx.dry_run:
            c.say("That was only a preview: nothing was installed, downloaded or changed. Run it without --dry-run to do it.")
        elif failed:
            c.bad("Not everything worked: " + ", ".join(s.title for s in failed) + ". Fix what is described above and run Setup-Jarvis.bat again; it carries on from here.")
        elif warned:
            c.warn("Jarvis should work, but some things need a look: " + ", ".join(s.title for s in warned) + ". Run Setup-Jarvis.bat again when you can.")
        else:
            c.good("Jarvis is ready.")
        c.blank()
        c.say("To start Jarvis:        double-click Start-Jarvis.bat (or the Jarvis shortcut on the desktop)")
        c.say("Settings and your own:  click ADMIN in the Jarvis window (it asks for your password), or run Admin-Panel.bat")
        c.say("How to use him:         open MANUAL.md (every command, every setting, and what to do when something is wrong)")
        c.say("Setup log:              Logs/setup.log")
        return 1 if failed else 0
