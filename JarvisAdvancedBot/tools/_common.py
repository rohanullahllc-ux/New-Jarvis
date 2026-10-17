"""Helpers shared by every tool module.

Tools return short plain-text results and raise ``ToolError`` with a message that is fine to
read aloud. Nothing in the tools package speaks or listens by itself.
"""
import ctypes
import html
import re
import time
import webbrowser
from urllib.parse import urlparse

import requests
from anthropic.lib.tools import ToolError

from config import DB_DIR

DB = DB_DIR                       # tests point this at a temporary folder
HTTP_TIMEOUT = 10
HEADERS = {"User-Agent": "JarvisAssistant/2.0 (personal voice assistant)"}   # Wikipedia, Nominatim... refuse anonymous clients

_cache = {}


class NotFoundError(ToolError):
    """The service answered, but has nothing under that name (HTTP 404)."""


class RateLimitedError(ToolError):
    """The service wants fewer requests (HTTP 429)."""


class RefusedError(ToolError):
    """The service understood the request and said no (other HTTP 4xx, such as 401 or 403)."""


def clear_cache():
    _cache.clear()


def _service(url):
    return (urlparse(url).hostname or "the service").removeprefix("www.")


def _failure(url, error):
    """Turn a network error into a ToolError that tells the user what actually went wrong."""
    name = _service(url)
    if isinstance(error, requests.HTTPError) and error.response is not None:
        code = error.response.status_code
        if code == 404:
            return NotFoundError(f"{name} has nothing under that name.")
        if code == 429:
            return RateLimitedError(f"{name} is limiting requests right now. Try again in a little while.")
        if code >= 500:
            return ToolError(f"{name} is having problems on its side (error {code}). Try again later.")
        return RefusedError(f"{name} refused the request (error {code}).")
    if isinstance(error, requests.Timeout):
        return ToolError(f"{name} took too long to answer.")
    if isinstance(error, requests.ConnectionError):
        return ToolError(f"I couldn't reach {name}. Check the internet connection.")
    return ToolError(f"{name} sent something I couldn't read.")


def _fetch(url, headers, timeout, params):
    try:
        response = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        raise _failure(url, error) from None


def get_json(url, headers=None, timeout=HTTP_TIMEOUT, cache_seconds=0, **params):
    """GET ``url`` and return its parsed JSON; every failure becomes a readable ToolError.

    ``cache_seconds`` keeps the answer in memory, which spares rate-limited services.
    """
    key = (url, tuple(sorted(params.items()))) if cache_seconds else None
    if key and key in _cache and time.time() - _cache[key][0] < cache_seconds:
        return _cache[key][1]
    response = _fetch(url, headers, timeout, params)
    try:
        data = response.json()
    except ValueError:
        raise _failure(url, ValueError()) from None
    if key:
        _cache[key] = (time.time(), data)
    return data


def get_text(url, headers=None, timeout=HTTP_TIMEOUT, **params):
    """GET ``url`` and return the body as text."""
    return _fetch(url, headers, timeout, params).text


def get_bytes(url, headers=None, timeout=HTTP_TIMEOUT, **params):
    """GET ``url`` and return the raw body (pictures, files)."""
    return _fetch(url, headers, timeout, params).content


def open_url(url):
    """Open a web page in the default browser (one place, so tests can intercept it)."""
    webbrowser.open(url)


def safe_filename(name):
    return re.sub(r"[^\w -]", "", name).strip()[:60]


def folder(name):
    """A folder inside DataBase, created if needed."""
    path = DB / name
    path.mkdir(parents=True, exist_ok=True)
    return path


CURRENCY_NAMES = {
    "USD": "US dollars", "PKR": "Pakistani rupees", "INR": "Indian rupees", "EUR": "euros", "GBP": "British pounds",
    "SAR": "Saudi riyals", "AED": "UAE dirhams", "JPY": "Japanese yen", "CNY": "Chinese yuan", "TRY": "Turkish lira",
    "CAD": "Canadian dollars", "AUD": "Australian dollars", "AFN": "Afghanis", "BDT": "Bangladeshi taka",
    "MYR": "Malaysian ringgit", "QAR": "Qatari riyals", "KWD": "Kuwaiti dinars",
}


def money(amount, code):
    """Format an amount the way it should be spoken, e.g. "27,698 Pakistani rupees"."""
    text = f"{amount:,.0f}" if amount >= 100 else f"{amount:,.2f}" if amount >= 1 else f"{amount:.4g}"
    return f"{text} {CURRENCY_NAMES.get(code.upper(), code.upper())}"


def plain(text):
    """Text from a website made fit to read aloud: no HTML entities, no decorative symbols, one space between words."""
    return " ".join(re.sub(r"[^\x20-\x7E]", " ", html.unescape(text or "")).split())


def first_sentences(text, count=2):
    """The first ``count`` sentences of ``text`` (for reading summaries aloud)."""
    return " ".join(re.split(r"(?<=[.!?])\s+", (text or "").strip())[:count])


def _open_clipboard(user32):
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    for _ in range(10):                              # another program may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ToolError("The clipboard is busy. Try again.")


def read_clipboard():
    """The text on the Windows clipboard, or "" when it holds something else (a picture, files...)."""
    CF_UNICODETEXT = 13
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _open_clipboard(user32)
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        pointer = kernel32.GlobalLock(handle) if handle else None
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def copy_to_clipboard(text):
    """Put ``text`` on the Windows clipboard (Unicode-safe, no external program)."""
    CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    data = (text + "\0").encode("utf-16-le")
    _open_clipboard(user32)
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ToolError("Windows would not accept the clipboard text.")
    finally:
        user32.CloseClipboard()
