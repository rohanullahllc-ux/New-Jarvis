# CLAUDE.md - read this first (for a new Claude session)

You are continuing **New Jarvis**, a Windows voice assistant in Python 3.14, built over many sessions for one owner who is **not a programmer**.
This file is loaded automatically by Claude Code. It gives you the rules, the map and the recipes; `docs/PROJECT_GUIDE.md` has the full breakdown
(read it before a big change), `MANUAL.md` is the user's manual, `ROADMAP.md` is the plan, `README.md` is the overview.

## 1. The owner and how to work with them

* Lives in Peshawar, Pakistan (default city Peshawar, currency PKR, accent `en-pk`). Calls themselves "Mr Khan" in the settings. **Not a coder:** explain in plain
  words, give exact commands to run, report results in plain language (what you did, what you saw, what is left), and keep them posted every few minutes on long work.
* Wants **live, visible tests** (run the real thing and show the output), not just "the unit tests pass".
* Their PC: Intel i5-6200U (2 cores, 4 threads), about 8 GB RAM (often under 2 GB free), no GPU, a SATA SSD that holds both C: and D:, an external 500 GB USB HDD as F:.
  The wizard calls this a "light" PC. Windows 10 Pro in October 2026, being replaced by Windows 11 Lite (Tiny11; may lack winget, the Store, the Visual C++ runtime).
