# New Jarvis: the project, how it works, and how to carry on

For a Claude session (or a programmer) who must understand the whole thing before changing it. `CLAUDE.md` is the short version and holds the
rules; read it first. This guide explains the parts, how they fit, why they are the way they are, and how to extend them.
Every Python file of the project is named here (a test, `tests/test_docs.py`, fails if a new file is not).

## 1. What it is

A voice assistant for Windows, written in Python 3.14, for one owner. They talk or type; a password stands in front of everything;
commands run through a free local brain (patterns, then a model trained on this PC), anything else goes to a chat model on this PC (Ollama).
Hearing (Whisper), speaking (Piper), the wake word, claps and "only my voice" all run offline. Nothing needs a paid service.
Anthropic's Claude is an optional extra brain (`ANTHROPIC_API_KEY`).

## 2. The big picture

```
 ways in            Startup.py (terminal)  |  JarvisGUI.py (window)  |  Start-Jarvis.bat / desktop shortcut / start with Windows
                              \                    |
 waking (asleep)       listener.py: wakeword.py ("hey Jarvis") + clap.py, in the background, + the START button
                                                   v
 the gate                    gate.py: password (salted PBKDF2 hash) then an optional camera glance (never blocks)
                                                   v
 one session                 MainCode.taskExe -> greeting -> loop { listen() -> handle_command() }
                                                   v
 hearing                     microphone.py (sounddevice | winmm_mic.py) -> stt.py Whisper (Google as 2nd opinion) -> speaker.py voice lock
                                                   v
 understanding               LocalBrain.LocalReply  (patterns, Frames, repair, NLU)   then   ChatBrain (Ollama)   then   FreeBrain / "did you mean"
                                                   v
 doing                       JarvisAdvancedBot/tools/*  (one function per ability; the same ones serve the Claude brain)
                                                   v
 speaking                    speech.Speak -> personal.address ("sir" -> ADDRESS_AS) -> tts_piper (Piper) | Windows SAPI; also shown in the window and recorded by transcript.py
```

Two threads matter in the window: the **Qt thread** (everything visible) and the **session thread** (`gui/session.py`: runs `MainCode.taskExe`, speaks, listens). They talk only through
Qt signals and `queue.Queue`; the session thread asks the window for things (like opening the admin panel) through `ui_bridge.py`.

## 3. A command's life, step by step

