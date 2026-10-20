"""The small parts the admin panel is built from: one row per setting (with the right kind of control for it), the password
dialogs, and the editor for a shortcut or a contact.

A SettingRow knows its Setting (settings_registry.py): its label, its explanation, its range and its usual value. It shows
a red note under itself while the value is not acceptable, marks itself when it differs from what is saved, and offers "usual" to put
the usual value back.
"""
import os
import subprocess
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

import config
import contacts
import gate
import settings_registry as registry
import shortcuts
from gui import theme

NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_CONSOLE_WRAPPER = ("import subprocess, sys; code = subprocess.call([sys.executable] + sys.argv[2:], cwd=sys.argv[1]); "
                    "input('\\nPress Enter to close this window...')")


def run_in_console(root, arguments):
    """Run `python <arguments>` in a window of its own that stays open until Enter is pressed (for the tools that ask questions,
    such as the voice lesson). Returns the process, or None if it could not start."""
    try:
        return subprocess.Popen([sys.executable, "-c", _CONSOLE_WRAPPER, str(root), *arguments], creationflags=NEW_CONSOLE, cwd=str(root))
    except OSError:
        return None


def normalized(key, text):
    """The text as it would be saved, so that "1.0" and "1" (or "Yes" and "true") are seen as the same value."""
    result = registry.validate(key, text)
    return result.value if result.ok else str(text).strip()


class SettingRow(QFrame):
    """One setting: its name, an explanation, the control, and a note when the value is not acceptable."""
    changed = pyqtSignal()

    def __init__(self, setting, value, options=(), parent=None):
        super().__init__(parent)
        self.setting = setting
        self.saved = normalized(setting.key, value)
        self.setObjectName("settingRow")
        self._building = True
        self.label = QLabel(setting.label)
        self.label.setObjectName("settingLabel")
        key = QLabel(setting.key)
        key.setObjectName("muted")
        key.setStyleSheet("font-family: Consolas; font-size: 8pt;")
        self.help = QLabel(setting.help)
        self.help.setObjectName("muted")
        self.help.setWordWrap(True)
        self.problem = QLabel("")
        self.problem.setStyleSheet(f"color: {theme.BAD};")
        self.problem.setWordWrap(True)
        self.problem.hide()
        self.editor = self._make_editor(options)
        self.usual_button = QPushButton("usual")
        self.usual_button.setObjectName("tool")
        self.usual_button.setToolTip(f"Put back the usual value ({setting.default or 'empty'})")
        self.usual_button.setFixedWidth(64)
        self.usual_button.clicked.connect(lambda: self.set_value(setting.default, from_user=True))

        top = QHBoxLayout()
        top.addWidget(self.label)
        top.addWidget(key)
        top.addStretch(1)
        control = QHBoxLayout()
        control.addWidget(self.editor, 1)
        if setting.secret:
            self.show_button = QPushButton("show")
            self.show_button.setObjectName("tool")
            self.show_button.setCheckable(True)
            self.show_button.setFixedWidth(64)
            self.show_button.toggled.connect(lambda on: self.editor.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
            control.addWidget(self.show_button)
        control.addWidget(self.usual_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)
        layout.addLayout(top)
        layout.addWidget(self.help)
        layout.addLayout(control)
        layout.addWidget(self.problem)
        self.set_value(value)
        self._building = False
        self._refresh()

    # ---- the control

    def _make_editor(self, options):
        s = self.setting
        if s.kind == "bool":
            box = QCheckBox("On")
            box.toggled.connect(lambda on: (box.setText("On" if on else "Off"), self._edited()))
            return box
        if s.kind == "int":
            spin = QSpinBox()
            spin.setRange(int(s.minimum) if s.minimum is not None else -1000000, int(s.maximum) if s.maximum is not None else 1000000)
            if s.unit:
                spin.setSuffix(" " + s.unit)
            spin.valueChanged.connect(lambda _v: self._edited())
            return spin
        if s.kind == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setSingleStep(0.05 if (s.maximum or 0) <= 1 else 0.1)
            spin.setRange(0.0 if s.zero_allowed else float(s.minimum if s.minimum is not None else -1e6), float(s.maximum if s.maximum is not None else 1e6))
            if s.unit:
                spin.setSuffix(" " + s.unit)
            spin.valueChanged.connect(lambda _v: self._edited())
            return spin
        if s.kind == "choice":
            combo = QComboBox()
            seen = set()
            for value, label in list(s.choices) + [(o, o) for o in options]:
                if value not in seen:
                    seen.add(value)
                    combo.addItem(label if label != value else (value or "(Windows default)"), value)
            if s.strict:
                combo.currentIndexChanged.connect(lambda _i: self._edited())
            else:
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.NoInsert)
                combo.editTextChanged.connect(lambda _t: self._edited())
                combo.currentIndexChanged.connect(lambda _i: self._edited())
            return combo
        line = QLineEdit()
        if s.secret:
            line.setEchoMode(QLineEdit.Password)
        line.textChanged.connect(lambda _t: self._edited())
        return line

    def value(self):
        """What the control shows now, as text."""
        s, e = self.setting, self.editor
        if s.kind == "bool":
            return "true" if e.isChecked() else "false"
        if s.kind == "int":
            return str(e.value())
        if s.kind == "float":
            return f"{e.value():.2f}".rstrip("0").rstrip(".") or "0"
        if s.kind == "choice":
            if s.strict:
                return str(e.currentData())
            text = e.currentText().strip()
            index = e.findText(text)
            return str(e.itemData(index)) if index >= 0 and e.itemData(index) is not None else text
        return e.text().strip()

    def set_value(self, text, from_user=False):
        s, e = self.setting, self.editor
        text = "" if text is None else str(text)
        was = self._building
        self._building = True
        try:
            if s.kind == "bool":
                e.setChecked(registry.is_true(text) if text else registry.is_true(s.default))
                e.setText("On" if e.isChecked() else "Off")
            elif s.kind == "int":
                try:
                    e.setValue(int(float(text)))
                except ValueError:
                    e.setValue(int(float(s.default or 0)))
            elif s.kind == "float":
                try:
                    e.setValue(float(text))
                except ValueError:
                    e.setValue(float(s.default or 0))
            elif s.kind == "choice":
                index = e.findData(text)
                if index < 0:
                    index = e.findText(text)
                if index >= 0:
                    e.setCurrentIndex(index)
                elif s.strict:
                    e.addItem(f"{text} (not a valid choice)", text)         # shown so that a wrong value in .env can be seen and corrected
                    e.setCurrentIndex(e.count() - 1)
                else:
                    e.setEditText(text)
            else:
                e.setText(text)
        finally:
            self._building = was
        self._refresh()
        if from_user:
            self.changed.emit()

    # ---- state

    def _edited(self):
        if self._building:
            return
        self._refresh()
        self.changed.emit()

    def is_changed(self):
        return normalized(self.setting.key, self.value()) != self.saved

    def check(self):
        return registry.validate(self.setting.key, self.value())

    def mark_saved(self):
        self.saved = normalized(self.setting.key, self.value())
        self._refresh()

    def revert(self):
        self.set_value(self.saved)

    def _refresh(self):
        result = self.check()
        self.problem.setText(result.message if not result.ok else "")
        self.problem.setVisible(not result.ok)
        changed = self.is_changed()
        self.label.setStyleSheet(f"color: {theme.YOU if changed else theme.TEXT}; font-weight: 600;")
        self.usual_button.setEnabled(normalized(self.setting.key, self.setting.default) != normalized(self.setting.key, self.value()))

    def matches(self, text):
        text = text.strip().lower()
        s = self.setting
        return not text or text in f"{s.label} {s.key} {s.help}".lower()


