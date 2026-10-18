"""Information tools: time, weather, knowledge, money, location and the state of this PC."""
import datetime
import functools
import math
import os
import platform
import re
import socket
import time
from typing import Literal
from urllib.parse import quote, quote_plus

import psutil
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import config
import rates
from ._common import get_json, get_text, money, open_url


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


GEOCODER = "https://geocoding-api.open-meteo.com/v1/search"
COUNTRY_ALIASES = {"usa": "united states", "us": "united states", "america": "united states", "uk": "united kingdom",
                   "britain": "united kingdom", "england": "united kingdom", "uae": "united arab emirates"}


@functools.lru_cache(maxsize=4)
def _home_country(city):
    """The country code of the user's home city, or "". When a name could be several places, the one in the user's own
    country is the likelier: "narayan kagan" is Kagan in Pakistan for someone in Peshawar, not Narayan in India."""
    if not city:
        return ""
    try:
        found = get_json(GEOCODER, name=city, count=1).get("results") or []
    except ToolError:
        return ""
    return found[0].get("country_code", "") if found else ""


def find_place(text):
    """The place that best matches what was said, or None.

    Understands "Lahore", "Murree in Pakistan" and "Lahore, Pakistan" (the country picks between places of the same name).
    The geocoder only knows single-word names, so for "narran kaghan" it tries "kaghan" and then "narran" instead of giving up.
    With no country said, a place in the user's own country wins over one with the same name elsewhere.
    """
    name, _, hint = text.strip().partition(" in ") if " in " in text else text.strip().partition(",")
    name, hint = name.strip(), hint.strip().lower()
    hint = COUNTRY_ALIASES.get(re.sub(r"^the\s+", "", hint), hint)

    def search(word):
        return get_json(GEOCODER, name=word, count=10).get("results") or []

    home = "" if hint else _home_country(config.DEFAULT_CITY)

    def best(results):
        if not hint:
            return next((p for p in results if home and p.get("country_code") == home), results[0] if results else None)
        return next((p for p in results if hint in (p.get("country") or "").lower() or hint == (p.get("country_code") or "").lower()
                     or hint in (p.get("admin1") or "").lower()), None)

    place = best(search(name))
    if place is None and len(name.split()) > 1:
        found = list(dict.fromkeys(re.findall(r"[^\W\d_]{3,}", name)))
        words = sorted(reversed(found), key=len, reverse=True)       # longest first; of two as long, the later word ("Naran Kaghan")
        for word in words[:3]:
            found_here = best(search(word))
            if found_here and (place is None or (home and found_here.get("country_code") == home)):
                place = found_here                              # the first word that finds anything, unless a later one is at home
            if place and (hint or not home or place.get("country_code") == home):
                break
    return place


def weather_report(city):
    """Current weather and today's forecast for a city, from Open-Meteo (no API key needed)."""
    place = find_place(city)
    if not place:
        raise ToolError(f"I couldn't find a place called {city}.")
    data = get_json(
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
    results = get_json("https://en.wikipedia.org/w/api.php", action="query", list="search", srsearch=topic,
                       srlimit=1, format="json").get("query", {}).get("search")
    if not results:
        raise ToolError(f"Nothing found on Wikipedia for {topic}.")
    title = results[0]["title"]
    page = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe=""))
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
    coins = get_json("https://api.coingecko.com/api/v3/search", query=coin).get("coins")
    if not coins:
        raise ToolError(f"I couldn't find a coin called {coin}.")
    found, cur = coins[0], currency.lower()
    price = get_json("https://api.coingecko.com/api/v3/simple/price",
                     ids=found["id"], vs_currencies=cur, include_24hr_change="true").get(found["id"], {})
    if cur not in price:
        raise ToolError(f"No {currency.upper()} price available for {found['name']}.")
    change = price.get(f"{cur}_24h_change")
    result = f"{found['name']} is {money(price[cur], cur)}"
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
    try:
        converted = rates.convert(amount, from_currency, to_currency)
    except rates.RateError as error:
        raise ToolError(str(error)) from None
    return f"{money(amount, from_currency)} is {money(converted, to_currency)}."


