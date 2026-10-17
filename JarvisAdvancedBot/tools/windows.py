"""Windows tools: open and close programs, keyboard shortcuts, screenshots, power, folders and Jarvis's own mini-apps."""
import ctypes
import datetime
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Literal

import psutil
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from gui.utils import launcher
from ._common import folder, safe_filename

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
    if "." not in name or name.lower().endswith(".exe"):      # never "open" a document by accident
        try:
            os.startfile(name)       # Windows' own lookup finds registered programs: chrome, notepad, calc ...
            return f"Opened {name}"
        except OSError:
            pass
    import keyboard                  # Store apps and the rest: type the name into the Start menu
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
    target = folder("ScreenShot")
    name = safe_filename(name) or datetime.datetime.now().strftime("screenshot-%Y%m%d-%H%M%S")
    pyautogui.screenshot().save(target / f"{name}.png")
    return f"Saved the screenshot as {name}.png"


# ---------------------------------------------------------------- power

POWER_VERBS = {"shutdown": "shut down", "restart": "restart", "sleep": "put to sleep", "lock": "lock"}


@beta_tool
def system_power_action(action: Literal["shutdown", "restart", "sleep", "lock", "cancel"],
                        confirmed: bool = False, delay_seconds: int = 15) -> str:
    """Shut down, restart, sleep or lock this PC, or cancel a pending shutdown or restart.

    IMPORTANT: this is disruptive. First ask the user to confirm this exact action, and only call it with
    confirmed=true after they have clearly said yes. Shutdown and restart wait delay_seconds so they can be
    cancelled with action="cancel".

    Args:
        action: shutdown, restart, sleep, lock, or cancel (stops a pending shutdown/restart).
        confirmed: True only after the user has explicitly agreed to this action.
        delay_seconds: Seconds to wait before a shutdown or restart (5 to 120).
    """
    if action == "cancel":
        result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        if result.returncode != 0:
            raise ToolError("There is no shutdown or restart waiting to be cancelled.")
        return "Cancelled. The PC will not shut down."
    if not confirmed:
        raise ToolError(f"That would {POWER_VERBS[action]} the PC. Ask the user to confirm first, "
                        f"then call again with confirmed set to true.")
    delay = max(5, min(int(delay_seconds), 120))
    if action in ("shutdown", "restart"):
        flag = "/s" if action == "shutdown" else "/r"
        subprocess.run(["shutdown", flag, "/t", str(delay)], check=True, capture_output=True)
        return f"The PC will {POWER_VERBS[action]} in {delay} seconds. Say cancel shutdown to stop it."
    if action == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "Locked the screen."
    subprocess.Popen(["powershell", "-NoProfile", "-Command",
                      "Add-Type -AssemblyName System.Windows.Forms; "
                      "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false) | Out-Null"],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "Putting the PC to sleep."


# ---------------------------------------------------------------- folders and Jarvis's own windows

KNOWN_FOLDERS = ("desktop", "documents", "downloads", "pictures", "music", "videos")


@beta_tool
def open_folder(location: str) -> str:
    """Open a drive or folder in File Explorer.

    Args:
        location: A drive letter such as "D", a full path, or one of: desktop, documents, downloads, pictures, music, videos.
    """
    text = location.strip().strip('"')
    drive = re.fullmatch(r"(?:drive |disk |local disk )?([A-Za-z]):?\\?", text, flags=re.I)
    if drive:
        path = Path(f"{drive.group(1).upper()}:\\")
    elif text.lower() in KNOWN_FOLDERS:
        path = Path.home() / text.title()
    else:
        path = Path(text).expanduser()
    if not path.is_dir():
        raise ToolError(f"I can't find a folder or drive called {location}.")
    os.startfile(str(path))
    return f"Opened {path}"


@beta_tool
def open_utility_app(name: Literal["calculator", "calendar", "currency_converter"]) -> str:
    """Open one of Jarvis's own small windows: a calculator, a month calendar, or a currency converter.

    Args:
        name: calculator, calendar or currency_converter.
    """
    try:
        launcher.launch(name)
    except FileNotFoundError as error:
        raise ToolError(str(error)) from None
    return f"Opened the {name.replace('_', ' ')}."


TOOLS = [open_app, close_app, windows_action, browser_action, take_screenshot, system_power_action, open_folder,
         open_utility_app]
