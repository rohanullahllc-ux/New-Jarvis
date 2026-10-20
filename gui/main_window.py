"""Jarvis's main window (start it with JarvisGUI.py).

START opens the unlock dialog first, then runs the same session the terminal runs. Typed commands, the
microphone button (push to talk) and the hands-free switch all feed that one session, and everything
Jarvis says appears in the conversation, so the window works with the sound off.
"""
import html
import subprocess
import sys
import webbrowser

from PyQt5.QtCore import QDateTime, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap, QTextCursor
from PyQt5.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                             QPlainTextEdit, QPushButton, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

import config
import ui_bridge
from gui import theme
from gui.login_dialog import LoginDialog
from gui.session import SessionController, WakeController
from gui.sprites import SpritePlayer

QUICK_LINKS = [("YouTube", "https://www.youtube.com"), ("Google", "https://www.google.com"),
               ("Gmail", "https://mail.google.com"), ("WhatsApp", "https://web.whatsapp.com"),
               ("Instagram", "https://www.instagram.com"), ("Facebook", "https://www.facebook.com"),
               ("GitHub", "https://github.com"), ("Maps", "https://maps.google.com")]
UTILITIES = [("Calculator", "calculator"), ("Calendar", "calendar"), ("Currency", "currency_converter")]
MUSIC = config.BASE_DIR / "DataBase" / "Sounds" / "Iron Man Music.mp3"


def panel(object_name="panel"):
    frame = QFrame()
    frame.setObjectName(object_name)
    return frame


def heading(text):
    label = QLabel(text.upper())
    label.setObjectName("heading")
    return label


