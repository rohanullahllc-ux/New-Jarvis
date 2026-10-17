"""MP3/WAV playback with pygame, replacing the playsound package.

playsound 1.3.0 does not install on new Pythons and fails on paths with
spaces, so this keeps the same call: playsound(path, block=True).
"""
import time
from pygame import mixer


def playsound(path, block=True):
    if not mixer.get_init():
        mixer.init()
    mixer.music.load(str(path))
    mixer.music.play()
    while block and mixer.music.get_busy():
        time.sleep(0.1)
