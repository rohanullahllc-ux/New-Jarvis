"""Tools Claude can use to fetch live information and act on this PC.

Each tool returns a short plain-text result for Claude, which then words the
spoken reply. Nothing here speaks or listens itself.
"""
import datetime
import os
import re
import secrets
import string
import subprocess
import threading
import time
import webbrowser
from typing import Literal
from urllib.parse import quote, quote_plus

import psutil
import requests
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from config import BASE_DIR, NASA_API_KEY

DB = BASE_DIR / "DataBase"
HTTP_TIMEOUT = 10
WIKI_HEADERS = {"User-Agent": "JarvisAssistant/2.0 (personal voice assistant)"}  # Wikipedia blocks anonymous clients


def _get_json(url, headers=None, **params):
    try:
        response = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as e:
        raise ToolError(f"The online service did not respond ({e.__class__.__name__}).")


def _safe_filename(name):
    return re.sub(r"[^\w -]", "", name).strip()[:60]


def _folder(name):
    folder = DB / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


CURRENCY_NAMES = {
    "USD": "US dollars", "PKR": "Pakistani rupees", "INR": "Indian rupees", "EUR": "euros", "GBP": "British pounds",
    "SAR": "Saudi riyals", "AED": "UAE dirhams", "JPY": "Japanese yen", "CNY": "Chinese yuan", "TRY": "Turkish lira",
    "CAD": "Canadian dollars", "AUD": "Australian dollars", "AFN": "Afghanis", "BDT": "Bangladeshi taka",
    "MYR": "Malaysian ringgit", "QAR": "Qatari riyals", "KWD": "Kuwaiti dinars",
}


def _money(amount, code):
    """Format an amount the way it should be spoken, e.g. "27,698 Pakistani rupees"."""
    text = f"{amount:,.0f}" if amount >= 100 else f"{amount:,.2f}" if amount >= 1 else f"{amount:.4g}"
    return f"{text} {CURRENCY_NAMES.get(code.upper(), code.upper())}"


# ---------------------------------------------------------------- information

@beta_tool
def get_current_datetime() -> str:
    """Get the current local date, day of the week and time on this PC."""
    return datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers",
    82: "violent rain showers", 95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with hail",
}


def weather_report(city):
    """Current weather and today's forecast for a city, from Open-Meteo (no API key needed)."""
    places = _get_json("https://geocoding-api.open-meteo.com/v1/search", name=city, count=1).get("results")
    if not places:
        raise ToolError(f"I couldn't find a place called {city}.")
    place = places[0]
    data = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        latitude=place["latitude"], longitude=place["longitude"], timezone="auto", forecast_days=1,
        current="temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    )
    now, today = data["current"], data["daily"]
    report = (
        f"{place['name']}, {place.get('country', '')}: {WEATHER_CODES.get(now['weather_code'], 'unknown conditions')}, "
        f"{now['temperature_2m']} degrees Celsius, feels like {now['apparent_temperature']}, "
        f"humidity {now['relative_humidity_2m']} percent, wind {now['wind_speed_10m']} km/h. "
        f"Today's high {today['temperature_2m_max'][0]}, low {today['temperature_2m_min'][0]}."
    )
    rain = today.get("precipitation_probability_max", [None])[0]
    if rain is not None:
        report += f" {rain} percent chance of rain."
    return report


@beta_tool
def get_weather(city: str) -> str:
    """Get the current weather and today's forecast for a city.

    Args:
        city: City name, e.g. "Peshawar" or "London".
    """
    return weather_report(city)


@beta_tool
def search_wikipedia(topic: str) -> str:
    """Look up a topic on Wikipedia and return a short summary. Use it for facts you are unsure of or that may have changed.

    Args:
        topic: What to look up.
    """
    results = _get_json("https://en.wikipedia.org/w/api.php", headers=WIKI_HEADERS, action="query",
                        list="search", srsearch=topic, srlimit=1, format="json").get("query", {}).get("search")
    if not results:
        raise ToolError(f"Nothing found on Wikipedia for {topic}.")
    title = results[0]["title"]
    page = _get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe=""),
                     headers=WIKI_HEADERS)
    if page.get("type") == "disambiguation":
        return f"{title} could mean several different things; ask about one of them more specifically."
    return page.get("extract") or f"Wikipedia has a page on {title} but no summary."