class PasswordPrompt(QDialog):
    """Asks for the Jarvis password before the admin panel opens (three tries)."""
    MAX_TRIES = 3

    def __init__(self, parent=None, check=None):
        super().__init__(parent)
        self.check = check or gate.check_password
        self.tries = 0
        self.setWindowTitle("Admin panel")
        self.setModal(True)
        self.setFixedWidth(400)
        heading = QLabel("ADMIN PANEL")
        heading.setObjectName("heading")
        hint = QLabel("Type the Jarvis password to change his settings.")
        hint.setObjectName("muted")
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.Password)
        self.field.setPlaceholderText("Password")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.ok = QPushButton("OPEN")
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.ok)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        for widget in (heading, hint, self.field, self.message):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        self.ok.clicked.connect(self.submit)
        self.field.returnPressed.connect(self.submit)
        cancel.clicked.connect(self.reject)

    def submit(self):
        attempt = self.field.text()
        if not attempt:
            return
        if self.check(attempt):
            self.accept()
            return
        self.tries += 1
        self.field.clear()
        if self.tries >= self.MAX_TRIES:
            self.message.setText("Access not granted.")
            self.message.setStyleSheet(f"color: {theme.BAD};")
            self.reject()
            return
        self.message.setText(f"That is not the password. {self.MAX_TRIES - self.tries} {'try' if self.MAX_TRIES - self.tries == 1 else 'tries'} left.")
        self.message.setStyleSheet(f"color: {theme.BAD};")