* They run scripts on the **global Python 3.14** (VS Code's Run button), **not in a venv**. They have **no paid AI keys**: everything free and local first.
* The Windows user folder is **`C:\Users\Rohaan & Co`**: an ampersand and a space. Quote every path; in batch files never print `%VAR%` unquoted; `cmd /c "path"` with an `&` in
  the path needs doubled outer quotes (`cmd /c ""C:\a & b\x.bat""`); in PowerShell/Python pass argument lists, never shell strings.

### Rules the owner has given (obey them)

1. **Finish the phase or task you were asked for, then STOP and wait for instructions.** Do not start another phase or any other development unasked.
2. **Commit and push only when asked**, or when they ask for a backup. End commit messages with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
   (use the attribution line your system prompt gives). The GitHub repo is **private**: `rohanullahllc-ux/New-Jarvis` (branch `main`; sign-in is stored by Git Credential Manager; there is no `gh` CLI).
3. Confirm before anything outward-facing or hard to reverse. Never print a secret (`.env` values, passwords, keys, tokens). Never copy secrets into OneDrive (it is cloud-synced).
4. **Never touch the owner's real data in tests**: tests use temporary folders (see section 5). Never put the real `DataBase/Notes`, `Tasks`, `memory.json`, `.env`, voice print or `Logs/` at risk.
5. Never write to the Rufus pen drive (the Windows installer). Never modify or delete `F:\ProtectionHub-Backup` (the old backup, read-only reference). New backups go into **new** folders.
6. Do not change system settings (Windows volume, power, startup entries) unless the owner asks. They changed their own speaker volume; the wizard only sets what they agree to.
7. Shutdown/restart/sleep/email/deleting notes or tasks always need a clear spoken or typed yes. Jarvis never deletes files, folders or programs by voice. Keep it that way.
8. Say plainly when something failed or was skipped; do not claim success you did not check.

## 2. State of the project (update this section when you finish work)

* **Built and tested (1,500+ tests pass):** the command brain (`LocalBrain`, ~60 tools), their own trained command model (`NLU`), chat over Ollama (`ChatBrain`),
  the PyQt5 window, the password gate, the voice package (Piper voice, Whisper hearing, "hey Jarvis" wake word, clap detector, voice lock), the conversation record, and (2026-10-20) the
  **setup wizard** (`Setup-Jarvis.bat`, `jarvis_setup/`), the **admin panel** (`gui/admin_panel.py`), **shortcuts and contacts**, **backup/restore** (`backup_jarvis.py`),
  the **settings registry** (`settings_registry.py`), `MANUAL.md` and this handover.
* **Waiting for the owner's own live gate (cannot be proven by loopback tests here):** Phase A on their voice and claps: `python voice_test.py`, `python enroll_voice.py` then `--test`,
  `python clap.py --live`, then `JarvisGUI.py` woken by voice and by clapping. Tune `STT_MODEL`, `WAKE_SENSITIVITY`, `CLAP_SENSITIVITY`, `VOICE_MATCH` from those numbers.
  The wizard's real downloads and installs (VC++ runtime, Python packages, Ollama) were tested with pretend effects and by a dry run on the real PC, not by a full install on a bare Windows:
  the first real run on the new Windows 11 Lite is the live test; read `Logs/setup.log` if it misbehaves.
* **The owner's "most advanced idea" (Phase I) is still undescribed.** Ask them when they are ready; do not guess.
* **Backups (2026-10-20):** GitHub (private, code only: no `.env`, models, personal data) and the HDD `F:\Backup-2026-10-20\` (full copy: `Jarvis\New Jarvis`, Ollama models, `D-drive-not-yet-backed-up`,
  `D-drive-skipped-earlier`, `Jarvis-FINAL`, a README and a SHA-256 manifest). A fresh PC is restored with `Setup-Jarvis.bat` (see `MANUAL.md` section 2.2).
* Known odd things in the owner's own files: `.env` had `STARTUP_GREETING=long` (invalid; the admin panel flags it) and a plain-text `JARVIS_PASSWORD` (the wizard offers to scramble it).

## 3. Running things

```
python -m unittest discover -s tests                   all tests, about 3 minutes, offline, touches nothing real
python -m unittest tests.test_localbrain -v             one module
python setup_jarvis.py --check                          the read-only health check of this PC (what the admin panel's Overview shows)
python setup_jarvis.py --dry-run --yes                  what the wizard would do (changes nothing)
python settings_registry.py --check                     is .env.example / the MANUAL settings table up to date with the registry?
python JarvisGUI.py   |   python JarvisAdmin.py   |   python Startup.py        the window, the admin panel, the terminal version
python tests/live_check.py                              asks the real web services (run it when a tool seems broken)
```

The double-click launchers (`Setup-Jarvis.bat`, `Start-Jarvis.bat`, `Admin-Panel.bat`) find Python with `jarvis_setup/find_python.cmd`.

## 4. The map (details in `docs/PROJECT_GUIDE.md`)

```
Startup.py / JarvisGUI.py            the two ways in (terminal / window); both go through gate.py (password, optional camera check)
JarvisAdmin.py                       the admin panel on its own;   setup_jarvis.py  the setup wizard
config.py                            every setting read from .env (nothing else reads os.environ);  settings_registry.py is the master LIST of settings
MainCode.py                          one session: greet, then commands until sleep/quit        transcript.py  the conversation record
JarvisAdvancedBot/                   LocalBrain (patterns -> tools), Frames, NLU, ChatBrain (Ollama), FreeBrain, JarvisAiBrain (Claude), tools/ (one ability each)
speech.py tts_piper.py               everything Jarvis says (Piper voice, Windows voice fallback); personal.py swaps "sir" for ADDRESS_AS
microphone.py winmm_mic.py stt.py    listening: backends, Whisper; speaker.py enroll_voice.py voice lock; wakeword.py clap.py listener.py wake by voice/claps
gui/                                 PyQt5: main_window, session (threads -> signals), login_dialog, theme, admin_panel + admin_widgets
jarvis_setup/                        the wizard (stdlib only): console, effects, system, steps/, questions, windows, runner, cli
envfile.py backup_jarvis.py          safe .env editing; backup and restore of personal data
shortcuts.py contacts.py ui_bridge.py  the owner's own lists; a message box from the session thread to the window
training/                            the phrases and trainer for his own command model;   tests/  offline tests (isolation helpers in tests/isolation.py)
```

## 5. Hard-won rules for the code

* **Import order crash:** importing `onnxruntime` AFTER `PyQt5` kills the process on this Windows. `gui/__init__.py` calls `native_libs.preload()` first; never import PyQt5 before the voice libraries
  in a script, and never let a test import the real `piper`/`onnxruntime` (the suite crashes).
* **Tests must never reach the real world.** Helpers in `tests/isolation.py`: `no_language_model()` (also gives a temporary DataBase and no personal shortcuts/contacts), `isolated_database()`,
  `no_personal_lists()`, `no_whisper()`, `no_natural_voice()`, `no_voice_lock()`, `no_windows_audio()`. Tests of the wizard use `tests/setup_support.py` (a pretend PC: `FakeEffects`, `World`).
  A probe in the session of 2026-10-20 found an old test that wrote "buy milk" notes into the real Notes folder on every run; always check with a before/after listing of `DataBase/` when you add tests.
* **Settings flow:** a setting is added in `config.py` (the reader), in `settings_registry.py` (label, help, kind, range, default, group), then run
  `python settings_registry.py --write-example` and `--write-manual`. `tests/test_settings_registry.py` compares the registry with `config.py` by parsing it (`ast`), so one cannot be forgotten.
  `.env` is edited only through `envfile.py` (keeps comments and unknown keys, atomic write, `.env.bak-*` copies, python-dotenv compatible quoting). `config.py` loads with `interpolate=False`.
* **Command routing order matters** (`LocalBrain.INTENTS` is first-match): specific before generic; `is_command()` uses the first matching handler; handlers named in `GENERIC_HANDLERS` do not count as commands.
  The name "jarvis" is stripped from every command by `normalize()` (so "open Jarvis settings" is rewritten before that, see `JARVIS_SETTINGS`).
* **Whisper:** a prompt/hint made of whole sentences makes it repeat them; keep the vocabulary hint a word list; output is capped and a runaway is retried.
* **The wizard may use only the standard library** (it runs before anything is installed): a test enforces it. Everything it does to the outside world goes through `jarvis_setup/effects.py`, which tests replace.
* **Wording:** plain, kind sentences for the owner ("I couldn't find...", never stack traces in the window); British spelling in prose; comments explain *why* (match the surrounding style and density).
* **Tooling traps in this environment:** a shell here-document containing `\\n` or `\\s` can lose the backslash: write code with backslashes through the Edit/Write tools, or a script file.
  The Write tool writes LF; Windows scripts (`.bat`, `.cmd`, `.ps1`) must be CRLF (`.gitattributes` and a test enforce it).

## 6. Recipes

**Add a spoken command.** Write a tool in `JarvisAdvancedBot/tools/<area>.py` (a function with a docstring and `@beta_tool`, add it to that module's `TOOLS`), then a handler in `LocalBrain.py`
with `@intent(r"^pattern$")` returning the sentence to speak (return `None` to let later patterns try). Put it before any broader pattern it could lose to. Add examples to
`tests/test_localbrain.py` (they use recorders: `self.routes("phrase", "tool_name", *args)`), a phrase file line in `training/nlu/` if loose wording should reach it, and, if people should know about it, a
quoted example in `MANUAL.md` section 5.2 (`tests/test_docs.py` checks every quoted example there still works).

**Add a setting.** See "Settings flow" above. The admin panel and the wizard's validation pick it up from the registry automatically; add a question in `jarvis_setup/questions.py` only if the wizard should ask it.

**Add an admin panel page or button.** Settings pages come from the registry groups (`GROUPS`); special pages are `_page_<id>` methods in `gui/admin_panel.py` listed in `PAGES`; extras at the top of a group page are
`_extras_<group>` methods. Test with the offscreen Qt pattern in `tests/test_admin_panel.py` (inject `confirm`/`tell`; patch `shortcuts.file`/`contacts.file`).

**Add a wizard step.** A class in `jarvis_setup/steps/*.py` with `check()` (is it already done? look at the real PC), `plan()` (what `--dry-run` shows), `run()`; list it in `steps/__init__.py` `all_steps()` in the right order;
ask questions through `ctx.console` with a key (so answers files and tests can answer them); do outside-world work only through `ctx.effects`; test it with `FakeEffects` in `tests/test_setup_steps.py`.
Steps whose `check()` means "the wizard finished me" use `self.done_before(ctx)` / `self.hand_made(ctx)`.

**Add a model/voice download.** `jarvis_setup/steps/install.py` `ModelsStep` (and the facts in `system.model_facts`); the real downloads are the project's own scripts (`stt.py --download`, `wakeword.py --download`, ...).

**Change what he says.** Replies are in `LocalBrain.py` handlers; write "sir" (the owner's `ADDRESS_AS` replaces it in `speech.py`).

## 7. Before you hand back

Run the whole suite (`python -m unittest discover -s tests`), run `python settings_registry.py --check`, run a before/after listing of the real `DataBase/` if you touched anything that writes, update section 2 of this file,
`ROADMAP.md` and (if users see it) `MANUAL.md`, tell the owner in plain language what changed and how to try it, and **stop** unless they gave you more to do. Do not commit unless asked.