class MainWindow(QMainWindow):
    admin_requested = pyqtSignal()                 # "open the admin panel" was said or typed (that happens on the session's thread)

    def __init__(self, controller=None, login=LoginDialog, wake=None, admin=None):
        super().__init__()
        self._open_admin = admin                      # what opens the admin panel (tests supply their own)
        self.controller = controller or SessionController()
        self._login = login
        self._started_once = False
        self.wake = wake                      # a WakeController: "hey Jarvis" or a clap presses START for you (None = off)
        self._closing = False
        self.setWindowTitle("J.A.R.V.I.S")
        self.resize(1120, 760)
        self.setMinimumSize(980, 700)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 10)
        outer.setSpacing(10)
        outer.addLayout(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_left())
        body.addWidget(self._build_centre(), 1)
        body.addWidget(self._build_right())
        outer.addLayout(body, 1)
        outer.addLayout(self._build_footer())

        self._connect()
        self._on_state("locked")
        self._refresh_system()
        self._tick()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(1000)
        self.setWindowIcon(self._icon())
        self.admin_requested.connect(self.open_admin)
        self._admin_handler = self.admin_requested.emit
        ui_bridge.register("admin", self._admin_handler)
        if self.wake is not None:
            self.wake.woke.connect(self._on_woke)
            self.wake.problem.connect(self._on_wake_problem)
            QTimer.singleShot(0, self._arm_wake)                      # once the window is up

    # ---- waking him by voice or by clapping

    def _arm_wake(self):
        """While he sleeps, listen for "hey Jarvis" or a clap (they do what START does)."""
        if self.wake is None or self._closing or self.controller.running:
            return
        if self.wake.arm():
            from listener import hint
            self._say_status(hint())
            QTimer.singleShot(2500, self.wake.check)                  # the microphone may turn out not to open

    def _on_woke(self, reason):
        """"hey Jarvis" or the claps were heard: the same as START, which asks for the password."""
        self.wake.disarm()                                            # the session opens the microphone for itself
        self._say_status(f"Woken by {reason}.")
        self.show()
        self.raise_()
        self.activateWindow()
        QApplication.beep()
        self.start()
        if not self.controller.running:                               # the password was not given
            self._arm_wake()

    def _on_wake_problem(self, text):
        self._say_status(text)
        self._add_note(text)

    # ---- building the window

    def _icon(self):
        ring = self.ring
        frame = ring.sheet.copy(ring.frame_rect(0).toRect())
        return QIcon(QPixmap.fromImage(frame))

    def _build_header(self):
        row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("J . A . R . V . I . S")
        title.setObjectName("title")
        subtitle = QLabel("JUST A RATHER VERY INTELLIGENT SYSTEM")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.pill = QLabel()
        self.pill.setTextFormat(Qt.RichText)
        self.pill.setStyleSheet(f"font-weight: 600; font-size: 11pt; padding: 6px 14px; border: 1px solid {theme.EDGE};"
                                "border-radius: 14px;")
        self.admin_button = QPushButton("ADMIN")
        self.admin_button.setToolTip("Change Jarvis's settings, make shortcuts and contacts, back up (asks for the password)")
        row.addLayout(titles)
        row.addStretch(1)
        row.addWidget(self.admin_button, 0, Qt.AlignVCenter)
        row.addWidget(self.pill, 0, Qt.AlignVCenter)
        return row

    def _build_left(self):
        column = QWidget()
        column.setFixedWidth(290)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        ring_frame = panel("screen")
        ring_layout = QVBoxLayout(ring_frame)
        ring_layout.setContentsMargins(6, 6, 6, 6)
        self.ring = SpritePlayer("ring", animate=config.GUI_ANIMATIONS)
        self.ring.setMinimumSize(200, 200)
        ring_layout.addWidget(self.ring)
        layout.addWidget(ring_frame)

        clock_frame = panel()
        clock_layout = QVBoxLayout(clock_frame)
        clock_layout.setSpacing(0)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        self.clock.setAlignment(Qt.AlignCenter)
        self.date = QLabel()
        self.date.setObjectName("muted")
        self.date.setAlignment(Qt.AlignCenter)
        clock_layout.addWidget(self.clock)
        clock_layout.addWidget(self.date)
        layout.addWidget(clock_frame)

        system = panel()
        grid = QGridLayout(system)
        grid.setVerticalSpacing(4)
        grid.addWidget(heading("System"), 0, 0, 1, 2)
        self.system_values = {}
        for row, name in enumerate(("Brain", "Input", "Voice", "User"), start=1):
            label = QLabel(name)
            label.setObjectName("muted")
            value = QLabel()
            value.setObjectName("value")
            value.setWordWrap(True)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self.system_values[name] = value
        grid.setColumnStretch(1, 1)
        layout.addWidget(system)

        layout.addStretch(1)
        self.start_button = QPushButton("START")
        self.start_button.setObjectName("primary")
        self.lock_button = QPushButton("SLEEP")
        self.lock_button.setToolTip("Put Jarvis to sleep; you will need the password to wake him")
        self.quit_button = QPushButton("QUIT")
        self.quit_button.setObjectName("danger")
        layout.addWidget(self.start_button)
        pair = QHBoxLayout()
        pair.addWidget(self.lock_button)
        pair.addWidget(self.quit_button)
        layout.addLayout(pair)
        return column

    def _build_centre(self):
        self.pages = QStackedWidget()

        splash = QWidget()
        splash_layout = QVBoxLayout(splash)
        screen = panel("screen")
        screen_layout = QVBoxLayout(screen)
        screen_layout.setContentsMargins(8, 8, 8, 8)
        self.hero = SpritePlayer("hero", animate=config.GUI_ANIMATIONS)
        screen_layout.addWidget(self.hero, 1)
        caption = QLabel("Press START and enter the password to wake Jarvis.")
        caption.setObjectName("splash")
        caption.setAlignment(Qt.AlignCenter)
        screen_layout.addWidget(caption)
        splash_layout.addWidget(screen)
        self.pages.addWidget(splash)

        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(8)
        self.chat = QTextBrowser()
        self.chat.setOpenLinks(False)
        chat_layout.addWidget(self.chat, 1)
        entry = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command")
        self.input.setToolTip("Type a command and press Enter, or click the microphone and speak")
        self.send_button = QPushButton("SEND")
        self.mic_button = QPushButton("\U0001F3A4")
        self.mic_button.setObjectName("mic")
        self.mic_button.setToolTip("Push to talk: click, then speak one command")
        self.hands_free_button = QPushButton("HANDS-FREE")
        self.hands_free_button.setCheckable(True)
        self.hands_free_button.setToolTip("Keep listening for commands without clicking")
        self.new_chat_button = QPushButton("NEW CHAT")
        self.new_chat_button.setToolTip("Clear this conversation and start afresh (what you asked Jarvis to remember stays)")
        entry.addWidget(self.input, 1)
        entry.addWidget(self.send_button)
        entry.addWidget(self.new_chat_button)
        entry.addWidget(self.mic_button)
        entry.addWidget(self.hands_free_button)
        chat_layout.addLayout(entry)
        self.pages.addWidget(chat_page)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(8)
        centre_layout.addWidget(self.pages, 1)
        centre_layout.addWidget(self._build_log())
        return centre

    def _build_right(self):
        column = QWidget()
        column.setFixedWidth(270)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        earth_frame = panel("screen")
        earth_layout = QVBoxLayout(earth_frame)
        earth_layout.setContentsMargins(6, 6, 6, 6)
        self.earth = SpritePlayer("earth", animate=config.GUI_ANIMATIONS)
        self.earth.setMinimumSize(220, 160)
        earth_layout.addWidget(self.earth)
        layout.addWidget(earth_frame)

        links = panel()
        links_layout = QGridLayout(links)
        links_layout.setVerticalSpacing(6)
        links_layout.addWidget(heading("Quick links"), 0, 0, 1, 2)
        self.link_buttons = {}
        for number, (name, url) in enumerate(QUICK_LINKS):
            button = QPushButton(name)
            button.clicked.connect(lambda _checked=False, url=url: webbrowser.open(url))
            links_layout.addWidget(button, 1 + number // 2, number % 2)
            self.link_buttons[name] = button
        layout.addWidget(links)

        tools = panel()
        tools_layout = QGridLayout(tools)
        tools_layout.setVerticalSpacing(6)
        tools_layout.addWidget(heading("Tools"), 0, 0, 1, 3)
        self.utility_buttons = {}
        for number, (name, key) in enumerate(UTILITIES):
            button = QPushButton(name)
            button.setObjectName("tool")
            button.clicked.connect(lambda _checked=False, key=key: self._open_utility(key))
            tools_layout.addWidget(button, 1, number)
            self.utility_buttons[key] = button
        self.music_button = QPushButton("▶  Play theme")
        self.music_button.setCheckable(True)
        self.music_button.toggled.connect(self._toggle_music)
        tools_layout.addWidget(self.music_button, 2, 0, 1, 3)
        layout.addWidget(tools)
        layout.addStretch(1)
        return column

    def _build_footer(self):
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("message")
        self.log_button = QPushButton("LOG")
        self.log_button.setCheckable(True)
        self.log_button.setFixedWidth(64)
        row.addWidget(self.status, 1)
        row.addWidget(self.log_button)
        return row

    def _build_log(self):
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFixedHeight(120)
        self.log_view.hide()
        return self.log_view

    def _connect(self):
        c = self.controller
        c.state_changed.connect(self._on_state)
        c.said.connect(self._said)
        c.said_more.connect(self._add_more)
        c.heard.connect(lambda text: self._add("YOU", text, theme.YOU))
        c.log.connect(self.log_view.appendPlainText)
        c.problem.connect(self._on_problem)
        c.ended.connect(self._on_ended)
        c.hands_free_changed.connect(self._on_hands_free)
        self.start_button.clicked.connect(self.start)
        self.lock_button.clicked.connect(lambda: c.submit("sleep"))
        self.quit_button.clicked.connect(self.close)
        self.send_button.clicked.connect(self.send)
        self.new_chat_button.clicked.connect(self.new_chat)
        self.admin_button.clicked.connect(self.open_admin)
        self.input.returnPressed.connect(self.send)
        self.mic_button.clicked.connect(lambda _checked=False: self.controller.talk())
        self.hands_free_button.toggled.connect(c.set_hands_free)
        self.log_button.toggled.connect(self.log_view.setVisible)

    # ---- what the buttons do

    def start(self):
        """Ask for the password, then start the session."""
        if self.controller.running:
            return
        if self.wake is not None:
            self.wake.disarm()                                        # (the session needs the microphone)
        dialog = self._login(self)
        if dialog.exec_() != dialog.Accepted:
            self._say_status("Not unlocked.")
            self._arm_wake()
            return
        self.pages.setCurrentIndex(1)
        if self._started_once:
            self._add_note("Session started")
        self._started_once = True
        self._say_status("")
        self.controller.start()
        if config.INPUT_MODE == "voice":
            self.hands_free_button.setChecked(True)
        self.input.setFocus()

    def send(self):
        text = self.input.text()
        if self.controller.submit(text):
            self.input.clear()

    def new_chat(self):
        """Clear the conversation on screen and have Jarvis forget it too."""
        if self.controller.reset_chat():
            self.chat.clear()

    def open_admin(self):
        """The admin panel (it asks for the password first). It can be opened while Jarvis is asleep or awake."""
        if self._open_admin is not None:
            self._open_admin(self)
            return
        from gui.admin_panel import open_admin
        open_admin(self, restart=self.restart_jarvis)

    def restart_jarvis(self):
        """Close this window and open Jarvis again a few seconds later, as a new process, so every changed setting is read afresh."""
        from jarvis_setup import windows
        code = "import subprocess, sys, time; time.sleep(3); subprocess.Popen([sys.argv[1], sys.argv[2]], cwd=sys.argv[3])"
        try:
            subprocess.Popen([sys.executable, "-c", code, windows.pythonw(), str(config.BASE_DIR / "JarvisGUI.py"), str(config.BASE_DIR)],
                             creationflags=0x00000008 | getattr(subprocess, "CREATE_NO_WINDOW", 0))       # DETACHED_PROCESS | CREATE_NO_WINDOW
        except OSError as error:
            self._say_status(f"I could not restart myself ({error}). Close me and start me again.")
            return
        QTimer.singleShot(200, self.close)

    def _open_utility(self, key):
        from gui.utils import launcher
        try:
            launcher.launch(key)
        except (FileNotFoundError, OSError) as error:
            self._say_status(str(error))

    def _toggle_music(self, on):
        try:
            from sound_player import playsound
            if on:
                playsound(MUSIC, block=False)
                self.music_button.setText("■  Stop theme")
            else:
                from pygame import mixer
                mixer.music.stop()
                self.music_button.setText("▶  Play theme")
        except Exception as error:                      # no sound device, missing file...
            self._say_status(f"I can't play the theme: {error}")
            self.music_button.blockSignals(True)
            self.music_button.setChecked(False)
            self.music_button.blockSignals(False)
            self.music_button.setText("▶  Play theme")

    # ---- reacting to the session

    def _said(self, text):
        if text.startswith("Fresh start, sir. I've cleared"):        # "new chat" said or typed: clear the screen like the button
            self.chat.clear()
        self._add("JARVIS", text, theme.ACCENT)

    def _add(self, who, text, colour):
        stamp = QDateTime.currentDateTime().toString("HH:mm")
        body = html.escape(text).replace("\n", "<br>")
        self.chat.append(f'<div style="margin: 8px 0 2px 0;"><b style="color:{colour};">{who}</b> '
                         f'<span style="color:{theme.MUTED}; font-size:8pt;">{stamp}</span><br>{body}</div>')
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _add_more(self, text):
        """The next sentence of the reply Jarvis is still giving: it joins the end of his last message."""
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(" " + text)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _add_note(self, text):
        self.chat.append(f'<div style="margin: 10px 0; color:{theme.MUTED}; text-align:center;">&mdash; {html.escape(text)} &mdash;</div>')

    def _on_state(self, state):
        label, colour = theme.STATES[state]
        self.pill.setText(f'<span style="color:{colour};">●</span>&nbsp;{label}')
        active = state != "locked"
        for widget in (self.input, self.send_button, self.new_chat_button, self.mic_button, self.hands_free_button, self.lock_button):
            widget.setEnabled(active)
        self.start_button.setEnabled(not active)
        self.start_button.setText("START" if not active else "RUNNING")
        if not active:
            self.hands_free_button.setChecked(False)
        self.ring.set_animated(config.GUI_ANIMATIONS and state in ("ready", "listening", "working", "starting"))
        self._refresh_system()

    def _on_problem(self, text):
        self._say_status(text)
        self._add_note(text)

    def _on_ended(self, outcome):
        if outcome == "quit":
            self.close()
        elif outcome == "sleep":
            self._add_note("Jarvis is asleep. Press START to wake him")
        elif outcome == "error":
            self._add_note("The session stopped because of an error. Open the LOG for details")
        if outcome != "quit":
            self._arm_wake()                                          # asleep again: listen for the wake word or the claps

    def _on_hands_free(self, on):
        self.hands_free_button.blockSignals(True)
        self.hands_free_button.setChecked(on)
        self.hands_free_button.blockSignals(False)
        self._refresh_system()

    def _say_status(self, text):
        self.status.setText(text)

    def _refresh_system(self):
        brain = "Claude, with tools" if config.ANTHROPIC_API_KEY else "Free local commands"
        listening = "Hands-free voice" if self.controller.hands_free else "Typed, or push to talk"
        self.system_values["Brain"].setText(brain)
        self.system_values["Input"].setText(listening)
        self.system_values["Voice"].setText("On" if config.TTS_ENABLED else "Off (text only)")
        self.system_values["User"].setText(config.USER_NAME)

    def _tick(self):
        now = QDateTime.currentDateTime()
        self.clock.setText(now.toString("HH:mm:ss"))
        self.date.setText(now.toString("dddd, d MMMM yyyy"))

    def closeEvent(self, event):
        self._closing = True
        ui_bridge.unregister("admin", self._admin_handler)
        if self.wake is not None:
            self.wake.disarm()
        self.clock_timer.stop()
        self.controller.stop()
        if self.music_button.isChecked():
            self._toggle_music(False)
        super().closeEvent(event)


def main(argv=None):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Jarvis")
    app.setStyleSheet(theme.STYLESHEET)
    _warm_up_voice()
    window = MainWindow(wake=WakeController() if config.INPUT_MODE == "voice" else None)
    window.show()
    return app.exec_()


def _warm_up_voice():
    """Load the natural voice, Whisper and the voice-lock model in the background while the window opens and the password is typed."""
    import speaker
    import speech
    import stt
    for load in (speech.warm_up, stt.warm_up, speaker.warm_up):
        try:
            load()
        except Exception:                                  # noqa: BLE001 - each of them reports its own trouble when it is used
            pass