@beta_tool
def get_crypto_price(coin: str, currency: str = "usd") -> str:
    """Get the live price of a cryptocurrency and its change over the last 24 hours.

    Args:
        coin: Coin name or symbol, e.g. "bitcoin", "ETH", "dogecoin".
        currency: Currency code for the price, e.g. "usd", "pkr", "eur".
    """
    coins = _get_json("https://api.coingecko.com/api/v3/search", query=coin).get("coins")
    if not coins:
        raise ToolError(f"I couldn't find a coin called {coin}.")
    found, cur = coins[0], currency.lower()
    price = _get_json("https://api.coingecko.com/api/v3/simple/price",
                      ids=found["id"], vs_currencies=cur, include_24hr_change="true").get(found["id"], {})
    if cur not in price:
        raise ToolError(f"No {currency.upper()} price available for {found['name']}.")
    change = price.get(f"{cur}_24h_change")
    result = f"{found['name']} is {_money(price[cur], cur)}"
    if change is not None:
        result += f", {'up' if change >= 0 else 'down'} {abs(change):.1f} percent in the last 24 hours"
    return result + "."


@beta_tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert money between currencies at today's exchange rate.

    Args:
        amount: How much money to convert.
        from_currency: Three-letter code of the currency you have, e.g. "USD".
        to_currency: Three-letter code to convert into, e.g. "PKR".
    """
    data = _get_json(f"https://open.er-api.com/v6/latest/{from_currency.upper()}")
    rate = data.get("rates", {}).get(to_currency.upper())
    if data.get("result") != "success" or rate is None:
        raise ToolError(f"I couldn't get a rate from {from_currency} to {to_currency}.")
    return f"{_money(amount, from_currency)} is {_money(amount * rate, to_currency)}."


@beta_tool
def get_my_location() -> str:
    """Find roughly where this PC is, at city level, from its internet connection."""
    geo = _get_json("https://get.geojs.io/v1/ip/geo.json")
    return f"Approximately {geo.get('city', 'an unknown city')}, {geo.get('region', '')}, {geo.get('country', '')}."


@beta_tool
def get_system_status() -> str:
    """Get this PC's battery level, CPU and memory use, free disk space and uptime."""
    parts = []
    battery = psutil.sensors_battery()
    if battery:
        parts.append(f"battery {battery.percent:.0f} percent, {'charging' if battery.power_plugged else 'on battery'}")
    memory = psutil.virtual_memory()
    parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f} percent")
    parts.append(f"memory {memory.percent:.0f} percent used of {memory.total / 2**30:.0f} GB")
    root = os.path.abspath(os.sep)
    disk = psutil.disk_usage(root)
    parts.append(f"drive {root[:2]} has {disk.free / 2**30:.0f} GB free of {disk.total / 2**30:.0f} GB")
    uptime = datetime.timedelta(seconds=int(time.time() - psutil.boot_time()))
    parts.append(f"running for {uptime}")
    return "; ".join(parts)


@beta_tool
def nasa_picture_of_the_day(date: str = "") -> str:
    """Open NASA's Astronomy Picture of the Day and get its title and explanation.

    Args:
        date: Date as YYYY-MM-DD, or empty for today.
    """
    params = {"api_key": NASA_API_KEY, **({"date": date} if date else {})}
    data = _get_json("https://api.nasa.gov/planetary/apod", **params)
    webbrowser.open(data.get("hdurl") or data["url"])
    return f"Opened '{data['title']}' from {data['date']}. NASA's explanation: {data['explanation']}"


# ---------------------------------------------------------------- web & media

@beta_tool
def open_website(url: str) -> str:
    """Open a website in the default browser.

    Args:
        url: Web address, e.g. "https://github.com". A bare name like "github" opens github.com.
    """
    if "://" not in url:
        url = "https://" + (url if "." in url else f"www.{url.replace(' ', '')}.com")
    if not url.startswith(("http://", "https://")):
        raise ToolError("Only web addresses can be opened.")
    webbrowser.open(url)
    return f"Opened {url}"


