"""World tools: facts and jokes, health numbers, games, mail, Wi-Fi, downloads and a few harmless party tricks."""
import datetime
import difflib
import mimetypes
import random
import re
import secrets
import smtplib
import ssl
import string
import subprocess
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from anthropic import beta_tool
from anthropic.lib.tools import ToolError

import config
from ._common import NotFoundError, copy_to_clipboard, folder, get_bytes, get_json, open_url, plain


# ---------------------------------------------------------------- ideas

NAME_PREFIXES = ("Bright", "Next", "Blue", "Swift", "Prime", "Nova", "Urban", "True", "Pure", "Smart", "Bold", "Peak")
NAME_SUFFIXES = ("ly", "ify", "Hub", "Labs", "Works", "Nest", "Forge", "Wave", "Loop", "Spark", "Craft", "Point")


@beta_tool
def generate_business_names(keyword: str, count: int = 5) -> str:
    """Suggest catchy business names built around a word or idea. It does not check whether a name or web address is taken.

    Args:
        keyword: The idea, product or industry, e.g. "coffee" or "fitness app".
        count: How many names to suggest (1 to 10).
    """
    words = [word.capitalize() for word in re.findall(r"[A-Za-z]{2,}", keyword)[:3]]
    if not words:
        raise ToolError("Give me a word or two to build the names around, like coffee or fitness.")
    core = words[0]
    options = {f"{prefix}{core}" for prefix in NAME_PREFIXES} | {f"{core}{suffix}" for suffix in NAME_SUFFIXES}
    if len(words) > 1:
        options |= {"".join(words), f"{words[1]}{words[0]}", f"{words[1]}{NAME_SUFFIXES[2]}", f"{random.choice(NAME_PREFIXES)}{words[1]}"}
    picks = random.sample(sorted(options), max(1, min(int(count), 10, len(options))))
    return f"Here are some ideas for {keyword.strip()}: {', '.join(picks)}. I haven't checked whether any of them is already taken."


@beta_tool
def get_random_fact(topic: Literal["any", "cat"] = "any") -> str:
    """Tell a random interesting fact.

    Args:
        topic: any for a general fact, or cat for a fact about cats.
    """
    if topic == "any":
        try:
            fact = get_json("https://uselessfacts.jsph.pl/api/v2/facts/random", language="en").get("text")
            if fact:
                return fact.strip()
        except ToolError:
            pass                                                     # the cat service is a decent plan B
    fact = get_json("https://catfact.ninja/fact").get("fact")
    if not fact:
        raise ToolError("The fact service sent an empty answer.")
    return fact.strip()


OFFLINE_ACTIVITIES = (
    ("Take a walk somewhere you have never been", "recreational", 1),
    ("Cook a dish from a country you have never visited", "cooking", 1),
    ("Learn three words in a new language", "education", 1),
    ("Call someone you haven't spoken to in a while", "social", 2),
    ("Sort through your old photos and delete the bad ones", "busywork", 1),
    ("Start a short sketch of the view from your window", "diy", 1),
    ("Play a board game with family", "social", 3),
)


@beta_tool
def get_random_activity() -> str:
    """Suggest something to do when bored."""
    try:
        data = get_json("https://bored-api.appbrewery.com/random")
        activity, kind, people = data.get("activity"), data.get("type"), data.get("participants")
    except ToolError:
        activity = None
    if not activity:
        activity, kind, people = random.choice(OFFLINE_ACTIVITIES)
    detail = ", ".join(part for part in (kind, f"{people} {'person' if people == 1 else 'people'}" if people else "") if part)
    return f"How about this: {activity}." + (f" ({detail})" if detail else "")


@beta_tool
def get_random_advice() -> str:
    """Give a random piece of life advice."""
    advice = (get_json("https://api.adviceslip.com/advice").get("slip") or {}).get("advice")
    if not advice:
        raise ToolError("The advice service sent an empty answer.")
    return advice.strip()


@beta_tool
def get_dog_image() -> str:
    """Open a random dog photo in the browser."""
    data = get_json("https://dog.ceo/api/breeds/image/random")
    link = data.get("message")
    if data.get("status") != "success" or not link:
        raise ToolError("The dog photo service didn't send a picture.")
    open_url(link)
    found = re.search(r"/breeds/([^/]+)/", link)
    breed = "mixed breed" if not found or found.group(1) == "mix" else " ".join(reversed(found.group(1).split("-")))
    return f"Opened a random dog photo. Breed: {breed}."                          # "hound-afghan" -> "afghan hound"


