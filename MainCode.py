from config import BASE_DIR, WOLFRAM_APP_ID, DEFAULT_CITY
import wolframalpha
import time
import wikipedia
import webbrowser
import datetime
import requests
import socket
import psutil
import platform
import math
import os
import re
import speech_recognition as sr
from microphone import listen
from bs4 import BeautifulSoup
from plyer import notification
from colored import fg, attr

client = wolframalpha.Client(WOLFRAM_APP_ID) if WOLFRAM_APP_ID else None

# Color Detection:
reset = attr('reset')
red = fg('red')
green = fg('green')
blue = fg('blue')
yellow = fg('yellow')

# Basic Details:

UserName = "Mr Khan"
BotName = "AI-Jarvis-M-2.O"

from speech import Speak  # noqa: E402,F401  (kept importable from here for the legacy modules)


def Listen():
    return listen()


def wishMe():
    hour = int(datetime.datetime.now().hour)
    if hour >= 6 and hour < 12:
        print(yellow+f"Good Morning, Sir"+reset)
        Speak(f"Good Morning {UserName}")
    elif hour >= 12 and hour < 18:
        print(yellow+f"Good Afternoon, Sir"+reset)
        Speak(f"Good Afternoon {UserName}")
    elif hour >= 18 and hour < 24:
        print(yellow+f"Good Evening, Sir"+reset)
        Speak(f"Good Evening {UserName}")
    else:
        print(yellow+f"Good Night, Sir"+reset)
        Speak(f"Good Night {UserName}")


def StartupTime():
    strTime = datetime.datetime.now().strftime("%H")
    strTime2 = datetime.datetime.now().strftime("%M")
    strTime = int(strTime)
    strTime2 = int(strTime2)
    Speak(f"Sir, right now the time is {strTime}:{strTime2}")


def Date():
    Date = datetime.datetime.now()
    Date = Date.strftime("%d")
    Speak(f"Todays date is {Date}")


def Year():
    year = datetime.datetime.now()
    year = year.strftime("%Y")
    Speak(f"The current year is {year}")


def tellDay():
    day = datetime.datetime.today().weekday() + 1

    Day_dict = {1: 'Monday', 2: 'Tuesday',
                3: 'Wednesday', 4: 'Thursday',
                5: 'Friday', 6: 'Saturday',
                7: 'Sunday'}

    if day in Day_dict.keys():
        day_of_the_week = Day_dict[day]
        Speak("The day is " + day_of_the_week)


def Sweather():
    from JarvisAdvancedBot.tools import weather_report
    try:
        Speak(weather_report(DEFAULT_CITY))
    except Exception:
        Speak(" City Not Found ")


def Temp():
    # Scraped a specific Google results class that no longer exists on the page,
    # so this always failed. Sweather() above already gives real weather via a
    # proper API - this is kept only so old callers don't break, and never crashes.
    try:
        search = "temperature in peshawar"
        url = f"https://www.google.com/search?q={search}"
        r = requests.get(url, timeout=10)
        data = BeautifulSoup(r.text, "html.parser")
        temp = data.find('div', class_='BNeawe').text
        Speak(f"Sir the temperature in the room is {temp}")
    except Exception:
        Speak("I couldn't read that from Google, sir. I already gave you the weather above.")

    
SLEEP_COMMAND = re.compile(r"(?:you can |go to |take (?:a )?)?(?:sleep|rest)(?: mode)?(?: now)?")
STOP_COMMAND = re.compile(r"(?:quit|exit|terminate|good ?bye|bye)(?: jarvis)?")
RESET_COMMAND = re.compile(r"(?:start (?:a )?)?new conversation|forget everything|(?:clear|reset) (?:your |the )?memory")


def ask_user(question):
    """Ask a follow-up question and return the answer (spoken or typed)."""
    Speak(question)
    return Listen()


