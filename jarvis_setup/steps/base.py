"""What a step is. check() looks at the PC and says whether the step's work is already done (so running the wizard twice does only
what is missing), plan() lists in plain words what run() would do (that is what --dry-run shows), and run() does it."""
from collections import namedtuple

Check = namedtuple("Check", "state detail")           # state: ok | todo | warn | skip | fail
Outcome = namedtuple("Outcome", "state detail")       # the same words, for what run() achieved

OK, TODO, WARN, SKIP, FAIL = "ok", "todo", "warn", "skip", "fail"


class Step:
    id = ""
    title = ""
    why = ""                      # one or two plain sentences shown before the step runs
    optional = False              # in an interactive run the user is asked whether to do it
    read_only = False             # never changes anything (the system look-around)

    def applies(self, ctx):
        return True

    def done_before(self, ctx):
        """True if an earlier run of the wizard finished this step."""
        return ctx.state.data["steps"].get(self.id, {}).get("state") == OK and not ctx.force

    def hand_made(self, ctx):
        """True for a Jarvis that was set up by hand, before the wizard existed: it has a .env, and the wizard has never run here.
        Questions about preferences are then taken as already answered (run the wizard with --force to be asked again)."""
        return not ctx.state.path.exists() and (ctx.root / ".env").exists() and not ctx.force

    def check(self, ctx):
        return Check(TODO, "")

    def plan(self, ctx):
        return []

    def run(self, ctx):
        return Outcome(OK, "")


def outcome_from(check):
    return Outcome(check.state, check.detail)


def tail(text, lines=4):
    """The last few lines of a program's output, for an error message."""
    kept = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])