OFFLINE_JOKES = (
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why did the computer go to the doctor? It had a virus.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, sees two tables and asks: may I join you?",
    "Why was the math book sad? It had too many problems.",
)


@beta_tool
def get_joke() -> str:
    """Tell a random joke."""
    try:
        joke = get_json("https://icanhazdadjoke.com/", headers={"Accept": "application/json"}).get("joke")
    except ToolError:
        joke = None
    return (joke or random.choice(OFFLINE_JOKES)).strip()


# ---------------------------------------------------------------- party tricks (pure fiction)

@beta_tool
def password_cracking_demo(password_length: int = 8) -> str:
    """Put on a pretend password-cracking show for fun. This is fiction: Jarvis invents a random password and then "finds" it, so nothing real is ever cracked. Use only when the user asks for the gag.

    Args:
        password_length: Length of the made-up password (4 to 12).
    """
    length = max(4, min(int(password_length), 12))
    made_up = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    guesses = random.randint(10 ** 6, 10 ** 8)
    return (f"This is a pretend demonstration; nothing real is being cracked. I made up a {length} character password "
            f"and acted out the hunt. Loading wordlists, three, two, one, trying {guesses:,} combinations... "
            f"Found it: {made_up}. Of course I knew it all along, because I invented it myself.")


@beta_tool
def hack_a_random_profile() -> str:
    """Act out a pretend hacking scene for fun, starring a made-up person from randomuser.me. Nobody real is involved and nothing is hacked. Use only when the user asks for the gag.
    """
    results = get_json("https://randomuser.me/api/", inc="name,location,email,dob,login",
                       nat="au,ca,gb,ie,nz,us").get("results")        # English-speaking, so the voice can read the names
    if not results:
        raise ToolError("I couldn't invent a target for the show.")
    who = results[0]
    name = f"{who['name']['first']} {who['name']['last']}"
    place = who["location"]
    return ("Pretend hacking scene, played entirely for fun. Scanning the network... target locked. Bypassing the firewall... "
            f"access granted! The target is {name}, aged {who['dob']['age']}, living in {place['city']}, {place['state']}, "
            f"{place['country']}. Username {who['login']['username']}, email {who['email']}. "
            f"Relax: {who['name']['first']} is a made-up person from randomuser.me, so nobody was hacked.")


# ---------------------------------------------------------------- health and games

@beta_tool
def get_disease_outbreak_stats(country: str = "", disease: str = "covid") -> str:
    """Get the latest COVID-19 case numbers, worldwide or for one country. COVID-19 is the only disease with live figures.

    Args:
        country: Country name or two-letter code, e.g. "Pakistan" or "US". Leave empty for the whole world.
        disease: Only "covid" is available.
    """
    if disease.strip().lower() not in {"covid", "covid-19", "covid19", "coronavirus"}:
        raise ToolError("I only have live figures for COVID-19.")
    place = country.strip()
    if not place:
        data = get_json("https://disease.sh/v3/covid-19/all", cache_seconds=600)
    else:
        url = f"https://disease.sh/v3/covid-19/countries/{quote(place, safe='')}"
        try:
            data = get_json(url, cache_seconds=600)
        except NotFoundError:
            try:
                data = get_json(url, cache_seconds=600, strict="false")          # allow partial names
            except NotFoundError:
                raise ToolError(f"I couldn't find COVID-19 figures for {place}.") from None
        if isinstance(data, list):
            data = data[0] if data else {}
    if "cases" not in data:
        raise ToolError("The outbreak service sent figures I couldn't read.")
    updated = datetime.datetime.fromtimestamp(data.get("updated", 0) / 1000).strftime("%d %B %Y") if data.get("updated") else "an unknown date"
    return (f"{data.get('country', 'Worldwide')}: {data['cases']:,} total COVID-19 cases ({data.get('todayCases', 0):,} reported today), "
            f"{data['deaths']:,} deaths, {data.get('recovered', 0):,} recovered, {data.get('active', 0):,} active. "
            f"Latest update: {updated}; some countries no longer report daily.")


