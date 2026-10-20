"""Your own spoken shortcuts: "open college portal", "open my project folder", "open the budget sheet".

Each shortcut has a name (what you say), a kind (website, folder, file or program) and a target (the address, path or program name).
They are kept in DataBase/shortcuts.json (not in git: they are yours) and are made and edited in the admin panel. LocalBrain asks
this module first for every "open ..." command, so a shortcut wins over a built-in meaning of the same words.

The name is matched loosely: "open my college portal", "open the college portal website" and a speech-recognition slip such as
"collage portal" all find a shortcut called "college portal".
"""
import difflib
import json
import os
import re
import tempfile
from pathlib import Path

import config

KINDS = ("website", "folder", "file", "app")
KIND_LABELS = {"website": "A website", "folder": "A folder", "file": "A file or document", "app": "A program"}
MAX_NAME = 40
GENERIC_WORDS = {"shortcut", "website", "web site", "site", "page", "app", "application", "folder", "file", "link", "program"}
_GENERIC_TAIL = re.compile(r"(?:\s+(?:shortcut|website|web site|site|page|app|application|folder|file|link|program))+$")
_cache = {"stamp": None, "path": None, "items": []}


def file():
    return config.DB_DIR / "shortcuts.json"


def clean_name(text):
    """The name as it is compared: lower case, no punctuation, no "my"/"the" in front and no "website"/"folder" at the end."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(text).lower().replace("&", " and "))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:my|the|a|an)\s+", "", text)
    text = _GENERIC_TAIL.sub("", text).strip()
    return "" if text in GENERIC_WORDS else text


def load(path=None):
    """The shortcuts: [{'name', 'kind', 'target'}]. A missing or damaged file is simply no shortcuts."""
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
        items = [i for i in data if isinstance(i, dict) and i.get("name") and i.get("kind") in KINDS and i.get("target")] if isinstance(data, list) else []
    except (OSError, ValueError):
        items = []
    _cache.update(stamp=stamp, path=str(path), items=items)
    return list(items)


def save(items, path=None):
    """Write the shortcuts (safely: a temporary file, then swapped in)."""
    path = Path(path) if path else file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".shortcuts-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump([{"name": i["name"], "kind": i["kind"], "target": i["target"]} for i in items], stream, indent=1, ensure_ascii=False)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _cache["stamp"] = None


def check(item):
    """Tidy a shortcut and say whether it can be used: (ok, tidied item, what is wrong in plain words)."""
    name = re.sub(r"\s+", " ", str(item.get("name", ""))).strip()
    kind = str(item.get("kind", "")).strip().lower()
    target = str(item.get("target", "")).strip().strip('"')
    tidy = {"name": name, "kind": kind, "target": target}
    if not name:
        return False, tidy, "Give the shortcut a name: the words you will say."
    if len(name) > MAX_NAME:
        return False, tidy, f"The name is too long (more than {MAX_NAME} letters)."
    if not clean_name(name):
        return False, tidy, "The name needs some letters or numbers (and not only words like 'my', 'website' or 'folder')."
    if kind not in KINDS:
        return False, tidy, "Choose what it opens: a website, a folder, a file or a program."
    if not target:
        return False, tidy, "Say where it goes: the web address, the folder path, the file or the program."
    if kind == "website":
        if "://" not in target:
            if " " in target or "." not in target:
                return False, tidy, "A website needs an address such as www.example.com."
            tidy["target"] = "https://" + target
        elif not target.lower().startswith(("http://", "https://")):
            return False, tidy, "Only web addresses that start with http:// or https:// can be opened."
    elif kind == "folder":
        tidy["target"] = str(Path(target).expanduser())
    return True, tidy, ""


def find(spoken, items=None):
    """The shortcut that the spoken words name, or None."""
    items = load() if items is None else items
    wanted = clean_name(spoken)
    if not wanted or not items:
        return None
    names = {clean_name(i["name"]): i for i in items}
    if wanted in names:
        return names[wanted]
    if len(wanted) >= 4:
        close = difflib.get_close_matches(wanted, list(names), n=1, cutoff=0.88)
        if close and len(close[0].split()) == len(wanted.split()):
            return names[close[0]]
    return None


def problems(item):
    """What is probably wrong with a saved shortcut (the folder or file is gone), or ''. Only looked at, never fixed."""
    kind, target = item["kind"], item["target"]
    if kind == "folder" and not Path(target).expanduser().is_dir():
        return "that folder does not exist"
    if kind == "file" and not Path(target).expanduser().exists():
        return "that file does not exist"
    if kind == "app" and re.search(r"[\\/]", target) and not Path(target).exists():
        return "that program is not there"
    return ""


def open_it(item):
    """Open the shortcut. Raises ToolError (a message Jarvis can say) if it cannot be."""
    from anthropic.lib.tools import ToolError
    from JarvisAdvancedBot import tools
    kind, target = item["kind"], item["target"]
    if kind == "website":
        tools.open_website(target)
    elif kind == "app":
        if re.search(r"[\\/]", target):
            if not Path(target).exists():
                raise ToolError(f"The program for {item['name']} is not where it was: {target}")
            os.startfile(target)
        else:
            tools.open_app(target)
    else:
        path = Path(target).expanduser()
        if not path.exists():
            raise ToolError(f"{item['name']} points to {target}, which does not exist any more.")
        if kind == "folder" and not path.is_dir():
            raise ToolError(f"{item['name']} points to {target}, which is not a folder.")
        os.startfile(str(path))
    return item["name"]
