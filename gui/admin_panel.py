"""The admin panel: change every setting Jarvis has, make your own shortcuts and contacts, back up and restore, and see what needs attention.

Open it with the ADMIN button in the Jarvis window, by saying "open the admin panel", or on its own with Admin-Panel.bat. It asks for the
Jarvis password first. The pages are made from settings_registry.py (the one list of settings), so a new setting shows up here without
anyone drawing a control for it.

* Settings are changed in the boxes and written to .env when you press SAVE (a copy of the old .env is kept, so "Undo the last save"
  on the Advanced page can bring it back). Most settings take effect the next time Jarvis starts; SAVE AND RESTART does that for you.
* Shortcuts and contacts are your own lists. They are saved the moment you add, change or remove one.
"""
import os
import subprocess
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

import backup_jarvis
import config
import contacts
import gate
import settings_registry as registry
import shortcuts
from envfile import EnvFile, mask
from gui import theme
from gui.admin_widgets import (ChangePasswordDialog, PasswordPrompt, SettingRow, ask_yes, edit_contact, edit_shortcut, normalized, run_in_console, say)
from jarvis_setup import system, windows
from jarvis_setup.effects import Effects
from jarvis_setup.questions import SAMPLE_SENTENCE, friendly_voice

PAGES = [("overview", "Overview")] + [(g.id, g.title) for g in registry.GROUPS] + [
    ("shortcuts", "Your shortcuts"), ("contacts", "Your contacts"), ("backup", "Backup and restore"), ("advanced", "Advanced")]


def heading(text):
    label = QLabel(text.upper())
    label.setObjectName("heading")
    return label


def muted(text):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


def button(text, call, name="", tip=""):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    b.clicked.connect(lambda _checked=False: call())
    return b


