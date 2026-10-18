"""Space tools: NASA pictures and asteroids, planet facts, the International Space Station and SpaceX.

Where a 2022-era service has died, this module uses its modern replacement:
  * Mars photos      NASA's Mars Photos API was retired            -> NASA's raw-image feed
  * SpaceX data      the community SpaceX API is down              -> Launch Library 2 (The Space Devs)
  * Planet facts     the Solar System OpenData API now needs a key -> NASA's published fact sheets
"""
import datetime
import json
import re
import time
from typing import Literal
from urllib.parse import urlparse

from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import config
from . import _common
from ._common import RateLimitedError, RefusedError, first_sentences, get_json, get_text, open_url

APOD_PAGE = "https://apod.nasa.gov/apod/astropix.html"
APOD_MEDIA_HOSTS = {"apod.nasa.gov", "www.youtube.com", "youtube.com", "player.vimeo.com"}
MARS_FEED = "https://mars.nasa.gov/api/v1/raw_image_items/"
PERSEVERANCE_FEED = "https://mars.nasa.gov/rss/api/"
LL2 = "https://ll.thespacedevs.com/2.2.0"
LUNAR_DISTANCE_KM = 384_400


def _when(moment):
    """A moment in time as speech: 'Monday 19 October at 3:30 PM' in the PC's own time zone."""
    return moment.astimezone().strftime("%A %d %B at %I:%M %p").replace(" 0", " ")