def handle_command(query, ask=None):
    """Carry out one command. Returns "sleep" or "quit" when the session should end, else None."""
    # Legacy feature modules, imported lazily so the dispatcher can be loaded (and tested) quickly.
    # Removed once every feature lives in JarvisAdvancedBot/tools (Phase 8).
    from System import (VirtualRam, AvailableRam, SysInfo, CpuInfo,
                        DiskInfo, MemoryInfo, IPAddress)
    from JarvisAdvancedBot.JarvisAiBrain import ReplyBrain, ResetBrain, ai_available
    from JarvisAdvancedBot.LocalBrain import LocalReply
    use_ai = ai_available()
    ask = ask or ask_user

    command = query.replace("jarvis", "").strip()

    if len(query)<3:
        pass

    elif STOP_COMMAND.fullmatch(command):
        Speak("Goodbye, sir.")
        return "quit"

    elif SLEEP_COMMAND.fullmatch(command):
        Speak("Going to sleep, sir. Say a wake word when you need me.")
        return "sleep"

    elif use_ai and RESET_COMMAND.fullmatch(command):
        ResetBrain()
        Speak("Fresh start, sir. I've cleared our conversation.")

    elif use_ai:
        Speak(ReplyBrain(query))

    elif (reply := LocalReply(query, ask)) is not None:
        Speak(reply)

    elif "translate" in query:
        from Features import Trans
        Trans()

    elif "read" in query or "a book" in query:
        from Features import Reader
        Speak("Sir which book should I read...")
        BookN = Listen()
        Reader(BookN)

    elif "generate password" in query:
        from Features import GenPass
        GenPass()
        
    elif "show my" in query:
        query = query.replace("jarvis ","")
        query = query.replace("show my ","")
        query = query.replace("password","")
        query = query.replace(" ","")
        try:
            os.startfile(rf"{BASE_DIR}\DataBase\Passwords\{query}.txt")
        except FileNotFoundError as e:
            print(e)
            Speak(f"File {query} does not exist...")

    elif "crack" in query:
        from Features import PassCrack
        PassCrack()

    elif "time table" in query:
        from Features import TimeTable
        TimeTable()

    elif "todo list" in query:
        from Features import SheduleDay
        SheduleDay()

    elif "my todo" in query:
        Speak("For which date please mention below...")
        ddddd = input("Enter Date:- ")
        from Features import DateConverter
        dddddd = DateConverter(ddddd)
        from Features import ShowShedule
        ShowShedule(dddddd)

    elif "start writing" in query:
        from Features import Notepad
        Notepad()

    elif "close it" in query:
        from Features import CloseNotepad
        CloseNotepad()

    elif "take note" in query:
        from Features import NoteTake
        NoteTake()

    elif "reminder" in query:
        os.startfile(rf"{BASE_DIR}\DataBase\Reminder\Reminder.py")

    elif "instagram profile" in query:
        from Features import downInstaPro
        downInstaPro()

    elif "acronym" in query:
        from Features import Acro
        Acro()

    elif "calculate" in query:
        from Features import calculate
        query = query.replace("jarvis", "")
        query = query.replace(" calculate", "")
        query = query.replace("plus", "+")
        query = query.replace("multiply", "*")
        query = query.replace("minus", "-")
        query = query.replace("divide by", "/")
        calculate(query)

    elif "calculator" in query:
        Speak("Opening Calculator...")
        os.startfile(rf"{BASE_DIR}\DataBase\Gui Programs\Calculator.py")

    elif "calender" in query:
        Speak("Opening Calendar...")
        os.startfile(rf"{BASE_DIR}\DataBase\Gui Programs\Calendar_gui.py")

    elif "currency convertor" in query:
        Speak("Opening Currency Convertor...")
        os.startfile(rf"{BASE_DIR}\DataBase\Gui Programs\Currency_convertor_GUI.py")

    elif "joke" in query:
        from Features import get_random_joke
        get_random_joke()

    elif "funny joke" in query:
        from Features import tellJoke
        tellJoke()

    elif "advise" in query or "advice" in query:
        from Features import get_random_advice
        get_random_advice()

    elif 'search wikipedia' in query:
        try:
            Speak('Sir, What should I search on wikipedia')
            Search = Listen()
            webbrowser.open(f"https://www.google.com/search?q={Search}")
            results = wikipedia.summary(Search, sentences=4)
            Speak("According to Wikipedia")
            Speak(results)
        except Exception as e:
            Speak("Sir I am getting information from internet...")
            time.sleep(2)
            import pywhatkit as kit
            kit.search(Search)
            try:
                search = wikipedia.summary(Search, 2)
                Speak(f": According To Your Search : {search}")
            except:
                Speak("Sir I did not get what did you say but I am searching it in google...")
                kit.search(Search)

    elif "weather update" in query:
        query = query.replace("jarvis ", "")
        query = query.replace("tell me ", "")
        query = query.replace("weather ", "")
        query = query.replace("update for ", "")
        from Features import weather_city
        weather_city(query)

    elif "tell me the weather in" in query or "tell me today's weather in" in query:
        query = query.replace("jarvis ", "")
        query = query.replace("tell me ", "")
        query = query.replace("weather in ", "")
        query = query.replace("today's ", "")
        query = query.replace("weather in ", "")
        from Features import weather_news
        weather_news(query)

    elif "fact" in query:
        from Features import RandFact
        RandFact()

    elif "activity" in query or "bore" in query:
        from Features import RandActivity
        RandActivity()

    elif "dog images" in query:
        from Features import DogImg
        DogImg()

    elif "hack" in query:
        from Features import HackRandom
        HackRandom()

    elif "set alarm" in query:
        from Features import Alarm
        Alarm(query)

    elif "this video" in query:
        from Features import DownloadYouTube
        time.sleep(2)
        DownloadYouTube()

    elif "my location" in query or "where i am" in query:
        from Internet import My_Location
        My_Location()

    elif "corona updates" in query or "corona news" in query:
        from Internet import CoronaVirus
        Speak("For which Country...")
        count = Listen()
        CoronaVirus(count)

    elif "search location" in query or "track" in query:
        query = query.replace("jarvis ","")
        query = query.replace("track ","")
        query = query.replace("search for ","")
        query = query.replace("search location ","")
        from Internet import GoogleMaps
        GoogleMaps(query)

    elif 'question' in query or "query" in query:
        Speak('tell me the question you want to get')
        question = Listen()
        Speak('getting information boss')
        try:
            try:
                results = wikipedia.summary(question, sentences=2)
                Speak(results)
            except:
                res = client.query(question)
                results = next(res.results).text
                Speak(results)
        except:
            Speak("Sorry sir i didn't get it")
    
    elif 'how to' in query:
        import pywikihow
        Speak("Getting Data From The Internet !")
        op = query.replace("jarvis","")
        max_result = 1
        how_to_func = pywikihow.search_wikihow(op,max_result)
        assert len(how_to_func) == 1
        how_to_func[0].print()
        Speak(how_to_func[0].summary)

    elif "google search" in query:
        from Internet import GoogleSearch
        query = query.replace("jarvis ", "")
        query = query.replace("google search ", "")
        GoogleSearch(query)

    elif "youtube search" in query:
        from Internet import YouTubeSearch
        query = query.replace("jarvis ", "")
        query = query.replace("youtube search ", "")
        YouTubeSearch(query)

    elif "nasa news" in query:
        Speak("Tell me the date required for news extraction process...")
        date = Listen()
        from Features import DateConverter
        Con_date = DateConverter(date)
        from Nasa import NasaNews
        try:
            NasaNews(Con_date)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "mars images" in query:
        from Nasa import MarsImage
        try:
            MarsImage()
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "solar bodies" in query:
        from Nasa import SolarBodies
        Speak("Sir about which solar body...")
        body = Listen()
        try:
            SolarBodies(body)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "astroids" in query or "near earth" in query or "astroids" in query:
        from Nasa import Astro
        from Features import DateConverter
        Speak("Tell Me The Starting Date .")
        start = input("Starting date> ")
        start_date = DateConverter(start)
        Speak("And Tell Me The End Date .")
        end = input("Ending date> ")
        end_date = DateConverter(end)
        Speak("Extracting data from nasa...")
        try:
            Astro(start_date, end_date=end_date)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "landpads" in query or "land pads" in query:
        from SpaceX import GetLandPadInfo
        Speak("Sir please tell me landpad id needed for extraction process...")
        iD = input("Enter the landpad id> ")
        try:
            GetLandPadInfo(iD)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "missions" in query:
        from SpaceX import SpaceXMission
        Speak("For which mission id you want to find information...")
        MiD = input("Enter the mission id> ")
        try:
            SpaceXMission(MiD)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "spacex" in query:
        from SpaceX import SpaceXInfo
        try:
            SpaceXInfo()
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "roadster" in query:
        from SpaceX import RoadsterInfo
        try:
            RoadsterInfo()
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "historical events" in query:
        from SpaceX import HistoricalEevents
        Speak("Sir please tell event id needed for extraction process...")
        HisId = input("Enter the event ID> ")
        try:
            HistoricalEevents(HisId)
        except Exception as e:
            print(e)
            Speak("No speakable data found on database...")

    elif "price" in query:
        query = query.replace("jarvis ", "")
        query = query.replace("tell me ", "")
        query = query.replace("tell me ", "")
        query = query.replace("current ", "")
        query = query.replace("price", "")
        query = query.replace(" of ", "")
        from Business import get_latest_crypto_price
        try:
            get_latest_crypto_price(query)
        except Exception as e:
            print(e)
            Speak("I faced some issues for fetching information...")
            Speak("It might be network issue...")

    elif "business" in query:
        from Business import BusinessNameGenerator
        query = query.replace("jarvis ", "")
        query = query.replace("tell me ", "")
        query = query.replace("a name ", "")
        query = query.replace("for my", "")
        try:
            BusinessNameGenerator(query)
        except Exception as e:
            print(e)
            Speak("I faced some issues for fetching information...")
            Speak("It might be network issue...")

    elif "price" in query or "rates" in query:
        from Business import CurrencyExchangeRates
        try:
            CurrencyExchangeRates()
        except Exception as e:
            print(e)
            Speak("I faced some issues for fetching information...")
            Speak("It might be network issue...")

    elif "free games" in query or "free game" in query:
        query = query.replace("jarvis ", "")
        query = query.replace("tell me a ", "")
        query = query.replace("free games", "")
        query = query.replace("free game", "")
        query = query.replace(" for id ", "")
        from Games import FreeToPlay
        try:
            FreeToPlay(query)
        except Exception as e:
            print(e)
            Speak("I faced some issues for fetching information...")
            Speak("It might be network issue...")

    elif "server" in query:
        from Games import MineServersInfo
        try:
            Speak("Tell me the host required for fetching information...")
            Host = input("Input host> ")
            MineServersInfo(Host)
        except Exception as e:
            print(e)
            Speak("I faced some issues for fetching information...")
            Speak("It might be network issue...")

    elif 'local disk d' in query:
        Speak("opening local disk D")
        webbrowser.open("D://")

    elif 'local disk c' in query:
        Speak("opening local disk C")
        webbrowser.open("C://")

    elif "virtual memory" in query:
        VirtualRam()
        
    elif "available memory" in query:
        AvailableRam()

    elif "system information" in query or "system details" in query:
        SysInfo()
        
    elif "cpu information" in query or "cpu details" in query:
        CpuInfo()
        
    elif "system power" in query:
        Speak("What do you want to do with the system, shutdown, restart or sleep...")
        ss = Listen()
        if "shutdown" in ss:
            os.system("shutdown /s /t 10")
        elif "restart" in ss:
            os.system("shutdown /r /t 10")
        elif "sleep" in ss:
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        else:
            Speak("Ok sir, cancelled...")


    elif "drives information" in query or "drives details" in query:
        DiskInfo()
        
    elif "memory information" in query or "memory details" in query:
        MemoryInfo()

    elif "ip address" in query:
        IPAddress()

    elif "send email" in query:
        from Internet import SendEmail
        SendEmail()
        
    elif "fetch wifi" in query or "wifi" in query or "wi-fi" in query:
        from Internet import WifiPassSender
        WifiPassSender()

    elif 'new folder' in query:
        from Features import NewFolder
        query = query.replace("jarvis ", "")
        query = query.replace("make ", "")
        query = query.replace("new folder ", "")
        NewFolder(query)

    else:
        Speak("Sorry sir, I don't know how to do that yet. Say 'what can you do' to hear my skills.")



def _announce_brain():
    from JarvisAdvancedBot.JarvisAiBrain import ai_available
    print(": Brain:", "Claude (natural speech)" if ai_available() else "free local commands (no Anthropic API key)")


def taskExe():
    """Run one session: greet, then handle commands until the user says sleep or quit.

    Returns "sleep" or "quit" so the launcher knows whether to go back to listening for
    the wake word or to exit.
    """
    from System import system_stats, username, check_int, IPAddress

    wishMe()
    Date()
    tellDay()
    Year()
    StartupTime()
    system_stats()
    username()
    check_int()
    Speak("Checking for your current ip address...")
    IPAddress()
    Sweather()
    Speak("Checking the room temperature...")
    Temp()
    from Features import TimeTable as ShowTimeTable
    ShowTimeTable()
    _announce_brain()

    Speak("Now I am ready for your command")
    while True:
        try:
            outcome = handle_command(str(Listen()))
            if outcome in ("sleep", "quit"):
                return outcome
        except Exception as e:  # one broken feature shouldn't stop Jarvis
            print(f": Error: {e}")
            Speak("Sorry sir, something went wrong with that command.")
