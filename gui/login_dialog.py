"""The unlock dialog: the password first, then an optional glance at the webcam (never required).

It asks gate.py, the same module the terminal launcher asks, so the rules cannot differ between the two.
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
        self._closing = False

        heading = QLabel("UNLOCK  JARVIS")
        heading.setObjectName("heading")
        hint = QLabel("Jarvis is password protected.")
        hint.setObjectName("muted")
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

    def _say(self, text, colour=theme.MUTED):
        self.message.setText(text)
        self.message.setStyleSheet(f"color: {colour};")

    def _lock_out(self, text):
        self.password.setEnabled(False)
        self.unlock_button.setEnabled(False)
        self._say(text, theme.BAD)

    def submit(self):
        if not self.unlock_button.isEnabled():
            return
        if gate.check_password(self.password.text()):
            self._granted()
            return
        self._attempts += 1
        self.password.clear()
        if self._attempts >= self.MAX_ATTEMPTS:
            self._lock_out("Access not granted.")
            QTimer.singleShot(1200, self.reject)
        else:
            self._say(f"Access not granted. {self.MAX_ATTEMPTS - self._attempts} "
                      f"{'try' if self.MAX_ATTEMPTS - self._attempts == 1 else 'tries'} left.", theme.BAD)
            self.password.setFocus()

    def _granted(self):
        self.password.setEnabled(False)
        self.unlock_button.setEnabled(False)
        if not config.FACE_CHECK:
            self._finish()
            return
        self._say("Access granted. Taking a quick look at the camera for extra confirmation. "
                  "Press Esc in the camera window, or the button below, to skip.", theme.GOOD)
        self.skip_button.show()
        threading.Thread(target=self._look, name="face-check", daemon=True).start()

    def _look(self):
        try:
            found = bool(gate.face_check())
        except Exception:
            found = False
        self._face_done.emit(found)

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

    def _finish(self):
        if not self._closing:
            self._closing = True
            self.accept()
