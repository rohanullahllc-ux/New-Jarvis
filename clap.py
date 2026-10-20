"""Clap detection: listens to the microphone stream for a short, loud, wide-band burst that dies away quickly.

No model is involved, only the shape of the sound, which is why it costs almost no CPU. For every 10 ms of sound it compares the
loudness with the room's usual loudness (a slowly updated average) and calls it a clap only if ALL of these hold:

  * it is much louder than the room, and louder than a fixed minimum (so a quiet room's tiny noises never count),
  * it rose sharply: the 10 ms before it were far quieter (speech and music rise slowly),
  * it dies away fast: 50 to 80 ms later it is a fraction of its peak (a voice, a hum or a fan carries on),
  * it is wide-band: a good share of its energy is above 1.5 kHz (a thump on the desk or a door is mostly low sound),
  * what follows is noise, not a voice: the first consonant of a word ("tick", "take") is a sharp burst too, but it is followed by
    a vowel, which has a pitch, and a clap's tail has none.

CLAP_COUNT claps, each within one second of the one before and with the room gone quiet again in between (in speech the sound
carries on between the bangs), are a "clap pattern" (two by default, so one stray bang is not enough). Afterwards it ignores the
microphone for two seconds. CLAP_SENSITIVITY makes the loudness limits easier (above 1) or stricter (below 1).

    python clap.py --live       watch the microphone and print every clap and every near miss, to tune CLAP_SENSITIVITY
"""
import collections
import sys

import numpy as np

from config import CLAP_COUNT, CLAP_SENSITIVITY

RATE = 16000
SUBFRAME = RATE // 100            # 10 ms
LOUDER_THAN_ROOM = 10.0           # times the room's usual loudness (20 dB) at sensitivity 1
MINIMUM_LEVEL = 0.02              # of full scale (about -34 dB) at sensitivity 1
SHARP_RISE = 4.0                  # times the previous 10 ms
FADES_TO = 0.3                    # of the peak, 50 to 80 ms later
HIGH_SHARE = 0.25                 # least share of the energy above 1.5 kHz
PITCHED = 0.45                    # a tail this periodic (0 to 1) at 80 to 300 Hz is a voice, not a clap
QUIET_BETWEEN = 8.0               # between two claps the room is back to within this many times its usual loudness
MAX_GAP = 1.0                     # seconds between claps of one pattern
MIN_GAP = 0.12                    # a second "clap" this soon is the first one echoing
COOLDOWN = 2.0                    # seconds deaf after a pattern
CHECK_AFTER = 8                   # subframes (80 ms) after the start of a sound, when it is judged


