from config import BASE_DIR
from sound_player import playsound


def NotifySound():
    playsound(rf"{BASE_DIR}\DataBase\Sounds\notification.mp3")


def Startup():
    playsound(rf"{BASE_DIR}\DataBase\Sounds\Startup2.mp3")


def IronManMusic_1():
    playsound(rf"{BASE_DIR}\DataBase\Sounds\Iron Man Music.mp3")


def IronManMusic_2():
    playsound(rf"{BASE_DIR}\DataBase\Sounds\Iron Man.mp3")