@beta_tool
def lookup_free_game(title: str = "") -> str:
    """Look up a free-to-play game by name and open its page, or suggest a random one when no name is given.

    Args:
        title: Game name or part of it, e.g. "Valorant" or "Warframe". Leave empty for a surprise.
    """
    games = get_json("https://www.freetogame.com/api/games", cache_seconds=3600)
    if not isinstance(games, list) or not games:
        raise ToolError("The free games list came back empty.")
    wanted = title.strip().lower()
    if not wanted:
        game, intro = random.choice(games), "Here's a free game you could try: "
    else:
        titles = {g["title"].lower(): g for g in games}
        chosen = (titles.get(wanted)
                  or next((g for t, g in titles.items() if wanted in t), None)
                  or next((titles[t] for t in difflib.get_close_matches(wanted, list(titles), n=1, cutoff=0.6)), None))
        if not chosen:
            raise ToolError(f"I couldn't find a free game called {title}.")
        game, intro = chosen, ""
    try:
        released = datetime.date.fromisoformat(game["release_date"]).strftime("%B %Y")
    except (KeyError, ValueError):
        released = "an unknown date"
    open_url(game.get("freetogame_profile_url") or game["game_url"])
    summary = plain(game.get("short_description", "")).rstrip(".")
    return (f"{intro}{game['title']} is a free {game['genre']} game for {game['platform']}, published by {game['publisher']} "
            f"and released in {released}. {summary}. I opened its page.")


MINECRAFT_ADDRESS = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::\d{1,5})?")


@beta_tool
def lookup_minecraft_server(host: str) -> str:
    """Check whether a Minecraft Java server is online, how many players are on it and which version it runs.

    Args:
        host: Server address, e.g. "mc.hypixel.net" or "play.example.com:25565".
    """
    address = host.strip().lower()
    if not MINECRAFT_ADDRESS.fullmatch(address):
        raise ToolError("That doesn't look like a server address. Try something like play.example.com.")
    data = get_json(f"https://api.mcsrvstat.us/3/{address}", cache_seconds=60)
    if not data.get("online"):
        if data.get("ip") in (None, "", "127.0.0.1"):                        # the status service's way of saying "no such address"
            return f"I couldn't find any server called {address}. Check the spelling of the address."
        return (f"The address {address} exists, but no Minecraft server answered. It is offline, "
                "or it doesn't allow status checks, as some large networks don't.")
    players = data.get("players") or {}
    motd = plain(" ".join((data.get("motd") or {}).get("clean", [])))
    text = f"{address} is online with {players.get('online', 0):,} of {players.get('max', 0):,} players"
    if data.get("version"):
        text += f", version {plain(data['version'])}"
    return text + (f". Its message of the day: {motd}." if motd else ".")


# ---------------------------------------------------------------- internet accounts and files

INSTAGRAM_NAME = re.compile(r"[A-Za-z0-9._]{1,30}")


@beta_tool
def instagram_profile_picture(username: str, download: bool = True) -> str:
    """Open someone's public Instagram profile and, if asked, save their profile picture. Instagram sometimes refuses automated requests, in which case the profile is opened in the browser instead.

    Args:
        username: Instagram username, with or without the @.
        download: True to save the profile picture, False to just open the profile page.
    """
    name = username.strip().lstrip("@")
    if not INSTAGRAM_NAME.fullmatch(name):
        raise ToolError("Instagram usernames use only letters, numbers, dots and underscores.")
    page = f"https://www.instagram.com/{name}/"
    if not download:
        open_url(page)
        return f"Opened {name}'s Instagram profile."
    try:
        import instaloader
    except ImportError:
        raise ToolError("The instaloader package isn't installed. Run: pip install instaloader") from None
    try:
        loader = instaloader.Instaloader(quiet=True, save_metadata=False, download_comments=False)
        picture = instaloader.Profile.from_username(loader.context, name).profile_pic_url
        data = get_bytes(picture, timeout=20)
    except instaloader.exceptions.ProfileNotExistsException:
        raise ToolError(f"There is no Instagram account called {name}.") from None
    except Exception:                                                      # Instagram blocks anonymous scraping often
        open_url(page)
        return (f"Instagram wouldn't let me download {name}'s picture right now, so I opened the profile page instead. "
                "You can save the picture from there.")
    target = folder("Downloads/Instagram") / f"{name}.jpg"
    target.write_bytes(data)
    return f"Saved {name}'s profile picture in the Instagram downloads folder."


