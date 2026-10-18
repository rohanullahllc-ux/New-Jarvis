"""Web and media tools: open sites, search, play YouTube, press media keys."""
import re
import time
from typing import Literal
from urllib.parse import quote_plus

import requests
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from ._common import open_url


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
    open_url(url)
    return f"Opened {url}"


@beta_tool
def search_google(query: str) -> str:
    """Show Google search results in the browser. Use when the user wants to see results on screen.

    Args:
        query: What to search for.
    """
    open_url("https://www.google.com/search?q=" + quote_plus(query))
    return f"Opened Google results for {query}"


def _first_video(query):
    """The address of the first video YouTube finds for ``query``, or "" when it can't be found.

    YouTube's search page carries its results as data inside the page, so the first video id can be read from it."""
    try:
        page = requests.get("https://www.youtube.com/results", params={"search_query": query}, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}).text
    except requests.RequestException:
        return ""
    found = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', page)
    return f"https://www.youtube.com/watch?v={found.group(1)}" if found else ""


@beta_tool
def youtube(query: str, play: bool = True) -> str:
    """Play a video or song on YouTube, or show YouTube search results.

    Args:
        query: Video, song or topic.
        play: True to start playing the best match, False to just show search results.
    """
    video = _first_video(query) if play else ""
    if video:
        open_url(video)
        return f"Playing {query} on YouTube"
    open_url("https://www.youtube.com/results?search_query=" + quote_plus(query))
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


TOOLS = [open_website, search_google, youtube, media_control, youtube_control]