class ChangePasswordDialog(QDialog):
    """A new password, typed twice. Only its scrambled form is stored."""

    def __init__(self, parent=None, env_path=None, require_current=False):
        super().__init__(parent)
        self.env_path = env_path
        self.require_current = require_current
        self.setWindowTitle("Change the password")
        self.setModal(True)
        self.setFixedWidth(430)
        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.Password)
        self.current.setPlaceholderText("Current password")
        self.current.setVisible(require_current)
        self.first = QLineEdit()
        self.first.setEchoMode(QLineEdit.Password)
        self.first.setPlaceholderText("New password (at least 4 characters; 8 or more is better)")
        self.second = QLineEdit()
        self.second.setEchoMode(QLineEdit.Password)
        self.second.setPlaceholderText("The new password again")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.save_button = QPushButton("SAVE")
        self.save_button.setObjectName("primary")
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        heading = QLabel("CHANGE THE PASSWORD")
        heading.setObjectName("heading")
        note = QLabel("Only a scrambled form of the password is stored; nobody, including Jarvis, can read it back.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        for widget in (heading, note, self.current, self.first, self.second, self.message):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)

    def save(self):
        if self.require_current and not gate.check_password(self.current.text()):
            return self._say("The current password is not right.")
        new = self.first.text().strip()
        if len(new) < 4:
            return self._say("Use at least 4 characters.")
        if new != self.second.text().strip():
            return self._say("The two entries are different.")
        gate.store_password(new, env_path=self.env_path)
        stored = gate.hash_password(new) if self.env_path is None else None
        from envfile import EnvFile
        written = EnvFile(self.env_path or config.BASE_DIR / ".env").get("JARVIS_PASSWORD_HASH")
        config.JARVIS_PASSWORD_HASH = written or stored or ""         # the running Jarvis uses the new password straight away
        config.JARVIS_PASSWORD = ""
        self.accept()

    def _say(self, text):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {theme.BAD};")


class ItemDialog(QDialog):
    """Adds or edits a shortcut or a contact. ``fields`` = [(key, label, kind, extra)]; kind is text | choice | path."""

    def __init__(self, title, fields, values, check, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.check_item = check
        self.editors = {}
        form = QFormLayout()
        form.setContentsMargins(24, 20, 24, 8)
        form.setVerticalSpacing(10)
        for key, label, kind, extra in fields:
            if kind == "choice":
                widget = QComboBox()
                for value, text in extra:
                    widget.addItem(text, value)
                index = widget.findData(values.get(key, ""))
                widget.setCurrentIndex(max(0, index))
                form.addRow(label, widget)
            else:
                widget = QLineEdit(str(values.get(key, "")))
                if extra:
                    widget.setPlaceholderText(extra if isinstance(extra, str) else "")
                if kind == "path":
                    row = QHBoxLayout()
                    row.addWidget(widget, 1)
                    browse = QPushButton("Browse...")
                    browse.setObjectName("tool")
                    browse.clicked.connect(lambda _c=False, w=widget: self._browse(w))
                    row.addWidget(browse)
                    form.addRow(label, row)
                else:
                    form.addRow(label, widget)
            self.editors[key] = widget
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color: {theme.BAD};")
        self.ok = QPushButton("SAVE")
        self.ok.setObjectName("primary")
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(24, 0, 24, 18)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.ok)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self.item = None
        self.ok.clicked.connect(self.accept_item)
        cancel.clicked.connect(self.reject)

    def current(self):
        out = {}
        for key, widget in self.editors.items():
            out[key] = str(widget.currentData()) if isinstance(widget, QComboBox) else widget.text()
        return out

    def _browse(self, widget):
        kind = self.editors.get("kind")
        chosen_kind = str(kind.currentData()) if isinstance(kind, QComboBox) else "file"
        if chosen_kind == "folder":
            path = QFileDialog.getExistingDirectory(self, "Choose a folder", widget.text() or os.path.expanduser("~"))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Choose a file or program", widget.text() or os.path.expanduser("~"))
        if path:
            widget.setText(os.path.normpath(path))

    def accept_item(self):
        ok, tidy, message = self.check_item(self.current())
        if not ok:
            self.message.setText(message)
            return
        self.item = tidy
        self.accept()


def edit_shortcut(parent, values=None):
    """Open the shortcut editor. Returns the tidied shortcut, or None if cancelled."""
    kinds = [(k, shortcuts.KIND_LABELS[k]) for k in shortcuts.KINDS]
    dialog = ItemDialog("A shortcut", [("name", "What you say", "text", "for example: college portal"),
                                       ("kind", "It opens", "choice", kinds),
                                       ("target", "Where it goes", "path", "a web address, a folder, a file or a program")],
                        values or {"kind": "website"}, shortcuts.check, parent)
    return dialog.item if dialog.exec_() == QDialog.Accepted else None


def edit_contact(parent, values=None):
    dialog = ItemDialog("A contact", [("name", "Name", "text", "what you will say, for example: Ali"), ("email", "Email address", "text", "ali@example.com"),
                                      ("phone", "Phone number (optional)", "text", ""), ("note", "Note (optional)", "text", "")],
                        values or {}, contacts.check, parent)
    return dialog.item if dialog.exec_() == QDialog.Accepted else None


def say(parent, title, text, detail=""):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.exec_()


def ask_yes(parent, title, text, detail=""):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec_() == QMessageBox.Yes
