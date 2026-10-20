"""Back up and bring back everything personal in Jarvis: your settings and password, notes, tasks, voice print, face model,
shortcuts, contacts and (if you want) the downloaded models.

    python backup_jarvis.py --list                  what there is to back up and how big it is
    python backup_jarvis.py --to F:\\               make a backup folder inside F:\\  (add --models to include the big downloaded models)
    python backup_jarvis.py --find                  look for backups on this PC's drives
    python backup_jarvis.py --restore "F:\\Jarvis-Backup-2026-10-20_2130"     bring one back (nothing is ever deleted or overwritten
                                                    without a copy: replaced files are moved to Backups/replaced-before-restore-...)

A backup is a plain folder (not encrypted): Jarvis-Backup-<date>_<time>/ with the files in files/, a list with a SHA-256 of every
file in BACKUP.json, and a README.txt. Keep it somewhere private: it holds your .env (passwords and keys) and your voice print.

It also understands the whole-project copies made by hand (a folder that contains config.py, Startup.py and your DataBase/): the
setup wizard uses that to restore from a copy of the Jarvis folder itself.

Standard library only (the setup wizard runs before anything is installed).
"""
import datetime
import hashlib
import json
import os
import shutil
import string
import sys
from collections import namedtuple
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules"}
BACKUP_NAME = "Jarvis-Backup-"

# part id -> (what it is called, the paths in the project folder, whether it is big and left out unless asked)
PARTS = {
    "settings": ("Settings and password (.env)", [".env"], False),
    "notes": ("Notes, to-do lists, time table and what you told him to remember",
              ["DataBase/Notes", "DataBase/NotePad", "DataBase/Tasks", "DataBase/TimeTable", "DataBase/memory.json"], False),
    "shortcuts": ("Your shortcuts and contacts", ["DataBase/shortcuts.json", "DataBase/contacts.json"], False),
    "voice": ("Your voice print", ["DataBase/voiceprint.npz"], False),
    "face": ("Your face photos and face model", ["DataBase/FaceDetectionModule/samples", "DataBase/FaceDetectionModule/trainer"], False),
    "files": ("Books, screenshots, downloads and saved passwords",
              ["DataBase/Books", "DataBase/ScreenShot", "DataBase/Downloads", "DataBase/Passwords", "DataBase/API Keys"], False),
    "logs": ("Records of your conversations", ["Logs/conversations"], False),
    "training": ("The sentences you really said, and the language model's reports", ["training/nlu_real.txt", "training/reports"], False),
    "models": ("The downloaded models (voices, Whisper, wake word, language model)", ["models"], True),
}
Backup = namedtuple("Backup", "path kind created label")        # kind: package (made by this tool) | project (a copy of the whole Jarvis folder)


def _files_under(path):
    """Every file under ``path`` (or the file itself), leaving out folders that are rebuilt anyway."""
    path = Path(path)
    if path.is_file():
        yield path
        return
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root=None, source_files=None):
    """{part: {'label', 'paths': [existing relative paths], 'files': n, 'bytes': n, 'big': bool}} for what exists in ``root``
    (the project folder; or, for a package backup, its files/ folder)."""
    base = Path(source_files or root or BASE_DIR)
    found = {}
    for part, (label, paths, big) in PARTS.items():
        existing, count, size = [], 0, 0
        for rel in paths:
            target = base / rel
            if target.exists():
                files = [f for f in _files_under(target) if f.is_file()]
                if files:
                    existing.append(rel)
                    count += len(files)
                    size += sum(f.stat().st_size for f in files)
        if existing:
            found[part] = {"label": label, "paths": existing, "files": count, "bytes": size, "big": big}
    return found


def human(size):
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024.0


# ---------------------------------------------------------------- making a backup