@beta_tool
def search_google(query: str) -> str:
    """Show Google search results in the browser. Use when the user wants to see results on screen.

    Args:
        query: What to search for.
    """
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
    return f"Opened Google results for {query}"


@beta_tool
def youtube(query: str, play: bool = True) -> str:
    """Play a video or song on YouTube, or show YouTube search results.

    Args:
        query: Video, song or topic.
        play: True to start playing the best match, False to just show search results.
    """
    if play:
        try:
            import pywhatkit
            pywhatkit.playonyt(query)
            return f"Playing {query} on YouTube"
        except Exception:
            pass  # fall back to the results page
    webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(query))
    return f"Opened YouTube results for {query}"


MEDIA_KEYS = {
    "play_pause": "media_play_pause", "next_track": "media_next", "previous_track": "media_previous",
    "mute": "media_volume_mute", "volume_up": "media_volume_up", "volume_down": "media_volume_down",
}


@beta_tool
def media_control(action: Literal["play_pause", "next_track", "previous_track", "mute", "volume_up", "volume_down"],
                  times: int = 1) -> str:
    """Press a media or volume key. Works with YouTube, Spotify and most players.

    Args:
        action: Which key to press.
        times: Number of presses. Each volume press changes the volume by about 2 percent, so use 5 for a noticeable change.
    """
    from pynput.keyboard import Controller, Key
    keys, key = Controller(), getattr(Key, MEDIA_KEYS[action])
    times = max(1, min(times, 50))
    for _ in range(times):
        keys.press(key)
        keys.release(key)
        time.sleep(0.05)
    return f"Pressed {action.replace('_', ' ')} {times} time(s)"


YOUTUBE_KEYS = {
    "fullscreen": "f", "theater_mode": "t", "forward_10_seconds": "l", "back_10_seconds": "j",
    "captions": "c", "faster": "shift+.", "slower": "shift+,", "next_video": "shift+n", "previous_video": "shift+p",
}


@beta_tool
def youtube_control(action: Literal["fullscreen", "theater_mode", "forward_10_seconds", "back_10_seconds",
                                    "captions", "faster", "slower", "next_video", "previous_video"]) -> str:
    """Use a YouTube keyboard shortcut on the YouTube tab that is currently in front.

    Args:
        action: Which shortcut to use.
    """
    import keyboard
    keyboard.send(YOUTUBE_KEYS[action])
    return f"Sent YouTube shortcut: {action.replace('_', ' ')}"


# ---------------------------------------------------------------- apps & Windows

PROTECTED_PROCESSES = {"explorer", "svchost", "csrss", "winlogon", "lsass", "services", "smss", "wininit",
                       "dwm", "system", "python", "pythonw", "py", "conhost", "code"}


@beta_tool
def open_app(name: str) -> str:
    """Open an installed program or Windows app by name, the same as typing it into the Start menu.

    Args:
        name: App name as it appears in the Start menu, e.g. "chrome", "spotify", "calculator".
    """
    if not re.fullmatch(r"[\w .+-]{1,40}", name):
        raise ToolError("App names may only contain letters, numbers, spaces, dots, plus and minus signs.")
    import keyboard
    keyboard.send("windows")
    time.sleep(0.8)
    keyboard.write(name, delay=0.02)
    time.sleep(1.5)
    keyboard.send("enter")
    return f"Opened {name} from the Start menu"


@beta_tool
def close_app(name: str) -> str:
    """Close a running program.

    Args:
        name: Program name, e.g. "chrome", "notepad", "spotify".
    """
    target = name.strip().lower().removesuffix(".exe")
    if target in PROTECTED_PROCESSES:
        raise ToolError(f"{name} is part of Windows or of Jarvis itself, so I won't close it.")
    closed = 0
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower().removesuffix(".exe") == target:
            try:
                process.terminate()
                closed += 1
            except psutil.Error:
                pass
    if not closed:
        raise ToolError(f"No running program called {name}.")
    return f"Closed {name} ({closed} process{'es' if closed > 1 else ''})"


