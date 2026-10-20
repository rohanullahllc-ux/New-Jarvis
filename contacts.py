"""Your contacts, so that "send an email" can be answered with a name: "Ali" instead of "ali dot khan at gmail dot com".

Each contact has a name, an email address and (if you like) a phone number and a note. They are kept in DataBase/contacts.json (not in
git) and made and edited in the admin panel. The email command asks this module first; anything that is not a name it knows is read as an
address the way it always was.
"""
import difflib
import json
import os
import re
import tempfile
from pathlib import Path

import config

_cache = {"stamp": None, "path": None, "items": []}
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE = re.compile(r"\+?[0-9][0-9 ()\-]{4,20}")


def file():
    return config.DB_DIR / "contacts.json"


def clean_name(text):
    text = re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:to|my|the|email|mail|send it to|send to)\s+", "", text).strip()


def load(path=None):
    path = Path(path) if path else file()
    try:
        info = path.stat()
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        return []
    if _cache["path"] == str(path) and _cache["stamp"] == stamp:
        return list(_cache["items"])
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        items = [c for c in data if isinstance(c, dict) and c.get("name")] if isinstance(data, list) else []
    except (OSError, ValueError):
        items = []
    _cache.update(stamp=stamp, path=str(path), items=items)
    return list(items)


def save(items, path=None):
    path = Path(path) if path else file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".contacts-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump([{"name": c["name"], "email": c.get("email", ""), "phone": c.get("phone", ""), "note": c.get("note", "")} for c in items],
                      stream, indent=1, ensure_ascii=False)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _cache["stamp"] = None


def check(contact):
    """Tidy a contact and say whether it can be used: (ok, tidied contact, what is wrong in plain words)."""
    tidy = {key: re.sub(r"\s+", " ", str(contact.get(key, ""))).strip() for key in ("name", "email", "phone", "note")}
    if not tidy["name"] or not clean_name(tidy["name"]):
        return False, tidy, "Give the contact a name: the words you will say."
    if len(tidy["name"]) > 40:
        return False, tidy, "The name is too long (more than 40 letters)."
    if tidy["email"] and not _ADDRESS.fullmatch(tidy["email"]):
        return False, tidy, "An email address looks like name@example.com."
    if tidy["phone"] and not _PHONE.fullmatch(tidy["phone"]):
        return False, tidy, "A phone number has digits, and may have + ( ) - and spaces."
    if not tidy["email"] and not tidy["phone"]:
        return False, tidy, "Give an email address or a phone number."
    tidy["email"] = tidy["email"].lower()
    return True, tidy, ""


def find(spoken, items=None):
    """The contact that the spoken words name, or None."""
    items = load() if items is None else items
    wanted = clean_name(spoken)
    if not wanted or not items:
        return None
    names = {clean_name(c["name"]): c for c in items}
    if wanted in names:
        return names[wanted]
    close = difflib.get_close_matches(wanted, list(names), n=1, cutoff=0.85) if len(wanted) >= 3 else []
    return names[close[0]] if close else None


def email_for(spoken):
    """The email address of the contact named in ``spoken`` ("ali", "to my brother"), or None if it is not a name Jarvis knows
    (an address spoken or typed out is not looked up)."""
    lowered = spoken.lower()
    if "@" in lowered or (re.search(r"\bat\b", lowered) and re.search(r"\bdot\b", lowered)):
        return None                                      # an address, spoken or typed: not a name to look up
    contact = find(spoken)
    return (contact.get("email") or None) if contact else None
