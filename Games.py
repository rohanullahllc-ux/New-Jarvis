from config import RAPIDAPI_KEY
import requests
import webbrowser
from MainCode import Speak


def FreeToPlay(id):
    url = f"https://free-to-play-games-database.p.rapidapi.com/api/game"
    querystring = {"id":id}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "free-to-play-games-database.p.rapidapi.com"
    }
    response = requests.request("GET", url, headers=headers, params=querystring)
    Data = response.json()
    print(Data)
    Title = Data["title"]
    thumbnail = Data["thumbnail"]
    short_description = Data["short_description"]
    description = Data["description"]
    game_url = Data["game_url"]
    genre = Data["genre"]
    platform = Data["platform"]
    publisher = Data["publisher"]
    developer = Data["developer"]
    release_date = Data["release_date"]
    freetogame_profile_url = Data["freetogame_profile_url"]

    Speak("Title...")
    Speak(Title)
    webbrowser.open(thumbnail)
    Speak(short_description)
    Speak(description)
    Speak("genre...")
    Speak(genre)
    Speak(f"You can play this game on {platform}")
    Speak(f"The publisher of this game is {publisher}")
    Speak(f"This game was developed by {developer}")
    Speak(f"This game was released on {release_date}")
    Speak("You can see rating of this game")
    webbrowser.open(freetogame_profile_url)


def MineServersInfo(host):
    url = "https://minecraft-server-status1.p.rapidapi.com/servers/single/lite"

    payload = {"host": host}
    headers = {
	    "content-type": "application/json",
	    "X-RapidAPI-Key": RAPIDAPI_KEY,
	    "X-RapidAPI-Host": "minecraft-server-status1.p.rapidapi.com"
    }

    response = requests.request("POST", url, json=payload, headers=headers)
    Data = response.json()
    Host = Data["host"]
    Port = Data["port"]
    ServerType = Data["type"]
    TotalPlayers = Data["players"]
    Online = TotalPlayers["online"]
    Max = TotalPlayers["max"]
    AllVer = Data["version"]
    Ver = AllVer["name"]
    Prot = AllVer["protocol"]

    Speak("The host of this server is...")
    Speak(Host)
    Speak(f"On port {Port}")
    Speak(f"You need {ServerType} edition of minecraft for this server.")
    Speak(f"Total online players in this server are {Online}")
    Speak(f"and maximum players in this server are {Max}")
    Speak(Ver+" of minecraft is required for this server")
    
