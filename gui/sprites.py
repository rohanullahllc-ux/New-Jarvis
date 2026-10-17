"""Draws the animated artwork from the sprite sheets in gui/resources (built by make_assets.py)."""
import json
from pathlib import Path

from PyQt5.QtCore import QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QSizePolicy, QWidget

RESOURCES = Path(__file__).resolve().parent / "resources"


def load_meta():
    return json.loads((RESOURCES / "sprites.json").read_text(encoding="utf-8"))


class SpritePlayer(QWidget):
    """One looping animation, scaled to fit the widget. ``animate=False`` shows its first frame only."""

    def __init__(self, name, animate=True, parent=None):
        super().__init__(parent)
        meta = load_meta()[name]
        self.sheet = QImage(str(RESOURCES / meta["file"]))
        self.frames, self.columns = meta["frames"], meta["columns"]
        self.frame_size = QSize(*meta["size"])
        self.frame = 0
        self._animate = animate
        self._timer = QTimer(self)
        self._timer.setInterval(meta["frame_ms"])
        self._timer.timeout.connect(self.advance)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self):
        return self.frame_size

    def minimumSizeHint(self):
        return QSize(self.frame_size.width() // 3, self.frame_size.height() // 3)

    def frame_rect(self, number):
        column, row = number % self.columns, number // self.columns
        return QRectF(column * self.frame_size.width(), row * self.frame_size.height(),
                      self.frame_size.width(), self.frame_size.height())

    def advance(self):
        self.frame = (self.frame + 1) % self.frames
        self.update()

    def set_animated(self, on):
        self._animate = on
        if on and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def is_animating(self):
        return self._timer.isActive()

    def showEvent(self, event):
        if self._animate:
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()                       # nothing to draw, so nothing to spend CPU on
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        source = self.frame_rect(self.frame)
        size = self.frame_size.scaled(self.size(), Qt.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())
        painter.drawImage(target, self.sheet, source)