SMTP_HOSTS = {
    "gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com",
    "yahoo.com": "smtp.mail.yahoo.com", "ymail.com": "smtp.mail.yahoo.com",
    "outlook.com": "smtp-mail.outlook.com", "hotmail.com": "smtp-mail.outlook.com", "live.com": "smtp-mail.outlook.com",
    "icloud.com": "smtp.mail.me.com", "me.com": "smtp.mail.me.com",
}
EMAIL_PATTERN = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_RECIPIENTS = 5


def _open_smtp(host, port):
    context = ssl.create_default_context()
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    server = smtplib.SMTP(host, port, timeout=30)
    server.starttls(context=context)
    return server


def _read_attachment(raw):
    """(bytes, maintype, subtype, filename) for a file that is safe to email."""
    path = Path(raw.strip().strip('"')).expanduser()
    if not path.is_file():
        raise ToolError(f"I can't find the file {raw}.")
    resolved = path.resolve()
    if (resolved.name.lower().startswith(".env") or resolved.name == "Data.txt"
            or {".git", "FaceDetectionModule"} & set(resolved.parts)):
        raise ToolError("That file holds private settings or face data, so I won't email it.")
    if resolved.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ToolError("Attachments over 20 megabytes won't go through email.")
    kind = (mimetypes.guess_type(resolved.name)[0] or "application/octet-stream").split("/", 1)
    return resolved.read_bytes(), kind[0], kind[1], resolved.name


@beta_tool
def send_email(to: str, subject: str, body: str, attachment_path: str = "", confirmed: bool = False) -> str:
    """Send an email from the user's own account.

    IMPORTANT: a sent email cannot be taken back. First read the recipient, subject and message back to the user,
    and call this with confirmed=true only after they clearly agree.

    Args:
        to: Recipient address, or up to 5 addresses separated by commas.
        subject: Subject line.
        body: The message text.
        attachment_path: Optional full path of one file to attach.
        confirmed: True only after the user has approved this exact email.
    """
    if not (config.EMAIL_ADDRESS and config.EMAIL_PASSWORD):
        raise ToolError("Email isn't set up. Put EMAIL_ADDRESS and an app password in EMAIL_PASSWORD in the .env file.")
    recipients = [address.strip() for address in re.split(r"[,;]", to) if address.strip()]
    if not recipients or len(recipients) > MAX_RECIPIENTS or not all(EMAIL_PATTERN.fullmatch(a) for a in recipients):
        raise ToolError(f"I need one to {MAX_RECIPIENTS} valid email addresses to send to.")
    subject = " ".join(subject.split())[:200] or "(no subject)"
    if not body.strip():
        raise ToolError("The email has no message in it.")
    attachment = _read_attachment(attachment_path) if attachment_path.strip() else None
    if not confirmed:
        raise ToolError(f"Not sent yet. Ask the user to confirm: email to {', '.join(recipients)}, subject '{subject}'"
                        + (f", with the file {attachment[3]}" if attachment else "")
                        + ". Then call again with confirmed set to true.")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = config.EMAIL_ADDRESS, ", ".join(recipients), subject
    message.set_content(body)
    if attachment:
        message.add_attachment(attachment[0], maintype=attachment[1], subtype=attachment[2], filename=attachment[3])
    host = config.EMAIL_SMTP_HOST or SMTP_HOSTS.get(config.EMAIL_ADDRESS.rpartition("@")[2].lower(),
                                                    "smtp." + config.EMAIL_ADDRESS.rpartition("@")[2].lower())
    server = None
    try:
        server = _open_smtp(host, config.EMAIL_SMTP_PORT)
        server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
        server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise ToolError("The mail server refused the login. Gmail, Yahoo and iCloud need an app password, "
                        "not your normal password.") from None
    except smtplib.SMTPRecipientsRefused:
        raise ToolError("The mail server rejected the recipient address.") from None
    except (smtplib.SMTPException, OSError) as error:
        raise ToolError(f"I couldn't send the email to {host} ({type(error).__name__}).") from None
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    return f"Sent your email to {', '.join(recipients)}" + (" with the attachment." if attachment else ".")


