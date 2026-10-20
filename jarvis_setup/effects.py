"""Everything the wizard does to the outside world goes through this one class: running a program, downloading a file, asking
PowerShell something, checking that an installer is signed. The tests hand the wizard a stand-in with the same methods, so no test
installs, downloads or runs anything.

Paths such as "C:\\Users\\Rohaan & Co\\..." contain spaces and an ampersand. Programs are therefore always started from a list
of arguments (never through a shell line), and PowerShell scripts are sent encoded, so nothing is ever re-read as another command.
"""
import base64
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

RunResult = namedtuple("RunResult", "returncode output")
Signature = namedtuple("Signature", "status subject")
USER_AGENT = "Jarvis-Setup/1.0 (+https://github.com/rohanullahllc-ux/New-Jarvis)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DownloadError(Exception):
    """A file could not be downloaded; the message says why in plain words."""


def _why(error):
    if isinstance(error, urllib.error.HTTPError):
        return f"the server answered {error.code} {error.reason}"
    reason = getattr(error, "reason", error)
    return f"{reason}"


class Effects:
    # ---- programs

    def run(self, command, cwd=None, env=None, timeout=None, on_line=None):
        """Run a program and collect what it prints. ``on_line(text)`` is called for each line as it appears. Returns RunResult."""
        merged = None if env is None else {**os.environ, **env}
        try:
            process = subprocess.Popen(command, cwd=cwd, env=merged, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except OSError as error:
            return RunResult(-1, f"could not start {command[0]}: {error}")
        lines = []

        def pump():
            for line in process.stdout:
                line = line.rstrip("\r\n")
                lines.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:                          # noqa: BLE001 - a faulty listener must not stop the program being read
                        pass
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)                      # (a program that prints nothing for ever is still stopped on time)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()
        reader.join(10)
        try:
            process.stdout.close()
        except OSError:
            pass
        if timed_out:
            lines.append(f"(stopped after {timeout} seconds)")
        return RunResult(process.returncode if process.returncode is not None else -1, "\n".join(lines))

    def run_visible(self, command, cwd=None, env=None):
        """Run a program that talks to the user itself (it keeps the console: a question, a camera window). Returns its exit code."""
        merged = None if env is None else {**os.environ, **env}
        try:
            return subprocess.call(command, cwd=cwd, env=merged)
        except OSError:
            return -1

    def start_detached(self, command):
        """Start a program that keeps running after the wizard ends (Ollama's server). True if it started."""
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                             creationflags=(0x00000008 | NO_WINDOW) if os.name == "nt" else 0)       # DETACHED_PROCESS | CREATE_NO_WINDOW
            return True
        except OSError:
            return False

    def powershell(self, script, timeout=60):
        """Run a PowerShell script and return what it printed (stdout). Raises OSError/RuntimeError if it could not run."""
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                              capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        if done.returncode != 0:
            detail = (done.stderr.strip().splitlines() or ["unknown error"])[0]
            raise RuntimeError(f"PowerShell failed: {detail}")
        return done.stdout.strip()

    def signature(self, path):
        """The Authenticode signature of an installer: Signature(status, subject). status 'Valid' means it is signed and untampered."""
        quoted = str(path).replace("'", "''")
        try:
            out = self.powershell(f"$s = Get-AuthenticodeSignature -LiteralPath '{quoted}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\"")
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return Signature("Unknown", "")
        status, _, subject = out.partition("|")
        return Signature(status.strip() or "Unknown", subject.strip())

    # ---- the network

    def http_json(self, url, timeout=3):
        """Fetch a small JSON answer (Ollama's local server), or None if there is none."""
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            return None

    def reachable(self, url, timeout=6):
        """True if the address answers at all (any answer, even an error page, means the internet works)."""
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
            with urllib.request.urlopen(request, timeout=timeout):
                return True
        except urllib.error.HTTPError as error:
            error.close()
            return True
        except (OSError, ValueError):
            return False

    def fetch(self, url, dest, progress=None, expected_size=None, retries=3):
        """Download ``url`` to ``dest`` (resuming a half-finished download), checking the size. Returns the Path.

        ``progress(done_bytes, total_bytes)`` is called a few times a second. Raises DownloadError with a plain sentence."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if expected_size and dest.exists() and dest.stat().st_size == expected_size:
            return dest
        part = dest.with_name(dest.name + ".part")
        last_error = "unknown problem"
        for attempt in range(1, retries + 1):
            try:
                have = part.stat().st_size if part.exists() else 0
                headers = {"User-Agent": USER_AGENT}
                if have:
                    headers["Range"] = f"bytes={have}-"
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                    resumed = response.status == 206
                    if have and not resumed:
                        have = 0                                    # the server sent the whole file again
                    length = response.headers.get("Content-Length")
                    total = (int(length) + have) if length and length.isdigit() else expected_size
                    shown = time.time()
                    with open(part, "ab" if resumed else "wb") as handle:
                        done = have
                        while True:
                            chunk = response.read(1 << 20)
                            if not chunk:
                                break
                            handle.write(chunk)
                            done += len(chunk)
                            if progress and time.time() - shown > 0.25:
                                progress(done, total)
                                shown = time.time()
                if total and part.stat().st_size != total:
                    raise OSError(f"only {part.stat().st_size} of {total} bytes arrived")
                os.replace(part, dest)
                if progress:
                    progress(dest.stat().st_size, dest.stat().st_size)
                return dest
            except (OSError, ValueError, http.client.HTTPException) as error:        # (a connection cut short is an HTTPException, not an OSError)
                last_error = _why(error)
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
                if isinstance(error, urllib.error.HTTPError) and error.code == 416 and part.exists():
                    os.replace(part, dest)                          # "nothing more to send": the earlier try had in fact got it all
                    return dest
                if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403, 404):
                    break                                           # trying again will not help
                time.sleep(min(10, 2 * attempt))
        raise DownloadError(f"could not download {url} ({last_error}). Check the internet connection and run the setup again; "
                            "it carries on where it stopped.")

    def open_url(self, url):
        try:
            os.startfile(url)                                       # (Windows: opens the default browser)
        except (AttributeError, OSError):
            import webbrowser
            webbrowser.open(url)