def make_backup(destination_parent, root=None, parts=None, progress=None):
    """Copy the chosen parts (default: everything except the big models) into a new Jarvis-Backup-<date>_<time> folder inside
    ``destination_parent``. Returns the folder. ``progress(text)`` hears what is happening."""
    root = Path(root or BASE_DIR)
    destination_parent = Path(destination_parent)
    parts = list(parts) if parts is not None else [p for p, (_, _, big) in PARTS.items() if not big]
    if not destination_parent.exists():
        raise FileNotFoundError(f"{destination_parent} does not exist")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    final = destination_parent / f"{BACKUP_NAME}{stamp}"
    number = 1
    while final.exists():
        number += 1
        final = destination_parent / f"{BACKUP_NAME}{stamp}-{number}"
    building = final.with_name(final.name + ".partial")
    files_dir = building / "files"
    files_dir.mkdir(parents=True)
    manifest = {"made": datetime.datetime.now().isoformat(timespec="seconds"), "tool": "backup_jarvis.py", "version": 1,
                "from": str(root), "computer": os.environ.get("COMPUTERNAME", ""), "parts": parts, "files": {}}
    present = inventory(root)
    try:
        for part in parts:
            if part not in present:
                continue
            if progress:
                progress(f"copying {PARTS[part][0]} ({human(present[part]['bytes'])})")
            for rel in present[part]["paths"]:
                for source in _files_under(root / rel):
                    relative = source.relative_to(root).as_posix()
                    target = files_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    digest = _digest(target)
                    manifest["files"][relative] = {"sha256": digest, "bytes": target.stat().st_size, "part": part}
        (building / "BACKUP.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        (building / "README.txt").write_text(_readme(manifest), encoding="utf-8")
        building.rename(final)
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise
    return final


def _readme(manifest):
    return (f"JARVIS BACKUP (plain copy, NOT encrypted)\nMade: {manifest['made']} from {manifest['from']}\n\n"
            f"{len(manifest['files'])} files in files/ (a SHA-256 of each is in BACKUP.json).\n"
            "It holds your .env (passwords and keys), your voice print, notes and tasks: keep this folder private.\n\n"
            "To bring it back: run Setup-Jarvis.bat and choose to restore, or  python backup_jarvis.py --restore \"<this folder>\"\n"
            "Nothing is deleted when restoring; a file that would be replaced is first moved to Backups/replaced-before-restore-...\n")


def verify_backup(folder):
    """[problems] - empty if every file listed in BACKUP.json is there with the right SHA-256."""
    folder = Path(folder)
    manifest = json.loads((folder / "BACKUP.json").read_text(encoding="utf-8"))
    problems = []
    for relative, info in manifest["files"].items():
        target = folder / "files" / relative
        if not target.exists():
            problems.append(f"missing: {relative}")
        elif _digest(target) != info["sha256"]:
            problems.append(f"changed: {relative}")
    return problems


# ---------------------------------------------------------------- starting over

START_OVER_PARTS = ("settings", "notes", "shortcuts", "voice", "face", "logs")      # what "brand new" clears; books, screenshots and models stay


def start_over(root=None, parts=START_OVER_PARTS, progress=None):
    """Make this Jarvis brand new, safely: first everything that would be cleared is copied into Backups/ and every copied file is
    checked (SHA-256); only if all of them check out is anything cleared. Returns (the backup folder, number of files cleared), or
    (None, 0) when there was nothing of the owner's to clear. Raises RuntimeError, having cleared nothing, if the copy cannot be trusted."""
    root = Path(root or BASE_DIR)
    present = inventory(root)
    chosen = [part for part in parts if part in present]
    if not chosen:
        return None, 0
    parent = root / "Backups"
    parent.mkdir(exist_ok=True)
    saved = make_backup(parent, root=root, parts=chosen, progress=progress)
    problems = verify_backup(saved)
    if problems:
        raise RuntimeError(f"the copy in {saved} did not check out ({problems[0]}), so nothing was cleared")
    removed = 0
    for part in chosen:
        for relative in present[part]["paths"]:
            target = root / relative
            removed += len([f for f in _files_under(target) if f.is_file()])
            if target.is_dir():
                shutil.rmtree(target)
                target.mkdir()
            else:
                target.unlink()
    notebook = root / "DataBase" / "setup_state.json"
    if notebook.exists():
        notebook.unlink()
    if progress:
        progress(f"cleared {removed} files; the copy is in {saved}")
    return saved, removed


# ---------------------------------------------------------------- finding backups

def _drive_roots():
    if os.name != "nt":
        return []
    return [Path(f"{letter}:/") for letter in string.ascii_uppercase if Path(f"{letter}:/").exists()]


def _looks_like_project(path):
    return (path / "config.py").is_file() and (path / "Startup.py").is_file()


def _read_made(folder):
    try:
        return datetime.datetime.fromisoformat(json.loads((folder / "BACKUP.json").read_text(encoding="utf-8"))["made"])
    except (OSError, ValueError, KeyError):
        return None


def find_backups(roots=None, depth=3):
    """Backups found on the drives (or in ``roots``): our own Jarvis-Backup-* folders, and copies of the whole Jarvis folder.
    Newest first. Only the first few levels of each drive are looked at, so this takes a second or two."""
    found, seen = [], set()
    roots = [Path(r) for r in roots] if roots else _drive_roots()

    def look(folder, level):
        if level > depth:
            return
        try:
            children = [c for c in folder.iterdir() if c.is_dir() and c.name not in SKIP_DIRS and not c.name.startswith("$")]
        except OSError:
            return
        for child in children:
            key = str(child).lower()
            if key in seen:
                continue
            seen.add(key)
            if child.name.startswith(BACKUP_NAME) and (child / "BACKUP.json").is_file() and (child / "files").is_dir():
                found.append(Backup(child, "package", _read_made(child), f"Jarvis backup {child.name[len(BACKUP_NAME):]}"))
                continue
            if _looks_like_project(child) and child.resolve() != BASE_DIR.resolve():
                made = datetime.datetime.fromtimestamp(child.stat().st_mtime)
                found.append(Backup(child, "project", made, f"A copy of the Jarvis folder ({child.parent.name}\\{child.name})"))
                continue
            low = child.name.lower()
            if level < depth and (level == 1 or any(word in low for word in ("backup", "jarvis", "python", "assistant"))):
                look(child, level + 1)
    for root in roots:
        look(root, 1)
    return sorted(found, key=lambda b: b.created or datetime.datetime.min, reverse=True)


def ollama_models_beside(backup_path):
    """A folder of Ollama models saved next to a whole-project copy (Backup-.../Jarvis/ollama-models/models), or None."""
    backup_path = Path(backup_path)
    for candidate in (backup_path.parent / "ollama-models" / "models", backup_path / "ollama-models" / "models", backup_path.parent.parent / "ollama-models" / "models"):
        if (candidate / "manifests").is_dir() and (candidate / "blobs").is_dir():
            return candidate
    return None


# ---------------------------------------------------------------- bringing a backup back

def source_folder(backup):
    """Where the files of a backup are: files/ for our own, the folder itself for a whole-project copy."""
    return Path(backup.path) / "files" if backup.kind == "package" else Path(backup.path)


def plan_restore(backup, root=None, parts=None):
    """What restoring would do: {'copy': [relative paths missing here], 'same': n, 'differ': [relative paths that differ], 'bytes': n}."""
    root = Path(root or BASE_DIR)
    base = source_folder(backup)
    parts = parts if parts is not None else list(inventory(source_files=base))
    plan = {"copy": [], "same": 0, "differ": [], "bytes": 0}
    available = inventory(source_files=base)
    for part in parts:
        for rel in available.get(part, {}).get("paths", []):
            for source in _files_under(base / rel):
                relative = source.relative_to(base).as_posix()
                target = root / relative
                if not target.exists():
                    plan["copy"].append(relative)
                    plan["bytes"] += source.stat().st_size
                elif target.stat().st_size == source.stat().st_size and _digest(target) == _digest(source):
                    plan["same"] += 1
                else:
                    plan["differ"].append(relative)
                    plan["bytes"] += source.stat().st_size
    return plan


def restore(backup, root=None, parts=None, conflict="keep_newer", progress=None):
    """Copy a backup's files into the project folder. ``conflict`` says what to do when a file is already there and different:
    'keep' leaves yours, 'replace' takes the backup's, 'keep_newer' takes whichever was changed last. A file that is replaced is
    first moved to Backups/replaced-before-restore-<time>/ , so nothing is ever lost. Returns counts."""
    root = Path(root or BASE_DIR)
    base = source_folder(backup)
    plan = plan_restore(backup, root, parts)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = root / "Backups" / f"replaced-before-restore-{stamp}"
    done = {"copied": 0, "replaced": 0, "kept": 0, "same": plan["same"]}

    def put(relative):
        source, target = base / relative, root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for relative in plan["copy"]:
        put(relative)
        done["copied"] += 1
    for relative in plan["differ"]:
        source, target = base / relative, root / relative
        take = conflict == "replace" or (conflict == "keep_newer" and source.stat().st_mtime > target.stat().st_mtime)
        if not take:
            done["kept"] += 1
            continue
        moved = aside / relative
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(moved))
        put(relative)
        done["replaced"] += 1
    if progress:
        progress(f"restored {done['copied'] + done['replaced']} files ({done['same']} already the same, {done['kept']} of yours kept)")
    return done


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--list" in args or not args:
        for part, info in inventory().items():
            print(f"  {part:10} {info['files']:>6} files {human(info['bytes']):>10}  {info['label']}{'  (big: only with --models)' if info['big'] else ''}")
    if "--to" in args:
        target = Path(args[args.index("--to") + 1])
        chosen = [p for p, (_, _, big) in PARTS.items() if not big or "--models" in args]
        print("backup made:", make_backup(target, parts=chosen, progress=print))
    if "--find" in args:
        for item in find_backups():
            print(f"  {item.kind:8} {item.created:%Y-%m-%d %H:%M}  {item.path}") if item.created else print(f"  {item.kind:8} {item.path}")
    if "--restore" in args:
        path = Path(args[args.index("--restore") + 1])
        kind = "package" if (path / "BACKUP.json").is_file() else "project"
        print(restore(Backup(path, kind, None, path.name), progress=print))