def _netsh(*arguments):
    try:
        result = subprocess.run(["netsh", "wlan", *arguments], capture_output=True, text=True, encoding="oem",
                                errors="replace", timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        raise ToolError("Windows didn't answer when I asked about Wi-Fi networks.") from None
    return result.stdout


@beta_tool
def get_saved_wifi_password(ssid: str = "") -> str:
    """Show the saved password of one Wi-Fi network this PC has connected to. The password is put on the screen and the clipboard, never read aloud. With no name given, it lists the saved networks instead.

    Args:
        ssid: Exact name of the Wi-Fi network. Leave empty to list the saved networks.
    """
    profiles = re.findall(r"^[ \t]*[^:\n]*Profile[^:\n]*:[ \t]*(.+?)[ \t]*$", _netsh("show", "profiles"), flags=re.M)
    wanted = ssid.strip()
    if not wanted:
        return ("Saved Wi-Fi networks: " + ", ".join(profiles) + ". Tell me which one you want the password for."
                if profiles else "This PC has no saved Wi-Fi networks.")
    exact = [p for p in profiles if p.lower() == wanted.lower()]
    matches = exact or [p for p in profiles if wanted.lower() in p.lower()]
    if not matches:
        raise ToolError(f"There is no saved network called {wanted}. Saved networks: {', '.join(profiles) or 'none'}.")
    if len(matches) > 1:
        raise ToolError(f"Several saved networks match: {', '.join(matches)}. Which one do you mean?")
    name = matches[0]
    found = re.search(r"^[ \t]*Key Content[ \t]*:[ \t]*(.+?)[ \t]*$", _netsh("show", "profile", f"name={name}", "key=clear"),
                      flags=re.M)
    if not found:
        raise ToolError(f"Windows didn't give me a password for {name}. It may be an open network, "
                        "or revealing it may need Jarvis to run as administrator.")
    password = found.group(1)
    print(f"\nWi-Fi password for {name}: {password}\n")
    try:
        copy_to_clipboard(password)
        shown = "on your screen and on the clipboard"
    except ToolError:
        shown = "on your screen"
    return f"The password for {name} is {shown}. I don't read passwords aloud."


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
MAX_VIDEO_SECONDS = 2 * 3600


@beta_tool
def download_youtube_video(url: str, audio_only: bool = False) -> str:
    """Download a YouTube video, or just its sound, into the Downloads/YouTube folder. Only for videos the user is allowed to keep. Can take a minute.

    Args:
        url: Full YouTube address of one video.
        audio_only: True to save only the audio (an .m4a file).
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in YOUTUBE_HOSTS:
        raise ToolError("I can only download from YouTube links.")
    try:
        import yt_dlp
        from yt_dlp.utils import match_filter_func
    except ImportError:
        raise ToolError("The yt-dlp package isn't installed. Run: pip install yt-dlp") from None
    target = folder("Downloads/YouTube")
    options = {
        "outtmpl": str(target / "%(title).80s [%(id)s].%(ext)s"),
        "format": "bestaudio[ext=m4a]/bestaudio" if audio_only else "best[ext=mp4]/best",     # one file: no ffmpeg needed
        "noplaylist": True, "quiet": True, "no_warnings": True, "windowsfilenames": True,
        "socket_timeout": 20, "retries": 3, "max_filesize": 1024 ** 3,
        "match_filter": match_filter_func(f"duration <= {MAX_VIDEO_SECONDS}"),
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url.strip(), download=True)
            path = Path(downloader.prepare_filename(info)) if info else None
    except yt_dlp.utils.DownloadError as error:
        reason = re.sub(r"\x1b\[[0-9;]*m", "", str(error)).replace("ERROR:", "").strip()
        raise ToolError(f"YouTube wouldn't give me that video ({reason[:140]}). Updating yt-dlp often fixes this.") from None
    if not info:
        raise ToolError("I skipped that video because it is longer than two hours.")
    if not path or not path.exists():
        path = next(iter(target.glob(f"*{info['id']}*")), None)
    if not path:
        raise ToolError("The download finished but I can't find the file.")
    return f"Downloaded '{info.get('title', 'the video')}' ({path.stat().st_size / 2 ** 20:.1f} MB) into the YouTube downloads folder."


TOOLS = [generate_business_names, get_disease_outbreak_stats, get_random_fact, get_random_activity, get_random_advice,
         get_dog_image, get_joke, password_cracking_demo, hack_a_random_profile, instagram_profile_picture, send_email,
         get_saved_wifi_password, download_youtube_video, lookup_free_game, lookup_minecraft_server]