class AdminPanel(QDialog):
    health_ready = pyqtSignal(list)
    backup_done = pyqtSignal(str, bool)

    def __init__(self, parent=None, root=None, effects=None, restart=None, confirm=None, tell=None):
        super().__init__(parent)
        self.root = Path(root or config.BASE_DIR)
        self.env = EnvFile(self.root / ".env")
        self.effects = effects or Effects()
        self.restart_callback = restart                # None when opened on its own: there is no running Jarvis to restart
        self.confirm = confirm or (lambda title, text, detail="": ask_yes(self, title, text, detail))
        self.tell = tell or (lambda title, text, detail="": say(self, title, text, detail))
        self.rows = {}
        self.nav_pages = {}
        self.show_advanced = False
        self.setWindowTitle("Jarvis admin panel")
        self.resize(1040, 720)
        self.setMinimumSize(900, 600)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search settings")
        self.nav = QListWidget()
        self.nav.setFixedWidth(230)
        self.stack = QStackedWidget()
        self.advanced_box = QCheckBox("Show advanced settings")
        side = QVBoxLayout()
        side.addWidget(self.search)
        side.addWidget(self.nav, 1)
        side.addWidget(self.advanced_box)
        body = QHBoxLayout()
        body.addLayout(side)
        body.addWidget(self.stack, 1)

        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("muted")
        self.revert_button = button("Revert", self.revert, tip="Put every box back to what is saved")
        self.save_button = button("SAVE", self.save, "primary")
        self.restart_button = button("Save and restart Jarvis", self.save_and_restart, tip="Save, then close Jarvis and open him again")
        self.restart_button.setVisible(restart is not None)
        close_button = button("Close", self.close_panel)
        bottom = QHBoxLayout()
        bottom.addWidget(self.dirty_label, 1)
        bottom.addWidget(self.revert_button)
        bottom.addWidget(self.restart_button)
        bottom.addWidget(self.save_button)
        bottom.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(body, 1)
        layout.addLayout(bottom)

        self._build_pages()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.search.textChanged.connect(self.apply_filter)
        self.advanced_box.toggled.connect(self._advanced_toggled)
        self.health_ready.connect(self._show_health)
        self.backup_done.connect(self._backup_finished)
        self.nav.setCurrentRow(0)
        self.apply_filter()                              # (hides the advanced settings until they are asked for)
        self._update_dirty()

    # ---- building the pages

    def _build_pages(self):
        values = registry.effective(self.env.values())
        for page_id, title in PAGES:
            item = QListWidgetItem(title)
            self.nav.addItem(item)
            if page_id in registry.GROUP_BY_ID:
                widget = self._settings_page(registry.GROUP_BY_ID[page_id], values)
            else:
                widget = getattr(self, f"_page_{page_id}")()
            self.stack.addWidget(widget)
            self.nav_pages[page_id] = (item, widget)

    def _settings_page(self, group, values):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(heading(group.title))
        layout.addWidget(muted(group.blurb))
        extras = getattr(self, f"_extras_{group.id}", None)
        if extras is not None:
            layout.addWidget(extras())
        for setting in registry.settings_in(group.id):
            row = SettingRow(setting, values[setting.key][0], options=self._options_for(setting))
            row.changed.connect(self._update_dirty)
            self.rows[setting.key] = row
            layout.addWidget(row)
        empty = muted("No setting here matches your search.")
        empty.hide()
        layout.addWidget(empty)
        layout.addStretch(1)
        page.empty_label = empty
        return scroll(page)

    def _options_for(self, setting):
        if setting.options_from == "piper_voices":
            return [name for name in self._piper_voices()]
        if setting.options_from == "mic_devices":
            return [""] + system.audio_facts(self.root)["microphones"]
        if setting.options_from == "ollama_models":
            found = self.effects.http_json(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=1.5) or {}
            return [m.get("name", "") for m in found.get("models", []) if m.get("name")]
        if setting.options_from == "windows_voices":
            return ["", "Zira", "David", "Mark", "Hazel", "Heera", "Ravi"]
        return []

    def _piper_voices(self):
        folder = self.root / "models" / "piper"
        return sorted(p.stem for p in folder.glob("*.onnx") if p.with_name(p.name + ".json").exists()) if folder.is_dir() else []

    # ---- extras at the top of some settings pages

    def _extras_speaking(self):
        box = QFrame()
        box.setObjectName("panel")
        layout = QHBoxLayout(box)
        voices = self._piper_voices()
        layout.addWidget(muted("Natural voices installed: " + (", ".join(friendly_voice(v) for v in voices) or "none yet (the setup wizard downloads them)")), 1)
        layout.addWidget(button("Hear the chosen voice", self.hear_voice, tip="Jarvis says a sentence with the voice shown in the box below"))
        layout.addWidget(button("Add more voices...", self.add_voice, tip="Opens a window that downloads another natural voice"))
        return box

    def _extras_hearing(self):
        box = QFrame()
        box.setObjectName("panel")
        layout = QHBoxLayout(box)
        layout.addWidget(muted("Microphones found: " + ("; ".join(system.audio_facts(self.root)["microphones"]) or "none")), 1)
        layout.addWidget(button("Test the microphone", lambda: run_in_console(self.root, ["microphone.py", "--no-speech"]),
                                tip="Opens a window that checks Windows' settings, the device and the recording"))
        return box

    def _extras_waking(self):
        box = QFrame()
        box.setObjectName("panel")
        layout = QVBoxLayout(box)
        self.security_note = muted("")
        layout.addWidget(self.security_note)
        row = QHBoxLayout()
        row.addWidget(button("Change password...", self.change_password))
        row.addWidget(button("Teach him my voice...", lambda: run_in_console(self.root, ["enroll_voice.py"]), tip="You read 16 sentences (about 3 minutes)"))
        row.addWidget(button("Test my voice...", lambda: run_in_console(self.root, ["enroll_voice.py", "--test"])))
        row.addWidget(button("Teach him my face...", self.teach_face, tip="The camera takes about 30 photos while you slowly turn your head"))
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh_security_note()
        return box

    def _extras_brain(self):
        box = QFrame()
        box.setObjectName("panel")
        layout = QHBoxLayout(box)
        self.ollama_note = muted("Looking for Ollama...")
        layout.addWidget(self.ollama_note, 1)
        layout.addWidget(button("Download a model...", self.pull_model, tip="Asks for a model name (for example qwen2.5:1.5b) and downloads it with Ollama"))
        QTimer.singleShot(0, self.refresh_ollama_note)
        return box

    def _extras_window(self):
        box = QFrame()
        box.setObjectName("panel")
        layout = QHBoxLayout(box)
        self.startup_box = QCheckBox("Open Jarvis when I log in to Windows")
        self.startup_box.setChecked(windows.starts_with_windows())
        self.startup_box.toggled.connect(self.toggle_startup)
        layout.addWidget(self.startup_box, 1)
        layout.addWidget(button("Put a shortcut on the desktop", self.desktop_shortcut))
        return box

    def refresh_security_note(self):
        values = self.env.values()
        if values.get("JARVIS_PASSWORD_HASH"):
            password = "Password: set (stored scrambled)."
        elif values.get("JARVIS_PASSWORD"):
            password = "Password: set, but stored as readable text. Press Change password to scramble it."
        else:
            password = "Password: NOT SET - Jarvis lets nobody in until you set one."
        facts = system.project_facts(self.root)
        self.security_note.setText(f"{password}   Voice print: {'yes' if facts['voiceprint'] else 'not taught yet'}.   "
                                   f"Face model: {'yes' if facts['face_model'] else 'not taught yet'}.")

    def refresh_ollama_note(self):
        found = system.ollama_facts(self.effects, config.OLLAMA_URL)
        if found["running"]:
            self.ollama_note.setText("Ollama is running. Models: " + (", ".join(found["models"]) or "none yet - download one."))
        elif found["installed"]:
            self.ollama_note.setText("Ollama is installed but not running. Open it from the Start menu.")
        else:
            self.ollama_note.setText("Ollama is not installed. Run the setup wizard (Setup-Jarvis.bat) to add the chat model.")

    # ---- the buttons on those pages

    def hear_voice(self):
        row = self.rows.get("PIPER_VOICE")
        name = row.value() if row else config.PIPER_VOICE
        try:
            subprocess.Popen([sys.executable, str(self.root / "tts_piper.py"), SAMPLE_SENTENCE], cwd=str(self.root), env={**os.environ, "PIPER_VOICE": name},
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            self.tell("Voice", f"I could not play the voice: {error}")

    def add_voice(self):
        name, ok = QInputDialog.getText(self, "Add a voice", "Name of the voice to download, for example en_US-amy-medium or en_GB-jenny_dioco-medium:")
        if ok and name.strip():
            run_in_console(self.root, ["-m", "piper.download_voices", name.strip(), "--download-dir", "models/piper"])

    def teach_face(self):
        code = ("import subprocess, sys; "
                "a = subprocess.call([sys.executable, 'DataBase/FaceDetectionModule/SampleGenerator.py']); "
                "a == 0 and subprocess.call([sys.executable, 'DataBase/FaceDetectionModule/ModelTrainer.py'])")
        run_in_console(self.root, ["-c", code])

    def pull_model(self):
        name, ok = QInputDialog.getText(self, "Download a chat model", "Model name, for example qwen2.5:1.5b (quick) or llama3.2:3b (better, slower):")
        exe = system.ollama_executable()
        if ok and name.strip() and exe:
            run_in_console(self.root, ["-c", f"import subprocess; subprocess.call([{exe!r}, 'pull', {name.strip()!r}])"])
        elif ok and not exe:
            self.tell("Ollama", "Ollama is not installed. Run Setup-Jarvis.bat to add it.")

    def change_password(self):
        dialog = ChangePasswordDialog(self, env_path=self.env.path, require_current=bool(gate.password_configured()))
        if dialog.exec_() == QDialog.Accepted:
            self.refresh_security_note()
            self.reload_from_env()
            self.tell("Password", "The password is changed. It works straight away.")

    def toggle_startup(self, on):
        try:
            windows.set_start_with_windows(self.effects, self.root, on)
        except Exception as error:                            # noqa: BLE001
            self.tell("Start-up", f"Could not change that: {error}")
            self.startup_box.blockSignals(True)
            self.startup_box.setChecked(windows.starts_with_windows())
            self.startup_box.blockSignals(False)

    def desktop_shortcut(self):
        try:
            windows.desktop_shortcut(self.effects, self.root, True)
            self.tell("Desktop", "The Jarvis shortcut is on the desktop.")
        except Exception as error:                            # noqa: BLE001
            self.tell("Desktop", f"Could not make the shortcut: {error}")

    # ---- Overview

    def _page_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 12, 12)
        layout.addWidget(heading("Overview"))
        layout.addWidget(muted("A look at how Jarvis is doing, and shortcuts to the things you will want most."))
        self.facts_label = QLabel("")
        self.facts_label.setWordWrap(True)
        layout.addWidget(self.facts_label)
        self.problems_label = QLabel("")
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet(f"color: {theme.WARN};")
        layout.addWidget(self.problems_label)
        layout.addWidget(heading("Health"))
        self.health_table = QTableWidget(0, 3)
        self.health_table.setHorizontalHeaderLabels(["", "What", "State"])
        self.health_table.horizontalHeader().setStretchLastSection(True)
        self.health_table.setColumnWidth(0, 60)
        self.health_table.setColumnWidth(1, 330)
        self.health_table.verticalHeader().hide()
        self.health_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.health_table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.health_table, 1)
        row = QHBoxLayout()
        self.check_button = button("Check again", self.run_health)
        row.addWidget(self.check_button)
        row.addWidget(button("Run the setup wizard", lambda: run_in_console(self.root, ["setup_jarvis.py"]), tip="Fixes whatever is missing; asks before doing anything"))
        row.addWidget(button("Start over (brand new)...", self.start_over, "danger", "Saves a checked copy of your settings, notes, voice print... then clears them and sets Jarvis up as new"))
        row.addWidget(button("Open the manual", lambda: self._open(self.root / "MANUAL.md")))
        row.addWidget(button("Open the log folder", lambda: self._open(self.root / "Logs")))
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh_overview()
        QTimer.singleShot(50, self.run_health)
        return page

    def start_over(self):
        text = ("This opens a window that first saves a copy of your settings, password, notes, to-do lists, voice print, face model, shortcuts and conversation records "
                "into the Backups folder and checks it, then clears them and sets Jarvis up as if he were brand new. Your books, screenshots and models stay. Continue?")
        if self.confirm("Start over", text):
            run_in_console(self.root, ["setup_jarvis.py", "--mode", "reset"])

    def _open(self, path):
        try:
            os.startfile(str(path))
        except OSError as error:
            self.tell("Open", f"Could not open {path}: {error}")

    def refresh_overview(self):
        values = self.env.values()
        python = system.python_facts()
        changed = sum(1 for key, (value, is_default) in registry.effective(values).items() if not is_default)
        self.facts_label.setText(f"Jarvis folder: {self.root}\nPython {python['text']}    Settings file: {self.env.path.name} "
                                 f"({'found' if self.env.exists() else 'not made yet'}, {changed} settings differ from the usual)")
        issues = registry.problems(values)
        self.problems_label.setText("")
        if issues:
            self.problems_label.setText("Settings Jarvis would not understand: " + "; ".join(f"{k} ({m})" for k, m in issues) + ". Open the page they are on to correct them.")

    def run_health(self):
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking...")
        threading.Thread(target=self._health_worker, daemon=True).start()

    def _health_worker(self):
        """The same look-around the setup wizard makes (nothing is changed), done off the window's thread."""
        from jarvis_setup.console import Console
        from jarvis_setup.context import Context
        from jarvis_setup.steps import all_steps
        rows = []
        try:
            ctx = Context(self.root, Console(interactive=False, out=_Null()), self.effects, mode="repair")
            ctx.facts = system.gather(self.effects, self.root, self.env.values())
            for step in all_steps():
                if step.id in ("system", "selfcheck", "restore") or not step.applies(ctx):
                    continue
                check = step.check(ctx)
                rows.append((check.state, step.title, check.detail))
        except Exception as error:                            # noqa: BLE001 - the overview must open even if a look-around fails
            rows.append(("fail", "Looking around", f"{type(error).__name__}: {error}"))
        try:
            self.health_ready.emit(rows)
        except RuntimeError:
            pass                                              # the panel was closed while this was looking

    def _show_health(self, rows):
        marks = {"ok": ("OK", theme.GOOD), "warn": ("WARN", theme.WARN), "todo": ("TODO", theme.WARN), "fail": ("FAIL", theme.BAD), "skip": ("-", theme.MUTED)}
        self.health_table.setRowCount(len(rows))
        for number, (state, title, detail) in enumerate(rows):
            text, colour = marks.get(state, (state, theme.TEXT))
            mark = QTableWidgetItem(text)
            mark.setForeground(self._colour(colour))
            self.health_table.setItem(number, 0, mark)
            self.health_table.setItem(number, 1, QTableWidgetItem(title))
            self.health_table.setItem(number, 2, QTableWidgetItem(detail))
        self.check_button.setEnabled(True)
        self.check_button.setText("Check again")

    @staticmethod
    def _colour(name):
        from PyQt5.QtGui import QColor
        return QColor(name)

    # ---- Your shortcuts and contacts (saved the moment they change)

    def _page_shortcuts(self):
        return self._list_page("Your shortcuts", "Things you can open by name: \"open college portal\", \"open my project folder\". Saved the moment you change them.",
                               ["What you say", "It opens", "Where it goes", "State"], self._shortcut_rows, shortcuts.load, shortcuts.save,
                               edit_shortcut, self._test_shortcut, "shortcut")

    def _page_contacts(self):
        return self._list_page("Your contacts", "People you can name when you say \"send an email\". Saved the moment you change them.",
                               ["Name", "Email", "Phone", "Note"], self._contact_rows, contacts.load, contacts.save, edit_contact, None, "contact")

    def _list_page(self, title, blurb, columns, to_rows, load, save, edit, test, noun):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 12, 12)
        layout.addWidget(heading(title))
        layout.addWidget(muted(blurb))
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        for column, width in enumerate((170, 130, 280)):
            if column < len(columns) - 1:
                table.setColumnWidth(column, width)
        layout.addWidget(table, 1)

        def fill():
            items = load()
            table.setRowCount(len(items))
            for number, cells in enumerate(to_rows(items)):
                for column, text in enumerate(cells):
                    table.setItem(number, column, QTableWidgetItem(text))
            return items

        def chosen():
            row = table.currentRow()
            items = load()
            return (row, items) if 0 <= row < len(items) else (None, items)

        def add():
            new = edit(self)
            if new is None:
                return
            items = load()
            if any(i["name"].lower() == new["name"].lower() for i in items):
                self.tell("Already there", f"There is already a {noun} called {new['name']}. Edit that one instead.")
                return
            save(items + [new])
            fill()

        def change():
            row, items = chosen()
            if row is None:
                self.tell("Choose one", f"Click a {noun} in the list first.")
                return
            new = edit(self, items[row])
            if new is not None:
                items[row] = new
                save(items)
                fill()

        def remove():
            row, items = chosen()
            if row is None:
                self.tell("Choose one", f"Click a {noun} in the list first.")
                return
            if self.confirm("Remove", f"Remove the {noun} {items[row]['name']}?"):
                del items[row]
                save(items)
                fill()

        buttons = QHBoxLayout()
        buttons.addWidget(button(f"Add a {noun}...", add, "primary"))
        buttons.addWidget(button("Change...", change))
        buttons.addWidget(button("Remove", remove, "danger"))
        if test is not None:
            buttons.addWidget(button("Try it", lambda: test(chosen())))
        buttons.addStretch(1)
        layout.addLayout(buttons)
        table.doubleClicked.connect(lambda _index: change())
        fill()
        page.table, page.fill, page.add, page.change, page.remove = table, fill, add, change, remove
        return page

    @staticmethod
    def _shortcut_rows(items):
        return [(i["name"], shortcuts.KIND_LABELS.get(i["kind"], i["kind"]), i["target"], shortcuts.problems(i) or "ready") for i in items]

    @staticmethod
    def _contact_rows(items):
        return [(c["name"], c.get("email", ""), c.get("phone", ""), c.get("note", "")) for c in items]

    def _test_shortcut(self, picked):
        row, items = picked
        if row is None:
            self.tell("Choose one", "Click a shortcut in the list first.")
            return
        try:
            shortcuts.open_it(items[row])
        except Exception as error:                            # noqa: BLE001 - the message is for the person at the panel
            self.tell("That shortcut does not work", str(error))

    # ---- Backup and restore

    def _page_backup(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 12, 12)
        layout.addWidget(heading("Backup and restore"))
        layout.addWidget(muted("A backup is a plain folder (not encrypted) with your settings and password, notes, tasks, voice print, face model, shortcuts and "
                               "contacts. Keep it somewhere private, on another drive. Nothing is ever deleted when you restore."))
        self.backup_parts = {}
        box = QFrame()
        box.setObjectName("panel")
        form = QVBoxLayout(box)
        inventory = backup_jarvis.inventory(self.root)
        for part, (label, _, big) in backup_jarvis.PARTS.items():
            info = inventory.get(part)
            check = QCheckBox(f"{label}" + (f"  ({info['files']} files, {backup_jarvis.human(info['bytes'])})" if info else "  (nothing yet)"))
            check.setChecked(bool(info) and not big)
            check.setEnabled(bool(info))
            self.backup_parts[part] = check
            form.addWidget(check)
        layout.addWidget(box)
        row = QHBoxLayout()
        self.backup_target = QLineEdit()
        self.backup_target.setPlaceholderText("Folder to put the backup in, for example F:\\")
        row.addWidget(self.backup_target, 1)
        row.addWidget(button("Choose...", self._choose_backup_folder))
        self.backup_button = button("Back up now", self.back_up, "primary")
        row.addWidget(self.backup_button)
        layout.addLayout(row)
        self.backup_status = muted("")
        layout.addWidget(self.backup_status)
        layout.addWidget(heading("Bring one back"))
        self.found = QListWidget()
        self.found.setMaximumHeight(120)
        layout.addWidget(self.found)
        row = QHBoxLayout()
        row.addWidget(button("Look for backups on my drives", self.find_backups))
        row.addWidget(button("Restore the selected one...", self.restore_selected))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.found_backups = []
        return scroll(page)

    def _choose_backup_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should the backup go?", self.backup_target.text() or os.path.expanduser("~"))
        if folder:
            self.backup_target.setText(os.path.normpath(folder))

    def chosen_parts(self):
        return [part for part, check in self.backup_parts.items() if check.isChecked() and check.isEnabled()]

    def back_up(self):
        target = self.backup_target.text().strip()
        if not target or not Path(target).is_dir():
            self.tell("Back up", "Choose a folder that exists, for example the root of your backup drive.")
            return
        parts = self.chosen_parts()
        if not parts:
            self.tell("Back up", "Tick at least one thing to back up.")
            return
        self.backup_button.setEnabled(False)
        self.backup_status.setText("Backing up...")

        def work():
            try:
                folder = backup_jarvis.make_backup(target, root=self.root, parts=parts)
                problems = backup_jarvis.verify_backup(folder)
                self.backup_done.emit(f"Done: {folder}" + (f"  - but {len(problems)} files did not verify!" if problems else "  (every file checked)"), not problems)
            except Exception as error:                        # noqa: BLE001
                self.backup_done.emit(f"The backup failed: {error}", False)
        threading.Thread(target=self._guarded(work), daemon=True).start()

    @staticmethod
    def _guarded(work):
        def run():
            try:
                work()
            except RuntimeError:
                pass                                          # the panel was closed while the backup was running
        return run

    def _backup_finished(self, text, ok):
        self.backup_status.setText(text)
        self.backup_status.setStyleSheet(f"color: {theme.GOOD if ok else theme.BAD};")
        self.backup_button.setEnabled(True)

    def find_backups(self):
        self.found.clear()
        self.found_backups = backup_jarvis.find_backups()
        for item in self.found_backups:
            when = f"{item.created:%d %b %Y %H:%M}" if item.created else "date unknown"
            self.found.addItem(f"{item.label}  -  {when}  -  {item.path}")
        if not self.found_backups:
            self.found.addItem("No backup was found on the drives.")

    def restore_selected(self):
        row = self.found.currentRow()
        if row < 0 or row >= len(self.found_backups):
            self.tell("Restore", "Look for backups and click the one to restore first.")
            return
        backup = self.found_backups[row]
        base = backup_jarvis.source_folder(backup)
        parts = [p for p in backup_jarvis.inventory(source_files=base) if p != "models"]
        plan = backup_jarvis.plan_restore(backup, self.root, parts)
        text = f"Bring back {len(plan['copy'])} missing files, and look at {len(plan['differ'])} that differ from yours ({plan['same']} are already the same)?"
        if not self.confirm("Restore", text, "A file of yours that would be replaced is first saved under Backups/replaced-before-restore-..., and the newer file wins."):
            return
        done = backup_jarvis.restore(backup, self.root, parts, conflict="keep_newer")
        self.reload_from_env()
        self.tell("Restore", f"Restored {done['copied'] + done['replaced']} files ({done['kept']} of yours kept, {done['same']} were already the same).")

    # ---- Advanced

    def _page_advanced(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 12, 12)
        layout.addWidget(heading("Advanced"))
        layout.addWidget(muted("Every line of the .env file. Settings of your own (that this list does not know) are kept as they are, and you can add more here. "
                               "Passwords and keys are hidden. Changes on this page are saved the moment you make them."))
        self.env_table = QTableWidget(0, 3)
        self.env_table.setHorizontalHeaderLabels(["Setting", "Value", "What it is"])
        self.env_table.horizontalHeader().setStretchLastSection(True)
        self.env_table.setColumnWidth(0, 230)
        self.env_table.setColumnWidth(1, 300)
        self.env_table.verticalHeader().hide()
        self.env_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.env_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.env_table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.env_table, 1)
        row = QHBoxLayout()
        row.addWidget(button("Add a setting of my own...", self.add_own_setting))
        row.addWidget(button("Remove the selected", self.remove_selected_setting, "danger", "Takes the line out of .env (a known setting then has its usual value)"))
        row.addWidget(button("Undo the last save", self.undo_last_save, tip="Puts back the copy of .env that was kept before the last change"))
        row.addWidget(button("Open .env in Notepad", lambda: self._notepad(self.env.path)))
        row.addStretch(1)
        layout.addLayout(row)
        self.fill_env_table()
        return page

    def _notepad(self, path):
        try:
            subprocess.Popen(["notepad.exe", str(path)])
        except OSError as error:
            self.tell("Notepad", str(error))

    def fill_env_table(self):
        values = self.env.values()
        self.env_table.setRowCount(len(values))
        for number, (key, value) in enumerate(values.items()):
            setting = registry.BY_KEY.get(key)
            shown = mask(value) if value and (setting is None and any(w in key.upper() for w in ("KEY", "PASSWORD", "SECRET", "TOKEN")) or (setting is not None and setting.secret)) else value
            self.env_table.setItem(number, 0, QTableWidgetItem(key))
            self.env_table.setItem(number, 1, QTableWidgetItem(shown))
            self.env_table.setItem(number, 2, QTableWidgetItem(setting.label if setting else "your own setting"))

    def add_own_setting(self):
        key, ok = QInputDialog.getText(self, "A setting of my own", "Name (capital letters and underscores, for example MY_SETTING):")
        if not ok or not key.strip():
            return
        key = key.strip().upper().replace(" ", "_")
        value, ok = QInputDialog.getText(self, "A setting of my own", f"Value of {key}:")
        if not ok:
            return
        try:
            self.env.set(key, value)
        except ValueError as error:
            self.tell("Not accepted", str(error))
            return
        self.reload_from_env()

    def remove_selected_setting(self):
        row = self.env_table.currentRow()
        if row < 0:
            self.tell("Choose one", "Click a line in the list first.")
            return
        key = self.env_table.item(row, 0).text()
        if self.confirm("Remove", f"Take {key} out of the .env file?"):
            self.env.remove(key)
            self.reload_from_env()

    def undo_last_save(self):
        if not self.env.backups():
            self.tell("Undo", "There is no earlier copy of .env to go back to.")
            return
        if self.confirm("Undo", "Put back the copy of .env that was kept before the last change?"):
            self.env.restore_latest_backup()
            self.reload_from_env()

    # ---- keeping the boxes and the file in step

    def reload_from_env(self):
        """Read .env again and put every box, table and note in step with it."""
        values = registry.effective(self.env.values())
        for key, row in self.rows.items():
            row.set_value(values[key][0])
            row.saved = normalized(key, values[key][0])
            row._refresh()
        self.fill_env_table()
        self.refresh_overview()
        if hasattr(self, "security_note"):
            self.refresh_security_note()
        self._update_dirty()

    def changed_rows(self):
        return {key: row for key, row in self.rows.items() if row.is_changed()}

    def _update_dirty(self):
        changed = self.changed_rows()
        invalid = [key for key, row in changed.items() if not row.check().ok]
        for key, row in self.rows.items():
            if not row.check().ok and key not in invalid:
                invalid.append(key)
        self.dirty_label.setText("" if not changed else f"{len(changed)} change{'s' if len(changed) != 1 else ''} not saved yet"
                                 + (f" - {len(invalid)} need correcting" if invalid else ""))
        self.save_button.setEnabled(bool(changed) and not invalid)
        self.restart_button.setEnabled(bool(changed) and not invalid)
        self.revert_button.setEnabled(bool(changed))

    def revert(self):
        for row in self.changed_rows().values():
            row.revert()
        self._update_dirty()

    def save(self):
        """Write the changed settings to .env. Returns the list of (key, old, new) written, [] if nothing, None if it was refused."""
        changed = self.changed_rows()
        if not changed:
            return []
        bad = {key: row.check().message for key, row in changed.items() if not row.check().ok}
        if bad:
            self.tell("Not saved", "Some boxes need correcting first:\n" + "\n".join(f"- {self.rows[k].setting.label}: {m}" for k, m in bad.items()))
            return None
        updates = {key: normalized(key, row.value()) for key, row in changed.items()}
        before = self.env.values()
        lines = []
        for key, new in updates.items():
            setting = registry.BY_KEY[key]
            old = before.get(key, setting.default)
            lines.append(f"{setting.label}: {mask(old) if setting.secret and old else (old or '(empty)')}  ->  {mask(new) if setting.secret and new else (new or '(empty)')}")
        if not self.confirm("Save these changes?", f"{len(updates)} setting{'s' if len(updates) != 1 else ''} will be written to the .env file.", "\n".join(lines)):
            return None
        written = self.env.set_many(updates)
        for row in changed.values():
            row.mark_saved()
        self.fill_env_table()
        self.refresh_overview()
        self._update_dirty()
        return written

    def save_and_restart(self):
        written = self.save()
        if written is not None and self.restart_callback is not None:
            self.restart_callback()
            self.accept()

    def close_panel(self):
        if self.changed_rows() and not self.confirm("Close", "Some changes are not saved. Close without saving them?"):
            return
        self.reject()

    # ---- search and advanced

    def _advanced_toggled(self, on):
        self.show_advanced = on
        self.apply_filter()

    def apply_filter(self, _text=None):
        text = self.search.text()
        first_with_matches = None
        for page_id, title in PAGES:
            item, widget = self.nav_pages[page_id]
            if page_id not in registry.GROUP_BY_ID:
                item.setText(title)
                continue
            shown = 0
            for setting in registry.settings_in(page_id):
                row = self.rows[setting.key]
                visible = row.matches(text) and (self.show_advanced or not setting.advanced or bool(text.strip()))
                row.setVisible(visible)
                shown += visible
            page = widget.widget()
            page.empty_label.setVisible(shown == 0)
            item.setText(title + (f"  ({shown})" if text.strip() else ""))
            if shown and first_with_matches is None:
                first_with_matches = page_id
        if text.strip() and first_with_matches is not None:
            current_id = PAGES[self.nav.currentRow()][0] if self.nav.currentRow() >= 0 else ""
            if current_id in registry.GROUP_BY_ID and self.nav_pages[current_id][1].widget().empty_label.isVisible() or current_id not in registry.GROUP_BY_ID:
                self.nav.setCurrentRow([p for p, _ in PAGES].index(first_with_matches))

    def show_page(self, page_id):
        self.nav.setCurrentRow([p for p, _ in PAGES].index(page_id))


class _Null:
    """An output that discards everything (the overview's look-around prints nothing)."""

    def write(self, text):
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def open_admin(parent=None, restart=None, root=None, effects=None):
    """Ask for the password, then open the panel. Returns True if it was opened."""
    if gate.password_configured():
        prompt = PasswordPrompt(parent)
        if prompt.exec_() != QDialog.Accepted:
            return False
    panel = AdminPanel(parent, root=root, effects=effects, restart=restart)
    panel.exec_()
    return True
