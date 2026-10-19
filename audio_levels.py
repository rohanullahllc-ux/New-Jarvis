"""The Windows microphone volume and mute switch: read and changed through Windows' Core Audio, with no extra package.

A microphone left at a low input volume is the commonest reason a voice assistant misses words or hears only half a sentence, and
Windows gives no hint of it. Everything here runs a short PowerShell script (the first call takes a couple of seconds).

    python audio_levels.py              show the volume and mute state of the default microphone and speakers
    python audio_levels.py --mic 80     set the microphone volume to 80 percent
"""
import base64
import re
import subprocess
import sys

LOW_VOLUME = 50            # below this many percent the microphone is probably too quiet for speech recognition

_CODE = r"""
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
  int j();
  int GetMasterVolumeLevelScalar(out float pfLevel);
  int k(); int l(); int m(); int n();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
  int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class AudioInfo {
  static IAudioEndpointVolume Vol(int flow) {
    var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
    IMMDevice dev = null;
    Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(flow, 1, out dev));
    IAudioEndpointVolume epv = null;
    var id = typeof(IAudioEndpointVolume).GUID;
    Marshal.ThrowExceptionForHR(dev.Activate(ref id, 23, 0, out epv));
    return epv;
  }
  public static string State(int flow) {
    float v; bool mute;
    var e = Vol(flow);
    Marshal.ThrowExceptionForHR(e.GetMasterVolumeLevelScalar(out v));
    Marshal.ThrowExceptionForHR(e.GetMute(out mute));
    return Math.Round(v * 100) + "|" + mute;
  }
  public static void SetVolume(int flow, float level) {
    Marshal.ThrowExceptionForHR(Vol(flow).SetMasterVolumeLevelScalar(level, Guid.Empty));
  }
  public static void SetMute(int flow, bool mute) {
    Marshal.ThrowExceptionForHR(Vol(flow).SetMute(mute, Guid.Empty));
  }
}
"""
INPUT, OUTPUT = 1, 0       # Core Audio data flows: capture (microphone) and render (speakers)


class AudioError(Exception):
    """Windows would not tell, or would not change, the audio level."""


def _run(commands, timeout=40):
    script = "Add-Type -TypeDefinition @'\n" + _CODE + "\n'@\n" + commands
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")        # (no quoting problems that way)
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True,
                              text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AudioError(f"Windows did not answer about the audio level ({error})") from None
    if done.returncode != 0:
        detail = (done.stderr.strip().splitlines() or ["unknown error"])[0]
        raise AudioError(f"Windows would not give the audio level ({detail})")
    return done.stdout.strip()


def state(flow=INPUT):
    """(volume in percent, muted) of the default microphone (or speakers)."""
    found = re.fullmatch(r"(\d+)\|(True|False)", _run(f"[AudioInfo]::State({flow})").splitlines()[-1].strip())
    if not found:
        raise AudioError("Windows gave an answer I could not read")
    return int(found.group(1)), found.group(2) == "True"


def set_volume(percent, flow=INPUT):
    """Set the volume (1 to 100 percent) and return the new value."""
    percent = max(1, min(100, int(percent)))
    _run(f"[AudioInfo]::SetVolume({flow}, {percent / 100:.2f})")
    return state(flow)[0]


def set_muted(muted, flow=INPUT):
    _run(f"[AudioInfo]::SetMute({flow}, ${'true' if muted else 'false'})")


def advice(volume, muted):
    """A sentence about the microphone setting when it is the likely cause of missed words, or "" when it looks fine."""
    if muted:
        return "The microphone is muted in Windows, so Jarvis cannot hear anything. Say \"unmute the microphone\"."
    if volume < LOW_VOLUME:
        return (f"The microphone volume in Windows is only {volume} percent, which is why words go missing. "
                "Say \"set the microphone volume to 80\", or raise it in Settings, System, Sound, Input.")
    return ""


if __name__ == "__main__":
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "--mic":
            print(f"microphone volume is now {set_volume(int(sys.argv[2]))} percent")
        mic, speakers = state(INPUT), state(OUTPUT)
        print(f"microphone: {mic[0]} percent, {'MUTED' if mic[1] else 'not muted'}")
        print(f"speakers:   {speakers[0]} percent, {'MUTED' if speakers[1] else 'not muted'}")
        print(advice(*mic) or "The microphone setting looks fine.")
    except AudioError as error:
        print(error)
        sys.exit(1)