def _my_position():
    """(latitude, longitude, description) of this PC from its internet address, accurate to about city level."""
    geo = get_json("https://get.geojs.io/v1/ip/geo.json")
    place = ", ".join(part for part in (geo.get("city"), geo.get("region"), geo.get("country")) if part)
    try:
        return float(geo["latitude"]), float(geo["longitude"]), place or "an unknown place"
    except (KeyError, ValueError):
        raise ToolError("I couldn't work out where this PC is.") from None


@beta_tool
def get_my_location() -> str:
    """Find roughly where this PC is, at city level, from its internet connection."""
    return f"Approximately {_my_position()[2]}."


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


@beta_tool
def show_on_map(place: str) -> str:
    """Open a place in Google Maps and say how far away it is from here.

    Args:
        place: A city, address or landmark, e.g. "Islamabad" or "Eiffel Tower".
    """
    found = get_json("https://nominatim.openstreetmap.org/search", q=place, format="json", limit=1,
                     **{"accept-language": "en"})
    if not found:
        raise ToolError(f"I couldn't find {place} on the map.")
    target = found[0]
    open_url("https://www.google.com/maps/search/?api=1&query=" + quote_plus(place))
    lat, lon, here = _my_position()
    km = _haversine_km(lat, lon, float(target["lat"]), float(target["lon"]))
    name = target.get("display_name", place).split(",")[0]
    return f"Opened {name} in Google Maps. It is about {km:,.0f} kilometres from {here}."


# ---------------------------------------------------------------- this PC

def _cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return " ".join(winreg.QueryValueEx(key, "ProcessorNameString")[0].split())
    except OSError:
        return platform.processor() or "an unknown processor"


def _gb(n):
    return f"{n / 2**30:.1f} GB"


def _local_ip():
    """This PC's address on the local network (no traffic is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def spoken_duration(seconds):
    """3 days 20:48:58 as "3 days and 20 hours", the way it is said (the clock form was read out digit by digit)."""
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes and not days:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " and ".join(parts) or "under a minute"


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
    parts.append(f"running for {spoken_duration(time.time() - psutil.boot_time())}")
    return "; ".join(parts)


@beta_tool
def get_system_details(topic: Literal["cpu", "memory", "disks", "network", "system"]) -> str:
    """Get detailed information about one part of this PC: its processor, memory, drives, network connection or operating system.

    Args:
        topic: Which part: cpu, memory, disks, network or system.
    """
    if topic == "cpu":
        freq = psutil.cpu_freq()
        speed = f", running at {freq.current / 1000:.1f} GHz" if freq else ""
        return (f"{_cpu_name()}: {psutil.cpu_count(logical=False)} cores and {psutil.cpu_count()} threads{speed}, "
                f"currently {psutil.cpu_percent(interval=0.5):.0f} percent busy.")
    if topic == "memory":
        ram, swap = psutil.virtual_memory(), psutil.swap_memory()
        return (f"RAM: {_gb(ram.used)} used of {_gb(ram.total)} ({ram.percent:.0f} percent), {_gb(ram.available)} free. "
                f"Virtual memory (page file): {_gb(swap.used)} used of {_gb(swap.total)}.")
    if topic == "disks":
        lines = []
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or not part.fstype:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            lines.append(f"drive {part.device[:2]} has {_gb(usage.free)} free of {_gb(usage.total)}")
        return "; ".join(lines) or "I couldn't read any drives."
    if topic == "network":
        local = _local_ip()
        if not local:
            return "This PC is not connected to a network."
        try:
            public = get_text("https://api.ipify.org").strip()
            return f"Connected. Local address {local}, public address {public}."
        except ToolError:
            return f"Connected to the local network ({local}), but the internet isn't reachable."
    uname = platform.uname()
    uptime = datetime.timedelta(seconds=int(time.time() - psutil.boot_time()))
    return (f"{uname.system} {uname.release} (version {uname.version}), computer name {uname.node}, "
            f"user {os.environ.get('USERNAME', 'unknown')}, Python {platform.python_version()}, up for {uptime}.")


TOOLS = [get_current_datetime, get_weather, search_wikipedia, get_crypto_price, convert_currency, get_my_location,
         show_on_map, get_system_status, get_system_details]
