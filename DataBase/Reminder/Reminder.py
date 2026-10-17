import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from config import BASE_DIR
from plyer import notification
import time
import pyttsx3
from pygame import mixer
import speech_recognition as sr
from microphone import Microphone

engine = pyttsx3.init('sapi5')
voices = engine.getProperty('voices')
engine.setProperty('voices',voices[0].id)

author = "Mr Khan"


def speak(audio):
    print(" ")
    print(f": {audio}")
    engine.say(audio)
    engine.runAndWait()
    print(" ")


def takeCommend():
    r = sr.Recognizer()
    with Microphone() as source:
        print(": Listening...")
        r.pause_threshold = 1.5
        audio = r.listen(source,timeout=5, phrase_time_limit=8)
    try:
        print(": Recognizing...")
        query = r.recognize_google(audio, language='en-in')
        print(f"User Said:{query} \n")
    except Exception as e:
        print(f"Sorry {author}, Say That again... ")
        return "None"
    return query.lower()


def Rem():
    speak('What shall I remind you about?')
    title = takeCommend()
    speak("For how many minutes? Please enter below :")
    local_time = float(input("Enter duration of timer in minutes :"))
    local_time = local_time * 60
    exe_time = local_time / 60
    if local_time == 60.0 :
        speak(f'Reminder set for {local_time} seconds')
        time.sleep(local_time)
        speak(f'Reminder over named {title}, setted for {local_time} seconds')
        mixer.init()
        mixer.music.load(rf"{BASE_DIR}\DataBase\Sounds\notification.mp3")
        mixer.music.play()
        notification.notify(
                title = title,
                message ="Please see to your reminder",
                timeout = 10)
    elif local_time < 60.0:
        speak(f'Reminder set for {local_time} seconds')
        time.sleep(local_time)
        speak(f'Reminder over named {title}, setted for {local_time} seconds')
        mixer.init()
        mixer.music.load(rf"{BASE_DIR}\DataBase\Sounds\notification.mp3")
        mixer.music.play()
        notification.notify(
                title = title,
                message ="Please see to your reminder",
                timeout = 10)
    elif local_time > 60.0:
        speak(f'Reminder set for {exe_time} minutes')
        time.sleep(local_time)
        speak(f'Reminder over named {title}, setted for {exe_time} minutes')
        mixer.init()
        mixer.music.load(rf"{BASE_DIR}\DataBase\Sounds\notification.mp3")
        mixer.music.play()
        notification.notify(
                title = title,
                message ="Please see to your reminder",
                timeout = 10)


Rem()