def _local_time(iso):
    return _when(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")))


def _coordinates(lat, lon):
    return f"{abs(lat):.1f} degrees {'north' if lat >= 0 else 'south'}, {abs(lon):.1f} degrees {'east' if lon >= 0 else 'west'}"


def _nasa(url, **params):
    """Call a NASA API with the configured key; the shared DEMO_KEY runs out quickly, so say how to fix that."""
    try:
        return get_json(url, api_key=config.NASA_API_KEY, **params)
    except RateLimitedError:
        hint = (" A free personal key from api.nasa.gov, put in NASA_API_KEY in the .env file, removes that limit."
                if config.NASA_API_KEY == "DEMO_KEY" else "")
        raise ToolError("NASA says I have asked too many times this hour." + hint) from None


# ---------------------------------------------------------------- NASA

@beta_tool
def nasa_picture_of_the_day(date: str = "") -> str:
    """Open NASA's Astronomy Picture of the Day and get its title and explanation.

    Args:
        date: Date as YYYY-MM-DD, or empty for today.
    """
    if date:
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ToolError("Dates must look like YYYY-MM-DD.") from None
    try:
        data = _nasa("https://api.nasa.gov/planetary/apod", **({"date": date} if date else {}))
        link = data.get("hdurl") or data.get("url") or ""
        # NASA's picture API sometimes answers with a placeholder (the NASA logo) instead of the day's picture.
        usable = (urlparse(link).hostname or "") in APOD_MEDIA_HOSTS and "title" in data and "explanation" in data
    except ToolError:
        usable = False
    if not usable:
        page = f"https://apod.nasa.gov/apod/ap{date[2:4]}{date[5:7]}{date[8:10]}.html" if date else APOD_PAGE
        open_url(page)
        return ("NASA's picture service isn't giving me the real picture right now, so I opened the "
                "Astronomy Picture of the Day page in your browser instead.")
    open_url(link)
    return f"Opened '{data['title']}' from {data['date']}. NASA's explanation: {first_sentences(data['explanation'], 3)}"


@beta_tool
def nasa_mars_photos(rover: Literal["curiosity", "perseverance"] = "curiosity") -> str:
    """Show the newest photo sent back by a rover on Mars and say when and with which camera it was taken. Perseverance's feed is slow and can take 20 seconds.

    Args:
        rover: curiosity or perseverance.
    """
    if rover == "curiosity":
        items = get_json(MARS_FEED, cache_seconds=300, order="sol desc", per_page=5, page=0,
                         condition_1="msl:mission").get("items") or []
        photos = [(i.get("sol"), i.get("date_taken") or "", i.get("title") or "", i.get("https_url") or i.get("url"))
                  for i in items]
    else:
        items = get_json(PERSEVERANCE_FEED, timeout=45, cache_seconds=300, feed="raw_images", category="mars2020",
                         feedtype="json", num=5, page=0, order="sol desc").get("images") or []
        photos = [(i.get("sol"), i.get("date_taken_utc") or "", i.get("title") or "", (i.get("image_files") or {}).get("large"))
                  for i in items]
    photos = [photo for photo in photos if photo[3]]
    if not photos:
        raise ToolError(f"NASA has no recent {rover.title()} photos available right now.")
    sol, taken, title, url = photos[0]
    open_url(url)
    try:
        taken = datetime.date.fromisoformat(taken[:10]).strftime("%d %B %Y").lstrip("0")
    except ValueError:
        taken = "an unknown date"
    camera = re.sub(r"^.*?Sol \d+:\s*", "", title) or "an onboard camera"
    return (f"{rover.title()}'s newest photo is from Martian day {sol}, taken on {taken} with {camera}. "
            "I opened it in your browser.")


def _body(name, kind, radius, gravity, spin, orbit, moons, temperature, distance, fact):
    return {"name": name, "kind": kind, "radius": radius, "gravity": gravity, "spin": spin, "orbit": orbit,
            "moons": moons, "temperature": temperature, "distance": distance, "fact": fact}


BODIES = {
    "sun": _body("the Sun", "star", "695,700 km", 274, "about 25 Earth days", "once around the centre of the Milky Way in about 230 million years",
                 "eight planets circling it", "5,500 degrees Celsius on the surface and 15 million at the core",
                 "150 million km from Earth", "It holds 99.8 percent of all the mass in the solar system."),
    "mercury": _body("Mercury", "planet", "2,440 km", 3.7, "58.6 Earth days", "once around the Sun in 88 Earth days", "no moons",
                     "about 167 degrees Celsius on average, from minus 180 at night to 430 by day", "58 million km from the Sun",
                     "It is the smallest planet and the closest to the Sun."),
    "venus": _body("Venus", "planet", "6,052 km", 8.9, "243 Earth days", "once around the Sun in 225 Earth days", "no moons",
                   "about 464 degrees Celsius, hot enough to melt lead", "108 million km from the Sun",
                   "It is the hottest planet, it spins backwards, and its day is longer than its year."),
    "earth": _body("Earth", "planet", "6,371 km", 9.8, "24 hours", "once around the Sun in 365.25 days", "one moon",
                   "about 15 degrees Celsius on average", "150 million km from the Sun",
                   "It is the only place we know of that has life."),
    "moon": _body("the Moon", "natural satellite of Earth", "1,737 km", 1.6, "27.3 Earth days", "once around the Earth in 27.3 days",
                  "no moons of its own", "from minus 173 to 127 degrees Celsius", "384,400 km from Earth",
                  "It always shows us the same face, and it is drifting away from Earth by about 3.8 centimetres a year."),
    "mars": _body("Mars", "planet", "3,390 km", 3.7, "24.6 hours", "once around the Sun in 687 Earth days",
                  "two moons, Phobos and Deimos", "about minus 65 degrees Celsius on average", "228 million km from the Sun",
                  "It is home to Olympus Mons, the tallest volcano in the solar system."),
    "jupiter": _body("Jupiter", "planet", "69,911 km", 24.8, "9.9 hours", "once around the Sun in 11.9 Earth years",
                     "more than 90 known moons", "about minus 110 degrees Celsius at the cloud tops", "778 million km from the Sun",
                     "Its Great Red Spot is a storm bigger than Earth that has raged for centuries."),
    "saturn": _body("Saturn", "planet", "58,232 km", 10.4, "10.7 hours", "once around the Sun in 29.4 Earth years",
                    "more than 140 known moons", "about minus 140 degrees Celsius at the cloud tops", "1.43 billion km from the Sun",
                    "Its spectacular rings are made mostly of water ice."),
    "uranus": _body("Uranus", "planet", "25,362 km", 8.7, "17.2 hours", "once around the Sun in 84 Earth years",
                    "more than 25 known moons", "about minus 195 degrees Celsius", "2.87 billion km from the Sun",
                    "It rolls around the Sun tipped over on its side, and it spins backwards."),
    "neptune": _body("Neptune", "planet", "24,622 km", 11.2, "16.1 hours", "once around the Sun in 165 Earth years",
                     "about 16 known moons", "about minus 200 degrees Celsius", "4.5 billion km from the Sun",
                     "It has the fastest winds in the solar system, over 2,000 kilometres an hour."),
    "pluto": _body("Pluto", "dwarf planet", "1,188 km", 0.62, "6.4 Earth days", "once around the Sun in 248 Earth years",
                   "five moons", "about minus 230 degrees Celsius", "5.9 billion km from the Sun on average",
                   "A heart-shaped glacier of nitrogen ice covers part of its surface."),
}


@beta_tool
def nasa_solar_body_facts(body: str, aspect: Literal["all", "size", "gravity", "day", "year", "moons", "temperature", "distance"] = "all") -> str:
    """Give key facts about the Sun, the Moon, one of the eight planets, or Pluto. For a specific question ("how hot is Mars?") ask for just that aspect to get a short answer.

    Args:
        body: Name of the body, e.g. "Mars", "Jupiter", "the Moon" or "the Sun".
        aspect: all for a full fact sheet, or one of: size, gravity, day (how long it takes to spin once), year (how long it takes to orbit), moons, temperature, distance.
    """
    key = re.sub(r"^(?:the |planet )+|(?: planet)$|'s$", "", body.strip().lower()).strip()
    if key not in BODIES:
        raise ToolError("I have facts for the Sun, the Moon, the eight planets and Pluto. Try one of those.")
    b = BODIES[key]
    name = b["name"][0].upper() + b["name"][1:]
    percent = f"{b['gravity'] / 9.81 * 100:.0f}"
    short = {
        "size": f"{name} has a radius of {b['radius']}.",
        "gravity": f"Surface gravity on {b['name']} is {b['gravity']} metres per second squared, {percent} percent of Earth's.",
        "day": f"One turn of {b['name']} on its axis takes {b['spin']}.",
        "year": f"{name} goes {b['orbit']}.",
        "moons": f"{name} has {b['moons']}.",
        "temperature": f"Temperature on {b['name']}: {b['temperature']}.",
        "distance": f"{name} is {b['distance']}.",
    }
    if aspect in short:
        return short[aspect]
    return (f"{name} is a {b['kind']}. Radius {b['radius']}; surface gravity {b['gravity']} metres per second squared "
            f"({percent} percent of Earth's). One turn on its axis takes {b['spin']}, and it goes {b['orbit']}. "
            f"It has {b['moons']}. Temperature: {b['temperature']}. It is {b['distance']}. {b['fact']}")


@beta_tool
def nasa_near_earth_objects(start_date: str = "", end_date: str = "") -> str:
    """List asteroids passing close to Earth in a date range: how many, the closest, the biggest and how many NASA classes as potentially hazardous.

    Args:
        start_date: First day as YYYY-MM-DD, or empty for today.
        end_date: Last day as YYYY-MM-DD, or empty for tomorrow. At most 7 days after the start.
    """
    try:
        first = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today()
        last = datetime.date.fromisoformat(end_date) if end_date else first + datetime.timedelta(days=1)
    except ValueError:
        raise ToolError("Dates must look like YYYY-MM-DD.") from None
    if last < first or (last - first).days > 7:
        raise ToolError("NASA allows a range of at most 7 days, and the end can't be before the start.")
    feed = _nasa("https://api.nasa.gov/neo/rest/v1/feed", cache_seconds=600,
                 start_date=first.isoformat(), end_date=last.isoformat())
    rocks = [r for day in feed.get("near_earth_objects", {}).values() for r in day]
    if not rocks:
        return f"NASA lists no near-Earth asteroids between {first:%d %B} and {last:%d %B}."

    def miss_km(rock):
        return float(rock["close_approach_data"][0]["miss_distance"]["kilometers"])

    def name_of(rock):
        return re.sub(r"[()]", "", rock["name"]).strip()

    def passes_at(rock):
        stamp = rock["close_approach_data"][0].get("close_approach_date_full", "")
        try:
            return _when(datetime.datetime.strptime(stamp, "%Y-%b-%d %H:%M").replace(tzinfo=datetime.timezone.utc))
        except ValueError:
            return rock["close_approach_data"][0].get("close_approach_date", "an unknown time")

    closest = min(rocks, key=miss_km)
    biggest = max(rocks, key=lambda r: r["estimated_diameter"]["meters"]["estimated_diameter_max"])
    hazardous = sum(1 for r in rocks if r["is_potentially_hazardous_asteroid"])
    text = (f"NASA lists {len(rocks)} near-Earth asteroids between {first:%d %B} and {last:%d %B}. "
            f"The closest, {name_of(closest)}, passes at {miss_km(closest):,.0f} kilometres "
            f"({miss_km(closest) / LUNAR_DISTANCE_KM:.1f} times the distance to the Moon) on {passes_at(closest)}. "
            f"The biggest, {name_of(biggest)}, is up to {biggest['estimated_diameter']['meters']['estimated_diameter_max']:,.0f} metres across. ")
    text += (f"{hazardous} of them {'is' if hazardous == 1 else 'are'} classed as potentially hazardous, which only means "
             "large and close enough to monitor, not that there is any danger." if hazardous
             else "None are classed as potentially hazardous.")
    return text


@beta_tool
def get_iss_location() -> str:
    """Say where the International Space Station is right now, how high and how fast it is moving."""
    iss = get_json("https://api.wheretheiss.at/v1/satellites/25544")
    lat, lon = iss["latitude"], iss["longitude"]
    try:
        place = get_json("https://nominatim.openstreetmap.org/reverse", timeout=4, lat=f"{lat:.4f}", lon=f"{lon:.4f}",
                         format="json", zoom=3, **{"accept-language": "en"})        # (a slow map service must not hold the answer up)
        over = f"over {place['display_name']}" if place.get("display_name") else f"over open water, at {_coordinates(lat, lon)}"
    except ToolError:
        over = f"at {_coordinates(lat, lon)}"
    lit = {"daylight": "in sunlight", "eclipsed": "in Earth's shadow", "visible": "visible from the ground"}.get(
        iss.get("visibility"), "")
    return (f"The International Space Station is {over}, {iss['altitude']:.0f} kilometres up, travelling at "
            f"{iss['velocity']:,.0f} kilometres an hour{', ' + lit if lit else ''}.")


# ---------------------------------------------------------------- SpaceX

@beta_tool
def spacex_company_info() -> str:
    """Give facts about SpaceX: when it was founded, who leads it, and how many launches and booster landings it has made."""
    agency = get_json(f"{LL2}/agencies/121/", timeout=30, cache_seconds=3600)
    leader = (agency.get("administrator") or "").split(":")[-1].strip()
    return (f"SpaceX was founded in {agency.get('founding_year')}" + (f" and is led by {leader}" if leader else "") +
            f". It has made {agency.get('total_launch_count')} launches, {agency.get('successful_launches')} successful "
            f"and {agency.get('failed_launches')} failed, and has landed boosters {agency.get('successful_landings')} times.")


@beta_tool
def spacex_latest_launch(which: Literal["latest", "next"] = "latest") -> str:
    """Tell about SpaceX's most recent launch or its next scheduled launch.

    Args:
        which: latest for the most recent launch, next for the upcoming one.
    """
    path = "launch/previous/" if which == "latest" else "launch/upcoming/"
    results = get_json(f"{LL2}/{path}", timeout=30, cache_seconds=600, lsp__name="SpaceX", limit=1, mode="normal").get("results")
    if not results:
        raise ToolError("Launch Library has no SpaceX launch to report.")
    launch = results[0]
    rocket, _, mission = launch.get("name", "").partition(" | ")
    where = (launch.get("pad") or {}).get("name")
    status = (launch.get("status") or {}).get("name", "")
    when = _local_time(launch["net"]) if launch.get("net") else "a date that isn't confirmed yet"
    subject = f"{mission or rocket}" + (f" on a {rocket}" if mission else "")
    place = f" from {where}" if where else ""
    if which == "latest":
        return f"SpaceX's latest launch was {subject}, on {when}{place}. Result: {status or 'unknown'}."
    return f"SpaceX's next launch is {subject}, scheduled for {when}{place}. Status: {status or 'to be confirmed'}."


@beta_tool
def spacex_starlink_count() -> str:
    """Say roughly how many Starlink satellites are in orbit. The first call can take up to a minute; later calls are instant."""
    cache = _common.DB / "Cache" / "starlink.json"
    stored = None
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        stored = {"count": int(saved["count"]), "fetched": float(saved["fetched"])}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if stored and time.time() - stored["fetched"] < 12 * 3600:
        return f"There are about {stored['count']:,} Starlink satellites in orbit, according to CelesTrak."
    try:
        rows = get_text("https://celestrak.org/NORAD/elements/gp.php", timeout=90, GROUP="starlink", FORMAT="csv").splitlines()
        if not rows or not rows[0].startswith("OBJECT_NAME"):
            raise ToolError("CelesTrak sent a satellite list I couldn't read.")
        count = len([row for row in rows[1:] if row.strip()])
    except ToolError as error:
        if stored:                                                            # an old answer beats no answer
            return (f"CelesTrak isn't giving me a fresh list, but when I last checked there were about "
                    f"{stored['count']:,} Starlink satellites in orbit.")
        if isinstance(error, RefusedError):
            raise ToolError("CelesTrak only lets the satellite list be downloaded once every two hours, and it was "
                            "downloaded a short while ago. Please ask again later.") from None
        raise
    if count:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"count": count, "fetched": time.time()}), encoding="utf-8")
    return f"There are about {count:,} Starlink satellites in orbit, according to CelesTrak."


TOOLS = [nasa_picture_of_the_day, nasa_mars_photos, nasa_solar_body_facts, nasa_near_earth_objects, get_iss_location,
         spacex_company_info, spacex_latest_launch, spacex_starlink_count]
