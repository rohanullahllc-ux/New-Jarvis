"""What the steps share: the project folder, the console, the outside-world helper, the settings file, what was found on this PC
and what the user has chosen so far. Also the small notebook the wizard keeps (DataBase/setup_state.json) so a second run knows what
the first one did. The notebook never holds a password or a key."""
import datetime
import json
import shutil
import sys
from pathlib import Path

import settings_registry as registry
from envfile import EnvFile, mask

from .effects import RunResult


class State:
    """DataBase/setup_state.json: which mode was used, the (non-secret) answers, and how each step ended last time."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {"version": 1, "mode": "", "answers": {}, "steps": {}, "started": "", "finished": ""}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass                                          # the notebook is a convenience; the wizard works without it

    def step(self, step_id, state, detail=""):
        self.data["steps"][step_id] = {"state": state, "detail": detail, "at": datetime.datetime.now().isoformat(timespec="seconds")}


class Context:
    def __init__(self, root, console, effects, mode="fresh", dry_run=False, express=True, force=False):
        self.root = Path(root)
        self.console = console
        self.effects = effects
        self.mode = mode                                  # fresh | restore | repair
        self.dry_run = dry_run
        self.express = express                            # True: only the questions that matter; False: every question
        self.force = force                                # run steps even when they look finished
        self.env = EnvFile(self.root / ".env")
        self.state = State(self.root / "DataBase" / "setup_state.json")
        self.facts = {}                                   # filled by the system step (see system.gather)
        self.results = {}                                 # step id -> (state, detail)
        self.python = sys.executable
        self.choices = {}                                 # things decided that are not settings: install_ollama, voices to download...
        self.restored_from = ""

    # ---- the settings file

    def env_values(self):
        return self.env.values()

    def value(self, key):
        """A setting as it is now (in .env), or its usual value."""
        return self.env_values().get(key) or registry.default_of(key)

    def save_settings(self, updates):
        """Check and write settings to .env (nothing is written in a dry run). Returns the list of (key, old, new) that changed."""
        clean = {}
        for key, raw in updates.items():
            result = registry.validate(key, raw)
            if not result.ok:
                self.console.warn(f"{key}: {result.message} - left as it was")
                continue
            clean[key] = result.value
        if not clean:
            return []
        if self.dry_run:
            for key, value in clean.items():
                self.console.note(f"would set {key}={self._shown(key, value)}")
            return []
        example = self.root / ".env.example"
        if not self.env.exists() and example.exists():
            shutil.copyfile(example, self.env.path)               # the first write of any step makes the full commented file, not a one-line one
        changes = self.env.set_many(clean)
        for key, old, new in changes:
            self.console.note(f"saved {key}={self._shown(key, new)}")
        return changes

    @staticmethod
    def _shown(key, value):
        setting = registry.BY_KEY.get(key)
        return mask(value) if (setting is not None and setting.secret and value) else value

    # ---- programs

    def run_python(self, arguments, visible=False, env=None, on_line=None, timeout=None):
        """Run a Python script of the project with the Python that runs the wizard, from the project folder."""
        command = [self.python, *arguments]
        if self.dry_run:
            self.console.note("would run: " + " ".join(command))
            return 0 if visible else RunResult(0, "")
        if visible:
            return self.effects.run_visible(command, cwd=str(self.root), env=env)
        return self.effects.run(command, cwd=str(self.root), env=env, on_line=on_line, timeout=timeout)

    @property
    def tier(self):
        return self.facts.get("tier")
