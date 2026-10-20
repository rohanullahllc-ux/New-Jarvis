"""Windows integration: the shortcut that starts Jarvis when you log in, the desktop shortcut, and the Visual C++ runtime installer.

Shortcuts are made with PowerShell's WScript.Shell (sent encoded, so the "&" in "Rohaan & Co" and the spaces in paths are safe). Both
shortcuts start JarvisGUI.py with pythonw.exe, the Python that has no black console window. Nothing here needs administrator rights
except the Visual C++ runtime installer, which Windows asks you to allow itself.
"""
import os
import sys
from pathlib import Path

LINK_NAME = "Jarvis.lnk"
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def pythonw():
    """The Python without a console window that belongs to the Python running now (the console one if there is none)."""
    here = Path(sys.executable)
    other = here.with_name("pythonw.exe")
    return str(other if other.exists() else here)


def launcher(root):
    """(program, arguments, working folder) that start the Jarvis window."""
    root = Path(root)
    return pythonw(), f'"{root / "JarvisGUI.py"}"', str(root)


def startup_dir():
    base = os.environ.get("APPDATA", "")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" if base else None


def desktop_dir(effects):
    """The real Desktop folder (it is somewhere else when OneDrive keeps the Desktop)."""
    try:
        found = effects.powershell("[Environment]::GetFolderPath('Desktop')")
        if found:
            return Path(found)
    except Exception:                                    # noqa: BLE001
        pass
    return Path.home() / "Desktop"


def shortcut_script(link, target, arguments, workdir, icon="", description="Jarvis"):
    lines = ["$shell = New-Object -ComObject WScript.Shell",
             f"$link = $shell.CreateShortcut({_quote(link)})",
             f"$link.TargetPath = {_quote(target)}",
             f"$link.Arguments = {_quote(arguments)}",
             f"$link.WorkingDirectory = {_quote(workdir)}",
             f"$link.Description = {_quote(description)}"]
    if icon:
        lines.append(f"$link.IconLocation = {_quote(icon)}")
    lines.append("$link.Save()")
    return "\n".join(lines)


def create_shortcut(effects, link, root):
    """Make a shortcut file at ``link`` that starts Jarvis. Returns True if it now exists."""
    program, arguments, workdir = launcher(root)
    icon = Path(root) / "gui" / "resources" / "jarvis.ico"
    Path(link).parent.mkdir(parents=True, exist_ok=True)
    effects.powershell(shortcut_script(link, program, arguments, workdir, str(icon) if icon.exists() else ""))
    return Path(link).exists()


def starts_with_windows():
    folder = startup_dir()
    return bool(folder and (folder / LINK_NAME).exists())


def set_start_with_windows(effects, root, on):
    """Switch "start Jarvis when I log in" on or off. Returns the new state."""
    folder = startup_dir()
    if folder is None:
        return False
    link = folder / LINK_NAME
    if on:
        create_shortcut(effects, link, root)
    elif link.exists():
        link.unlink()
    return link.exists()


def desktop_shortcut(effects, root, on=True):
    link = desktop_dir(effects) / LINK_NAME
    if on:
        create_shortcut(effects, link, root)
    elif link.exists():
        link.unlink()
    return link.exists()


def run_elevated(effects, path, arguments):
    """Run an installer that needs administrator rights (Windows shows its own "Allow this app?" question). Returns its exit code,
    or None if it could not be started or the question was refused."""
    script = (f"try {{ $p = Start-Process -FilePath {_quote(path)} -ArgumentList {_quote(arguments)} -Verb RunAs -Wait -PassThru; "
              "Write-Output $p.ExitCode } catch { Write-Output 'REFUSED' }")
    try:
        out = effects.powershell(script, timeout=1800)
    except Exception:                                    # noqa: BLE001
        return None
    out = out.strip().splitlines()[-1] if out.strip() else ""
    return int(out) if out.lstrip("-").isdigit() else None
