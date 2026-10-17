"""The unlock dialog: the password first, then an optional glance at the webcam (never required).

It asks gate.py, the same module the terminal launcher asks, so the rules cannot differ between the two.

Keyboard behaviour matters here, because people type the password and press Enter:
* Enter means UNLOCK. In a dialog every button is "auto default" and Qt makes the focused one the default,
  so Enter used to press Cancel (the last button) and quietly threw the unlock away.
* Once the password is right, nothing a stray key does can cancel: Escape (or the window's X) now skips the
  camera step and carries on, and the dialog reports only its first result.
"""
import threading

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

import config
import gate
from gui import theme


class LoginDialog(QDialog):
    MAX_ATTEMPTS = 3
    _face_done = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unlock Jarvis")
        self.setModal(True)
        self.setFixedWidth(430)
        self.face_confirmed = None          # None = not checked, otherwise whether the camera knew you
        self._attempts = 0
        self._closing = False               # set once the dialog has reported its result; the camera is told to stop
        self._camera_running = False        # from the right password until the dialog closes

        heading = QLabel("UNLOCK  JARVIS")
        heading.setObjectName("heading")
        hint = QLabel("Jarvis is password protected. Type the password and press Enter.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(40)
        self.unlock_button = QPushButton("UNLOCK")
        self.unlock_button.setObjectName("primary")
        self.skip_button = QPushButton("Skip the camera")
        self.skip_button.hide()
        self.cancel_button = QPushButton("Cancel")
        self.unlock_button.setDefault(True)
        self.skip_button.setAutoDefault(False)
        self.cancel_button.setAutoDefault(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.unlock_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        for widget in (heading, hint, self.password, self.message):
            layout.addWidget(widget)
        layout.addLayout(buttons)

        self.password.returnPressed.connect(self.submit)
        self.unlock_button.clicked.connect(self.submit)
        self.cancel_button.clicked.connect(self.reject)
        self.skip_button.clicked.connect(self._skip_camera)
        self._face_done.connect(self._camera_finished)

        if not gate.password_configured():
            self._lock_out("No unlock password is set. Add JARVIS_PASSWORD to the .env file, "
                           "or run:  python gate.py --set-password")
        else:
            self.password.setFocus()

    # ---- results

    def done(self, result):
        if self._closing:
            return                          # the first result wins: a late accept can't undo a cancel, or the reverse
        self._closing = True
        super().done(result)

    def reject(self):
        if self._camera_running:
            self._skip_camera()             # Escape or the X after the password was right: carry on without the camera
        else:
            super().reject()

    def _finish(self):
        self._camera_running = False
        self.accept()

    # ---- the password

    def _say(self, text, colour=theme.MUTED):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {colour};")

    def _lock_out(self, text):
        self.password.setEnabled(False)
        self.unlock_button.setEnabled(False)
        self._say(text, theme.BAD)

    def submit(self):
        if self._closing or not self.unlock_button.isEnabled():
            return
        attempt = self.password.text()
        if not attempt:
            return                          # Enter on an empty box is not a try (and one Enter arrives here twice)
        if gate.check_password(attempt):
            self._granted()
            return
        self._attempts += 1
        self.password.clear()
        left = self.MAX_ATTEMPTS - self._attempts
        if left <= 0:
            self._lock_out("Access not granted.")
            QTimer.singleShot(1200, self.reject)
        else:
            self._say(f"Access not granted. {left} {'try' if left == 1 else 'tries'} left.", theme.BAD)
            self.password.setFocus()

    # ---- the camera

    def _granted(self):
        self.password.setEnabled(False)
        self.unlock_button.setEnabled(False)
        if not config.FACE_CHECK:
            self._finish()
            return
        self._camera_running = True
        self.cancel_button.hide()           # the password was right, so there is nothing left to cancel
        self.skip_button.show()
        self.skip_button.setFocus()
        self._say("Access granted. Taking a quick look at the camera for extra confirmation. "
                  "Press Esc, or the button below, to skip.", theme.GOOD)
        threading.Thread(target=self._look, name="face-check", daemon=True).start()

    def _look(self):
        try:
            found = bool(gate.face_check(cancelled=lambda: self._closing))
        except Exception:
            found = False
        try:
            self._face_done.emit(found)
        except RuntimeError:
            pass                            # the dialog is already gone

    def _camera_finished(self, found):
        if self._closing:
            return
        self.face_confirmed = found
        self._say(f"Face confirmed. Welcome back, {config.USER_NAME}." if found
                  else "I couldn't confirm your face, but your password was correct, so I'll continue.", theme.GOOD)
        self.skip_button.hide()
        QTimer.singleShot(900, self._finish)

    def _skip_camera(self):
        self._finish()