WINDOWS_SHORTCUTS = {
    "show_desktop": "windows+d", "minimize_all": "windows+m", "restore_windows": "windows+shift+m",
    "open_settings": "windows+i", "file_explorer": "windows+e", "start_menu": "windows",
    "lock_screen": "windows+l", "task_view": "windows+tab", "switch_window": "alt+tab",
    "snip_screen": "windows+shift+s", "action_center": "windows+a", "quick_link_menu": "windows+x",
    "new_virtual_desktop": "windows+ctrl+d", "next_virtual_desktop": "windows+ctrl+right",
    "previous_virtual_desktop": "windows+ctrl+left", "close_virtual_desktop": "windows+ctrl+f4",
}


@beta_tool
def windows_action(action: Literal["show_desktop", "minimize_all", "restore_windows", "open_settings",
                                   "file_explorer", "start_menu", "lock_screen", "task_view", "switch_window",
                                   "snip_screen", "action_center", "quick_link_menu", "new_virtual_desktop",
                                   "next_virtual_desktop", "previous_virtual_desktop", "close_virtual_desktop"]) -> str:
    """Do a Windows action using its keyboard shortcut.

    Args:
        action: Which action to do.
    """
    import keyboard
    keyboard.send(WINDOWS_SHORTCUTS[action])
    return f"Done: {action.replace('_', ' ')}"


BROWSER_SHORTCUTS = {
    "new_tab": "ctrl+t", "close_tab": "ctrl+w", "reopen_closed_tab": "ctrl+shift+t", "next_tab": "ctrl+tab",
    "previous_tab": "ctrl+shift+tab", "new_window": "ctrl+n", "incognito_window": "ctrl+shift+n",
    "history": "ctrl+h", "downloads": "ctrl+j", "bookmark_page": "ctrl+d", "refresh": "f5",
    "zoom_in": "ctrl+=", "zoom_out": "ctrl+-", "reset_zoom": "ctrl+0",
}


@beta_tool
def browser_action(action: Literal["new_tab", "close_tab", "reopen_closed_tab", "next_tab", "previous_tab",
                                   "new_window", "incognito_window", "history", "downloads", "bookmark_page",
                                   "refresh", "zoom_in", "zoom_out", "reset_zoom"]) -> str:
    """Use a keyboard shortcut in the web browser that is currently in front (Chrome, Edge or Firefox).

    Args:
        action: Which shortcut to use.
    """
    import keyboard
    keyboard.send(BROWSER_SHORTCUTS[action])
    if action == "bookmark_page":
        time.sleep(0.5)
        keyboard.send("enter")
    return f"Done: {action.replace('_', ' ')}"


@beta_tool
def take_screenshot(name: str = "") -> str:
    """Take a screenshot of the whole screen and save it in the ScreenShot folder.

    Args:
        name: Optional file name without extension.
    """
    import pyautogui
    folder = _folder("ScreenShot")
    name = _safe_filename(name) or datetime.datetime.now().strftime("screenshot-%Y%m%d-%H%M%S")
    pyautogui.screenshot().save(folder / f"{name}.png")
    return f"Saved the screenshot as {name}.png"


# ---------------------------------------------------------------- productivity

@beta_tool
def take_note(text: str, title: str = "") -> str:
    """Save a note as a text file in the Notes folder.

    Args:
        text: What the note says.
        title: Short title, used as the file name.
    """
    folder = _folder("Notes")
    now = datetime.datetime.now()
    name = _safe_filename(title) or now.strftime("note-%Y%m%d-%H%M%S")
    (folder / f"{name}.txt").write_text(f"{now:%A, %d %B %Y, %I:%M %p}\n\n{text}\n", encoding="utf-8")
    return f"Saved note '{name}'"


@beta_tool
def read_notes(title: str = "") -> str:
    """List the saved notes, or read one of them.

    Args:
        title: Title of the note to read, or empty to list the most recent notes.
    """
    folder = DB / "Notes"
    notes = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    if not notes:
        return "There are no saved notes."
    if not title:
        return "Recent notes: " + ", ".join(p.stem for p in notes[:10])
    match = next((p for p in notes if title.lower() in p.stem.lower()), None)
    if match is None:
        raise ToolError(f"No note matching {title}. Notes: " + ", ".join(p.stem for p in notes[:10]))
    return f"{match.stem}: {match.read_text(encoding='utf-8', errors='replace')[:2000]}"


