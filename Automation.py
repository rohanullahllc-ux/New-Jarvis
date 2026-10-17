from config import BASE_DIR
import webbrowser
import pyautogui
import keyboard
import time
import os
import webbrowser as web
from time import sleep
from plyer import notification
from pyautogui import click
from pyautogui import click
from MainCode import Speak
from MainCode import Listen
from keyboard import press
from keyboard import press_and_release
from pynput.keyboard import Key,Controller
from keyboard import write
from time import sleep

def WhatsAppMsg(name,msg):
    Name = str(name)
    Speak("Opeing Whatsapp web...")
    web.open("https://web.whatsapp.com/")
    Speak(f"Wait for some seconds I am sending the message to {Name} Khan...")
    sleep(50)
    if "masood" in Name:
        click(x=251, y=251)
        sleep(2)
        click(x=689, y=698)
        write(msg)
        press("enter")

        
def ChromeAuto(command):
    query = str(command)
    if 'new tab' in query:
        press_and_release('ctrl + t')
    elif 'close tab' in query:
        press_and_release('ctrl + w')
    elif 'new window' in query:
        press_and_release('ctrl + n')
    elif 'history' in query:
        press_and_release('ctrl + h')
    elif 'download' in query:
        press_and_release('ctrl + j')
    elif 'bookmark' in query:
        press_and_release('ctrl + d')
        press('enter')
    elif 'incognito' in query:
        press_and_release('Ctrl + Shift + n')
    elif 'switch tab' in query:
        tab = query.replace("switch tab ", "")
        Tab = tab.replace("to","")
        num = Tab
        bb = f'ctrl + {num}'
        press_and_release(bb)
    elif 'open' in query:
        name = query.replace("open ","")
        NameA = str(name)
        if 'youtube' in NameA:
            web.open("https://www.youtube.com/")
        elif 'instagram' in NameA:
            web.open("https://www.instagram.com/")
        else:
            string = "https://www." + NameA + ".com"
            string_2 = string.replace(" ","")
            web.open(string_2)


def YouTubeAuto(command):
    query = str(command)
    if 'pause' in query or 'stop' in query:
        press('space bar')
    elif 'resume' in query or 'play' in query:
        press('space bar')
    elif 'full screen' in query:
        press('f')
    elif 'exit' in query:
        press('esc')
    elif 'film screen' in query:
        press('t')
    elif 'skip' in query:
        press('l')
    elif 'back' in query:
        press('j')
    elif 'increase' in query:
        press_and_release('SHIFT + .')
    elif 'decrease' in query:
        press_and_release('SHIFT + ,')
    elif 'previous' in query:
        press_and_release('SHIFT + p')
    elif 'next' in query:
        press_and_release('SHIFT + n')
    elif 'search' in query:
        click(x=691, y=123)
        Speak("What To Search Sir ?")
        search = Listen()
        write(search)
        sleep(0.8)
        press('enter')
    elif 'mute' in query:
        press('m')
    elif 'unmute' in query:
        press('m')
    elif 'my channel' in query:
        web.open("https://www.youtube.com/channel/UC7A5u12yVIZaCO_uXnNhc5g")
    else:
        Speak("No Command Found!")


def WindiowsAuto(command):
    query = str(command)
    if 'home screen' in query:
        press_and_release('windows + m')
    elif 'minimize' in query:
        press_and_release('windows + m')
    elif 'show start' in query:
        press('windows')
    elif 'setting' in query:
        press_and_release('windows + i')
    elif 'search' in query:
        press_and_release('windows + s')
    elif 'snip' in query or 'sketch' in query:
        press_and_release('windows + SHIFT + s')
    elif 'restore windows' in  query:
        press_and_release('Windows + Shift + M')
    elif "lock" in query:
        press_and_release("windows + l")
    elif "quick menu" in query:
        press_and_release("windows + x")
    elif "switch window" in query:
        press_and_release("alt + tab")
    elif "virtual desktop" in query:
        press_and_release("windows + tab")
    elif "add" in query:
        press_and_release("windows + ctrl + d")
    elif "right" in query:
        press_and_release("Windows + Ctrl + Right arrow")
    elif "left" in query:
        press_and_release("Windows + Ctrl + Left arrow")
    elif "close" in query:
        press_and_release("windows + ctrl + f4")
    elif "action center" in query or "notification center" in query:
        press_and_release("windows + a")
    
    else:
        Speak("Sorry , No Command Found!")


def OpenApp(app_name):
    query = str(app_name)
    press_and_release("windows+s")
    sleep(1)
    write(query)
    sleep(2)
    press("enter")


def CloseApp(app_name):
    query = str(app_name)
    exe = query+".exe"
    os.system(f"TASKKILL /F /im {exe}")


def OpenBrowser(browser_name):
    query = str(browser_name)
    press_and_release("windows+s")
    sleep(1)
    write(query)
    sleep(2)
    press("enter")


def volumeup():
    keyboard = Controller()
    for i in range(5):
        keyboard.press(Key.media_volume_up)
        keyboard.release(Key.media_volume_up)
        sleep(0.1)


def volumedown():
    Keyboard = Controller()
    for i in range(5):
        Keyboard.press(Key.media_volume_down)
        Keyboard.release(Key.media_volume_down)
        sleep(0.1)


def HideFiles():
    Speak("Sir please specify a folder to hide the files...")
    f_dir = input("Write the path of the folder: ")
    os.system("attrib +h /s /d "+f_dir)
    Speak("Sir, all the files in this folder are now hidden")


def CopyAndPaste(Copy_File_Location,Final_Destination):
    os.system(f"copy {Copy_File_Location} {Final_Destination}")


def MoveAndPaste(Copy_File_Location,Final_Destination):
    os.system(f"move {Copy_File_Location} {Final_Destination}")


def ScreenShot():
    Speak("Sir, please tell me the name for the screenshot file")
    name = Listen()
    Speak("Please hold the screen for few seconds,sir,i am taking shot")
    time.sleep(3)
    img = pyautogui.screenshot()
    img.save(f"{BASE_DIR}\\DataBase\\ScreenShot\\{name}.png")
    Speak("i am done sir, screenshot is saved in main folder , now i am ready for next task")


def OnlinClass(Subject):
    Speak("Joining The Class Sir .")
    if 'science' in Subject:
        from DataBase.OnlineClasses.Links import Science
        Link = Science()
        webbrowser.open(Link)
        sleep(10)
        click(x=412, y=571)
        sleep(1)
        click(x=1011, y=443)
        Speak("Class Joined Sir .")

    elif 'mathematics' in Subject:
        from DataBase.OnlineClasses.Links import Maths
        Link = Maths()
        webbrowser.open(Link)
        sleep(10)
        click(x=412, y=571)
        sleep(1)
        click(x=1011, y=443)
        Speak("Class Joined Sir .")

    elif 'pakistan studies' in Subject:
        from DataBase.OnlineClasses.Links import sst
        Link = sst()
        webbrowser.open(Link)
        sleep(10)
        click(x=412, y=571)
        sleep(1)
        click(x=1011, y=443)
        Speak("Class Joined Sir .")

    elif 'english' in Subject:
        from DataBase.OnlineClasses.Links import English
        Link = English()
        webbrowser.open(Link)
        sleep(10)
        click(x=412, y=571)
        sleep(1)
        click(x=1011, y=443)
        Speak("Class Joined Sir .")