def periodicity(samples):
    """How periodic the sound is at the pitch of a human voice (80 to 300 Hz): 0 (noise) to 1 (a pure tone)."""
    samples = samples - samples.mean()
    energy = float(samples @ samples)
    if energy < 1e-9 or len(samples) < 400:
        return 0.0
    full = np.correlate(samples, samples, mode="full")[len(samples) - 1:]
    return float(max(0.0, full[RATE // 300:RATE // 80 + 1].max()) / energy)


class ClapDetector:
    def __init__(self, count=CLAP_COUNT, sensitivity=CLAP_SENSITIVITY):
        self.count = max(1, int(count))
        self.sensitivity = max(0.1, float(sensitivity))
        self.reset()

    def reset(self):
        self.room = None                       # the room's usual loudness (RMS, 0 to 1)
        self.previous = 0.0                    # loudness of the last 10 ms
        self.leftover = np.zeros(0, dtype=np.float32)
        self.time = 0.0                        # seconds of sound seen so far (so tests do not depend on the clock)
        self.pending = None                    # a loud start waiting to be judged
        self.claps = []                        # (start, peak) of the claps of the current pattern
        self.history = collections.deque(maxlen=150)      # (time, loudness) of the last 1.5 s
        self.deaf_until = 0.0
        self.refractory_until = 0.0
        self.events = []                       # what happened: (time, "clap" | why it was not one, details), for --live and the tests

    # ---- the numbers for one 10 ms piece

    @staticmethod
    def _high_share(window):
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)))) ** 2
        frequencies = np.fft.rfftfreq(len(window), 1.0 / RATE)
        total = float(spectrum.sum()) or 1.0
        return float(spectrum[frequencies >= 1500].sum()) / total

    def _note(self, what, **details):
        self.events.append((round(self.time, 3), what, details))
        del self.events[:-200]

    # ---- the stream

    def feed(self, samples):
        """Give it the next piece of sound (any length; 16 kHz, 16-bit integers or floats from -1 to 1).
        Returns True when the clap pattern has just been completed."""
        samples = np.asarray(samples)
        samples = samples.astype(np.float32) / 32768.0 if samples.dtype.kind in "iu" else samples.astype(np.float32)
        data = np.concatenate([self.leftover, samples])
        whole = len(data) // SUBFRAME * SUBFRAME
        self.leftover = data[whole:]
        done = False
        for start in range(0, whole, SUBFRAME):
            if self._subframe(data[start:start + SUBFRAME]):
                done = True
        return done

    def _subframe(self, frame):
        """Look at 10 ms of sound. True if this completes the clap pattern."""
        rms = float(np.sqrt(np.mean(frame * frame)))
        self.time += SUBFRAME / RATE
        self.history.append((self.time, rms))
        triggered = False
        if self.room is None:
            self.room = max(rms, 1e-4)
        if self.pending is not None:
            self.pending["levels"].append(rms)
            self.pending["frames"].append(frame.copy())
            if len(self.pending["levels"]) > CHECK_AFTER:
                triggered = self._judge()
        elif self.time >= self.deaf_until and self.time >= self.refractory_until:
            limit = LOUDER_THAN_ROOM / self.sensitivity
            minimum = MINIMUM_LEVEL / self.sensitivity
            if rms > minimum and rms > self.room * limit and rms > self.previous * SHARP_RISE:
                self.pending = {"at": self.time - SUBFRAME / RATE, "peak": rms, "levels": [], "frames": [frame.copy()],
                                "louder": rms / self.room}
        if self.pending is None:
            self.room = max(1e-4, 0.985 * self.room + 0.015 * min(rms, self.room * 4))       # the room's loudness, slowly
        self.previous = rms
        return triggered

    def _judge(self):
        """Eighty milliseconds after a loud start: was it a clap? Returns True if that completed the pattern."""
        event, self.pending = self.pending, None
        peak = max(event["peak"], max(event["levels"]))
        tail = event["levels"][4:CHECK_AFTER]
        later = float(np.mean(tail))
        share = self._high_share(np.concatenate(event["frames"][:3]))               # the first 30 ms of the sound
        pitch = periodicity(np.concatenate(event["frames"][3:CHECK_AFTER])) if later > self.room * 3 else 0.0
        details = {"louder": round(event["louder"], 1), "fades_to": round(later / peak, 2), "high": round(share, 2),
                   "pitch": round(pitch, 2)}
        if later > peak * FADES_TO:
            self._note("not a clap: it goes on", **details)
            return False
        if share < HIGH_SHARE:
            self._note("not a clap: too much low sound (a thump)", **details)
            return False
        if pitch > PITCHED:
            self._note("not a clap: a voice follows it", **details)
            return False
        start = event["at"]
        self.refractory_until = start + MIN_GAP
        if self.claps and start - self.claps[-1][0] > MAX_GAP:
            self.claps.clear()
        if self.claps:                                         # between two claps the room goes quiet again; in speech it does not
            last_start, last_peak = self.claps[-1]
            between = [level for when, level in self.history if last_start + 0.10 <= when <= start - 0.02]
            if between and float(np.mean(between)) > max(self.room * QUIET_BETWEEN, last_peak * 0.15):
                self.claps.clear()
                self._note("not a pattern: the sound carries on between the bangs", **details)
        self.claps.append((start, peak))
        self._note("clap", number=len(self.claps), **details)
        if len(self.claps) >= self.count:
            self.claps.clear()
            self.deaf_until = self.time + COOLDOWN
            self._note("pattern complete", claps=self.count)
            return True
        return False


def live():
    """Print what the detector makes of the microphone, until Ctrl+C."""
    import listener
    detector = ClapDetector()
    print(f"Clap {detector.count} times (sensitivity {detector.sensitivity}). Also try typing, talking, a door, a cough: "
          f"each loud sound shows what the detector made of it. Ctrl+C stops.\n")
    seen = 0
    try:
        for block in listener.microphone_blocks():
            fired = detector.feed(block)
            for when, what, details in detector.events[seen:]:
                print(f"  {when:7.2f}s  {what}  {details}")
            seen = len(detector.events)
            if fired:
                print("  >>>>>>  CLAP PATTERN: Jarvis would wake now\n")
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
    else:
        print(__doc__)