def _task_file(day):
    return DB / "Tasks" / f"{day.isoformat()}-Task.txt"


def _parse_day(date):
    try:
        return datetime.date.fromisoformat(date) if date else datetime.date.today()
    except ValueError:
        raise ToolError("Dates must look like YYYY-MM-DD.")


def _read_tasks(day):
    path = _task_file(day)
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


@beta_tool
def add_task(task: str, date: str = "") -> str:
    """Add an item to the to-do list.

    Args:
        task: What needs doing.
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    path = _task_file(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(task.strip() + "\n")
    return f"Added to the list for {day:%A %d %B}: {task}"


@beta_tool
def list_tasks(date: str = "") -> str:
    """Read the to-do list.

    Args:
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    tasks = _read_tasks(day)
    if not tasks:
        return f"The to-do list for {day:%A %d %B} is empty."
    return f"To-do list for {day:%A %d %B}: " + "; ".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))


@beta_tool
def remove_task(number: int, date: str = "") -> str:
    """Remove a finished item from the to-do list.

    Args:
        number: The item's number, as given by list_tasks.
        date: Day as YYYY-MM-DD, or empty for today.
    """
    day = _parse_day(date)
    tasks = _read_tasks(day)
    if not 1 <= number <= len(tasks):
        raise ToolError(f"There is no item {number}; the list has {len(tasks)} items.")
    removed = tasks.pop(number - 1)
    _task_file(day).write_text("".join(t + "\n" for t in tasks), encoding="utf-8")
    return f"Removed: {removed}"


def _ring(message):
    print(f"\n: Reminder: {message}")
    try:
        from plyer import notification
        notification.notify(title="Jarvis reminder", message=message, timeout=15)
    except Exception:
        pass
    try:
        from sound_player import playsound
        playsound(DB / "Sounds" / "1.mp3")
    except Exception:
        pass


@beta_tool
def set_reminder(message: str, minutes_from_now: float = 0, at_time: str = "") -> str:
    """Set a timer, alarm or reminder that plays a sound and shows a notification. Give minutes_from_now or at_time.

    Args:
        message: What the reminder is for.
        minutes_from_now: Minutes until it goes off, e.g. 10 for a ten-minute timer.
        at_time: Clock time in 24-hour HH:MM, e.g. "07:30" or "18:45". If that time has passed today, it goes off tomorrow.
    """
    now = datetime.datetime.now()
    if at_time:
        try:
            hour, minute = map(int, at_time.split(":"))
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            raise ToolError("Times must look like HH:MM in 24-hour format.")
        if when <= now:
            when += datetime.timedelta(days=1)
    elif minutes_from_now > 0:
        when = now + datetime.timedelta(minutes=minutes_from_now)
    else:
        raise ToolError("Say how many minutes from now, or what time.")
    timer = threading.Timer((when - now).total_seconds(), _ring, args=[message])
    timer.daemon = True
    timer.start()
    days_ahead = (when.date() - now.date()).days
    day = "today" if days_ahead == 0 else "tomorrow" if days_ahead == 1 else f"on {when:%A}"
    clock = when.strftime("%I:%M %p").lstrip("0")
    return f"Reminder set for {clock} {day}: {message}. It only goes off while Jarvis is running."


@beta_tool
def generate_password(length: int = 16) -> str:
    """Generate a strong random password and copy it to the clipboard. The password is never shown to you.

    Args:
        length: Number of characters, from 8 to 64.
    """
    length = max(8, min(length, 64))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    subprocess.run("clip", input=password.encode("ascii"), check=True)
    return f"Generated a {length}-character password and copied it to the clipboard."


TOOLS = [
    get_current_datetime, get_weather, search_wikipedia, get_crypto_price, convert_currency, get_my_location,
    get_system_status, nasa_picture_of_the_day, open_website, search_google, youtube, media_control,
    youtube_control, open_app, close_app, windows_action, browser_action, take_screenshot, take_note, read_notes, add_task,
    list_tasks, remove_task, set_reminder, generate_password,
]