1. **Waking.** While asleep the window arms `WakeController` (`gui/session.py`) -> `listener.WakeListener` opens the microphone and feeds `wakeword.WakeWordDetector` and `clap.ClapDetector` (about 6 percent of one core). Either one acts like START.
2. **Password.** `LoginDialog` (window) or `Startup.authenticate` (terminal) call `gate.check_password`; then `gate.face_check` if `FACE_CHECK`.
3. **Session.** `MainCode._run_session` warms the models in the background (`_prewarm`), greets (`STARTUP_GREETING`), then loops.
4. **Listening.** `microphone.listen_voice` records one phrase (adaptive noise floor, a pause of `MIC_PAUSE` ends it, joins a sentence that stopped mid-way, ignores his own voice), `stt.transcribe`
   (Whisper `base.en` about 2 s per command on the owner's CPU; Google only if Whisper heard nothing), then `speaker.accept` (voice lock) decides if the voice is the owner's.
5. **Routing, `MainCode._handle_one`:** stop/sleep words; if Claude is on, Claude; "new chat"; then `LocalBrain.LocalReply`; a cut-off fragment gets "only caught part of that";
   guards for editing data, deleting files and personal data questions (they never go to the chat model); then `_chat` (Ollama, streaming sentence by sentence via `speech.SpeakStream`); then `_answer_anything` (`FreeBrain` key/web answer, then "did you mean").
6. **`LocalReply`**, in order: `normalize` (drops "jarvis", lead-ins like "ok could you please", trailing "please/sir") -> `_canonical` (bare words) -> **shortcuts** (`_by_shortcut`, the owner's own names win) -> numerals ("fifteen percent") ->
   `Frames` (a request about tasks/notes understood by its parts) -> "another" -> the `-ing` form (`imperative`) -> the first matching **`@intent`** in `INTENTS` -> `_by_frame` -> `_by_repair` (typos in command words) -> `_by_the_language_model`
   (`NLU.interpret`, only when sure; risky commands are confirmed first).
7. **Tools.** A handler calls tools in `JarvisAdvancedBot/tools/` (each returns a sentence or raises `ToolError`, whose message is spoken as it is).
8. **Speaking.** `speech.Speak` shows the text, tells listeners (the window's chat, the transcript), then speaks with Piper (prefetching the next sentence) or the Windows voice.
9. **Record.** `transcript.record` writes `Logs/conversations/<day>.jsonl` (`LOG_CONVERSATIONS`, kept `CONVERSATION_LOG_DAYS` days).

## 4. File reference

### The ways in and the core

| File | What it is |
|---|---|
| `Startup.py` | Terminal launcher: wake word, password, camera check, then `MainCode.taskExe`. Needs a real console. |
| `JarvisGUI.py` | Window launcher (`gui.main_window.main`). |
| `JarvisAdmin.py` | The admin panel on its own (`gui.admin_panel.open_admin`), so a bad setting can always be fixed. |
| `setup_jarvis.py` | The setup wizard entry (checks the Python version, then `jarvis_setup.cli.main`). |
| `Setup-Jarvis.bat`, `Start-Jarvis.bat`, `Admin-Panel.bat` | Double-click launchers. They find Python with `jarvis_setup/find_python.cmd`, offer to install it with `jarvis_setup/install_python.ps1` if there is none. |
| `config.py` | Reads `.env` (python-dotenv, `interpolate=False`) into constants. The only place that reads settings. Helpers `key`, `number`, `decimal`, `flag`. |
| `settings_registry.py` | The master list of the 56 settings: label, plain help, kind, range, default, group, advanced/hidden flags, `validate()`; writes `.env.example` and the MANUAL's settings table. |
| `envfile.py` | Safe `.env` editor (`EnvFile`): keeps comments and unknown keys, atomic write, ten `.env.bak-*` copies, quoting that python-dotenv reads back exactly; `mask()` for secrets. |
| `personal.py` | `address(text)`: swaps "sir" for `ADDRESS_AS` in everything he says (leaves "Sir Isaac Newton" alone). |
| `gate.py` | The one authority on "may this person in": PBKDF2 hash (600,000 rounds), `check_password`, `store_password` (through `envfile`), `face_check`; `python gate.py --set-password`. |
| `MainCode.py` | One session (greeting, command loop, routing, start-up prewarm). Cannot be run alone, so it cannot skip the gate. |
| `transcript.py` | The private conversation record and `python transcript.py` to read it. |
| `calc.py`, `rates.py`, `units.py` | Safe arithmetic (no `eval`), exchange rates (open.er-api.com), offline unit conversion. |
| `sound_player.py` | MP3/WAV playback with pygame (reminder sounds, theme music). |

### Voice

| File | What it is |
|---|---|
| `speech.py` | The one place he speaks: Piper first, Windows SAPI as fallback, text always shown; `Speak`, `Show`, `SpeakStream`, listeners, `check()` (`python speech.py`). |
| `tts_piper.py` | The natural voice (Piper, models in `models/piper`); synthesis cache and prefetch. Tests must never import the real piper. |
| `microphone.py` | Capture backends, level/noise handling, `listen`, `listen_voice`, `diagnose` (`python microphone.py`), Windows privacy switches. |
| `winmm_mic.py` | Dependency-free capture through `winmm.dll` (ctypes); the backup backend; also lists microphones for the wizard. |
| `audio_levels.py` | Windows microphone/speaker volume and mute through Core Audio (PowerShell); `python audio_levels.py --mic 80`. |
| `stt.py` | Whisper (faster-whisper) in `models/whisper`; vocabulary hint, runaway guard, `python stt.py --download`. |
| `speaker.py`, `enroll_voice.py` | Voice lock: a TitaNet voice print (`DataBase/voiceprint.npz`), `accept()`, `python enroll_voice.py [--test|--status|--delete]`. |
| `wakeword.py` | openWakeWord "hey Jarvis" detector (`models/wakeword`). |
| `clap.py` | Clap pattern detector (shape, fade, pitch, quiet between); `python clap.py --live`. |
| `listener.py` | `WakeListener`: the always-on ear that combines wake word and claps and reports why it cannot listen. |
| `native_libs.py` | Loads onnxruntime/sherpa/faster-whisper before PyQt5 (the crash rule). |
| `voice_test.py` | Records ten sentences and compares Whisper, Google, speed and the voice lock. |

### The brains and tools (`JarvisAdvancedBot/`)

| File | What it is |
|---|---|
| `LocalBrain.py` | The command brain: `INTENTS` (first match wins), `normalize`, `LocalReply`, `split_commands` ("then"), `is_command`, `suggest`, shortcuts and the admin-panel intent. Replies say "sir". |
| `Frames.py` | Reads a to-do/note request by action + thing + which one + text ("remove the third task I am done"); `buy_not_by`, `tidy_task`. |
| `NLU.py` | His own trained model (`models/nlu.joblib`): `interpret()` maps loosely worded sentences to a command family; `training/` makes it. |
| `ChatBrain.py` | Chat over Ollama: model choice by free RAM, streaming sentences, conversation memory, facts file `DataBase/memory.json`, web grounding. |
| `FreeBrain.py` | A free online key (Groq/Gemini/OpenRouter...) or a web answer when Ollama is not available. |
| `JarvisAiBrain.py` | The Claude brain: the same tools chosen by Claude (only when `ANTHROPIC_API_KEY` is set). |
| `tools/__init__.py` | `TOOLS` (64 tools) and the names `LocalBrain` calls. |
| `tools/_common.py` | Shared helpers: `DB` (the database folder; tests point it at a temp folder), `folder()`, text helpers, `ToolError` use. |
| `tools/info.py`, `productivity.py`, `space.py`, `web.py`, `windows.py`, `world.py` | The abilities: time/weather/money/system; notes, tasks, reminders, time table, books, translation; NASA/ISS/SpaceX; websites/search/YouTube/media keys; apps, folders, screenshots, power, keyboard shortcuts; fun facts, health numbers, mail, Wi-Fi, downloads. |

### The window (`gui/`)

| File | What it is |
|---|---|
| `__init__.py` | Calls `native_libs.preload()` before anything imports PyQt5. |
| `main_window.py` | `MainWindow`: three columns, ADMIN button, `admin_requested` signal (from `ui_bridge`), `restart_jarvis`. |
| `session.py` | `SessionController` (the session thread -> signals) and `WakeController` (wake word/claps -> "woke"). |
| `login_dialog.py` | The unlock dialog (password, optional camera). |
| `theme.py` | Colours and the one stylesheet used by every Qt window (including the admin panel). |
| `sprites.py`, `make_assets.py` | The animated ring/earth/hero pictures from sprite sheets in `gui/resources/`. The original GIF artwork is not in the repo: it is in `Documents\Jarvis Personal Archive\GUI Material\Original window artwork` (see its README). |
| `admin_panel.py` | The admin panel (section 8). `admin_widgets.py`: `SettingRow`, `PasswordPrompt`, `ChangePasswordDialog`, `ItemDialog`, `run_in_console`. |
| `utils/calculator.py`, `calendar_view.py`, `currency_converter.py`, `style.py`, `launcher.py` | The small CustomTkinter tool windows and what opens them as separate programs. |

### The owner's data and personalisation

| File | What it is |
|---|---|
| `shortcuts.py` | Spoken shortcuts (`DataBase/shortcuts.json`): website/folder/file/program; loose name matching; `check`, `find`, `open_it`. |
| `contacts.py` | Contacts (`DataBase/contacts.json`) so "send an email" accepts a name. |
| `ui_bridge.py` | `register(name, handler)` / `request(name)`: the session thread asks the window to do something. |
| `backup_jarvis.py` | `make_backup`, `verify_backup`, `find_backups`, `plan_restore`, `restore` (replaced files go to `Backups/`), `inventory`; understands our `Jarvis-Backup-*` folders and whole-folder copies. |
| `DataBase/FaceDetectionModule/FaceRecognition.py`, `SampleGenerator.py`, `ModelTrainer.py` | The optional camera check, its photo tool and its trainer (OpenCV 4). |

### The setup wizard (`jarvis_setup/`, standard library only)

| File | What it is |
|---|---|
| `cli.py` | Arguments (`--check`, `--dry-run`, `--yes`, `--custom`, `--only`, `--skip`, `--mode`, `--restore-from`, `--answers`, `--set`, `--project`...). |
| `runner.py` | `Runner`: welcome (mode and style), the plan, each step (`check` -> `run` -> record -> re-check), `check_only`, the summary. Decides a step applies **when its turn comes**. |
| `console.py` | Output and questions with keys (`ask`, `confirm`, `choose`, `choose_many`, `secret`); scripted answers; never logs a secret; ASCII markers. |
| `context.py` | `Context` (root, console, effects, `.env`, facts, choices, `save_settings`, `run_python`) and `State` (`DataBase/setup_state.json`). |
| `effects.py` | Everything that touches the outside world: `run`, `run_visible`, `powershell`, `signature`, `fetch` (resumes, checks size), `http_json`, `reachable`, `start_detached`. Tests replace it. |
| `system.py` | Probes (Windows, Python, memory, disk, internet, sound devices, VC++ runtime, Ollama, packages, models), `PACKAGES`, `hardware_tier`. |
| `questions.py` | The questions (about you, brain, privacy, email, Windows; voice and hearing) with recommended answers. |
| `windows.py` | Shortcuts (desktop, start-up), `run_elevated` (UAC) for installers. |
| `steps/` | `base.py` (Step), `machine.py` (system, runtime), `data.py` (restore, profile), `install.py` (packages, models, Ollama), `personal.py` (voice, password, identity, language model, Windows), `finish.py` (self-check). `__init__.py` lists them in order. |
| `find_python.cmd`, `install_python.ps1` | Used by the `.bat` launchers (no Python yet). |

### Training and tests

| File | What it is |
|---|---|
| `training/nlu_phrases.py`, `train_nlu.py`, `speedtest_models.py`, `training/nlu/*.txt` | The phrase bank, the trainer (`python training/train_nlu.py [--report|--try]`), a timer for installed Ollama models. |
| `tests/` | About 1,500 offline tests. `isolation.py`, `setup_support.py`, `tools_support.py` are the fixtures. `live_check.py` asks real services. |

## 5. The setup wizard in detail

**Modes** (`Runner.welcome`): `fresh`, `restore`, `repair` (default `repair` when a `.env` exists), and `reset` ("start completely fresh": `backup_jarvis.start_over` copies the owner's data into `Backups/`, verifies the copy by SHA-256,
only then clears it, forgets the wizard's notebook and continues as `fresh`; it is never done without the typed answer `start_over=yes`, so `--yes` alone cannot clear anything). **Style:** express (a handful of questions, recommended answers) or custom (everything).
**Steps in order:** system, restore (restore mode only), profile, runtime, packages, models, ollama (if wanted), voice, password, identity (optional lessons), language_model, windows (if chosen), selfcheck.

* Each step's `check()` looks at the real PC, so a second run only does what is missing; `run()` returns `Outcome(state, detail)`; the runner records it in `DataBase/setup_state.json` *before* re-checking, then double-checks that the PC agrees.
* Steps that ask preferences count as done when the wizard recorded them, or for a **hand-made** install (a `.env` exists and the wizard has never run here: `Step.hand_made`).
* The answers are keyed (`USER_NAME`, `wake_method`, `install_ollama`, `enroll_voice`...), so `--answers file.json`, `--set KEY=VALUE` and the tests can answer every question.
* `--dry-run` prints each step's `plan()` (or "already done"); nothing is written, run or downloaded (`save_settings` and `run_python` honour it).
* Safety: installers are run only after a signature check (`effects.signature`): VC++ must be signed by Microsoft; Ollama must have a valid signature (an unexpected signer is asked about); Python by the PSF (in `install_python.ps1`).
  Administrator rights are only requested for the VC++ installer (`windows.run_elevated`, Windows shows its own question).
* `ModelsStep` downloads through the project's own scripts (`python -m piper.download_voices`, `stt.py --download` with `STT_MODEL` in the environment, `wakeword.py --download`, `speaker.py --download`) and then checks the files exist.
* `RestoreStep` uses `backup_jarvis` (find, plan, restore with a conflict policy; Ollama models saved beside a whole-folder backup are copied back additively).
* Hardware tier (`system.hardware_tier`): "light" (<= 9.5 GB RAM or <= 2 cores): `base.en`, `qwen2.5:1.5b`, `CHAT_AUTO_MAX_MB=1600`; "balanced"; "strong" (>= 15 GB and >= 6 cores): `small.en`, `llama3.2:3b`, preload.

## 6. The admin panel in detail

`gui/admin_panel.AdminPanel(parent, root, effects, restart, confirm, tell)` is a `QDialog`. Pages come from `PAGES`: Overview, one page per registry group (rows built by `_settings_page` from `settings_registry`), Your shortcuts, Your contacts, Backup and restore, Advanced.
`SettingRow` picks the control by `Setting.kind` (checkbox, spin boxes with ranges, strict combo, editable combo with suggestions from `options_from`: installed Piper voices, microphones, Ollama models; password-style box for secrets) and validates with `registry.validate`.
Save writes only changed rows through `EnvFile.set_many` after a confirmation that masks secrets; lists (shortcuts, contacts) and the Advanced page save at once. The health table runs the wizard's own `check()` methods on a worker thread.
`open_admin()` asks for the password with `PasswordPrompt` (skipped when no password exists yet). A voice command reaches the window through `ui_bridge.request("admin")` (the terminal version starts `JarvisAdmin.py` instead).
Changing the password updates the in-memory `config.JARVIS_PASSWORD_HASH` too, so it works at once. Tests inject `confirm`/`tell` and patch `shortcuts.file`/`contacts.file`.

## 7. Settings and data

* `.env` (git-ignored) holds the settings; `settings_registry.py` describes them; `config.py` reads them; `envfile.py` edits them. `ADDRESS_AS` (default `sir`) personalises replies.
* Personal data, all git-ignored: `.env`, `DataBase/Notes|Tasks|TimeTable|memory.json|shortcuts.json|contacts.json|voiceprint.npz|setup_state.json`, `DataBase/FaceDetectionModule/samples|trainer`, `Logs/`, `models/`, `Backups/`, `training/nlu_real.txt`, `training/reports/`.
* Backups: `backup_jarvis.PARTS` lists what counts as personal data (a test-friendly single list). GitHub holds the code only.

## 8. Testing

* `python -m unittest discover -s tests` (about 3 minutes, offline). The suite never uses the microphone, speakers, network, camera, e-mail, the real DataBase or `.env`.
* Isolation: see `CLAUDE.md` section 5. The wizard is tested against a pretend PC (`tests/setup_support.py`): `FakeEffects` records programs and downloads; `World` fakes the probes and the shortcut functions; `pretend_downloads` makes the "downloaded" files appear.
* Real-world checks that tests cannot do: `python setup_jarvis.py --check` and `--dry-run` on the real PC; the launcher scripts are tested in a folder named like the owner's (`Rohaan & Co's folder`) with real `cmd`.
* After adding a test module, run it alone and compare the real `DataBase/` before and after (the probe that found the old "buy milk" leak): `tests/isolation.py` exists because of such leaks.

## 9. Extending, with the details

See `CLAUDE.md` section 6 for the recipes. A few specifics:

* **A new tool** must raise `ToolError("a sentence he can say")` for expected failures; return a short sentence otherwise; never print secrets; add it to `TOOLS`; tests replace tools with recorders by name (`T.TOOLS`).
* **A new intent's regex** runs on the normalized lower-case text (no "jarvis", no lead-ins). Use `ask(question)` for follow-ups; `_confirmed(ask, question)` for yes/no (silence is no).
* **A new setting kind** (rare): add the kind to `settings_registry.validate`, `Setting` docs, `SettingRow._make_editor/value/set_value`.
* **A new data part for backups**: add it to `backup_jarvis.PARTS` (and `.gitignore`); the wizard's restore and the admin panel's backup page pick it up.
* **A new launcher script**: CRLF line endings, quote every path, never echo `%VAR%` unquoted (tests check this).

## 10. Why it is the way it is

* **Free and local first** because the owner has no paid keys and a slow PC: Piper and Whisper instead of cloud voices, Ollama instead of an API, openWakeWord instead of a service. Every part falls back to the older way (Google hearing, the Windows voice, the START button) and says so.
* **No PyAudio** (no Python 3.14 wheel): sounddevice, with a pure-ctypes winmm backend as the guaranteed fallback.
* **127.0.0.1, not localhost**: on this Windows "localhost" waits two seconds for IPv6 to fail on every Ollama request.
* **The wizard is standard-library only** and talks to the world through `effects.py`: it must run on a PC with nothing installed, and be testable without installing anything.
* **One list of settings** so the example file, the manual, the admin panel and the wizard cannot disagree; tests compare it with `config.py`.
* **`interpolate=False`** so a password containing `${...}` is read as typed.
* **Plain-language messages**: the owner is not a programmer; failures say what to do (the exact command), not a stack trace (that goes to the log).
* **Applicability decided late in the runner**: a user who says "no chat model" must not get an Ollama install because the plan was drawn before they answered.
* **Decisions the owner made:** stop after each phase; backups into new folders; the code on a private GitHub repo and everything else on their own HDD; unencrypted backups are acceptable if kept private.

## 11. Known limits and ideas

* Loopback tests cannot prove hearing, the wake word or claps (the Realtek driver suppresses speakers-to-microphone): only the owner's voice and hands can (see `CLAUDE.md` section 2).
* The wizard's installers (VC++, Python packages, Ollama) were exercised with pretend effects, a dry run on the real PC and downloads against a local server; the first real run on a bare Windows 11 Lite is the live test.
* The wake word is fixed to "hey Jarvis" (a different phrase needs a trained model). The chat models are small: they invent facts, hence the web grounding.
* Ideas in `ROADMAP.md`: proactive briefings, memory that learns the owner, phone/remote control, screen understanding, agent mode, own models, and the owner's undescribed "most advanced idea" (Phase I).
