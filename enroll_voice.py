"""Teach Jarvis your voice, so that he only answers you.

    python enroll_voice.py            record about 16 sentences and make your voice print (about three minutes)
    python enroll_voice.py --test     say things and see, live, whether Jarvis would accept your voice (and what score it got)
    python enroll_voice.py --status   say whether a voice print exists and what the lock is set to
    python enroll_voice.py --delete   forget your voice print

Sit where you normally sit, speak the way you normally speak to Jarvis (not slowly, not loudly) and keep the room as it usually
is. The voice print is saved in DataBase/voiceprint.npz. It never leaves this PC and is not in git.
"""
import sys

import microphone
import speaker
from stt import samples_of

PROMPTS = [
    "Hey Jarvis, what time is it?",
    "Jarvis, open the task folder.",
    "Add a task, buy milk and call Ali.",
    "Please remove the last task from my list.",
    "Set a timer for two minutes.",
    "What is the weather in London today?",
    "Show me my notes, and read the newest one.",
    "Make a to do list for tomorrow.",
    "Take a screenshot and open the screenshots folder.",
    "Tell me a joke, and then tell me another one.",
    "How much battery is left on this laptop?",
    "Good evening Jarvis, how are you doing tonight?",
    "Open the downloads folder and show me the latest file.",
    "Play some music, and turn the volume up a little.",
    "The quick brown fox jumps over the lazy dog.",
    "Remind me to call my brother at five o'clock this evening.",
]


def _ready():
    if not speaker.model_ready():
        if speaker.MODEL_FILE.exists():
            print("The sherpa-onnx library is not installed:  pip install sherpa-onnx")
            return False
        print("Downloading the voice model (26 MB, once)...")
        try:
            speaker.download_model()
        except OSError as error:
            print(f"Could not download it ({error}). Check the internet connection and run again.")
            return False
    if not microphone._ensure_ready():
        print("The microphone is not working. Run:  python microphone.py")
        return False
    return True


def _record():
    """One phrase from the microphone as 16 kHz samples, or None if nothing was heard."""
    for _ in range(3):
        audio = microphone._capture(timeout=15, phrase_time_limit=12)
        if audio is not None:
            return samples_of(audio), audio
        print("   I did not hear anything. Speak after the beep, a little closer to the microphone.")
    return None, None


def enroll():
    if not _ready():
        return 1
    print(__doc__.split("\n\n")[1])
    print(f"I will show {len(PROMPTS)} sentences. Say each one after it appears (the first time there is a beep).\n")
    clips = []
    for number, prompt in enumerate(PROMPTS, 1):
        print(f"[{number}/{len(PROMPTS)}]  Say:  {prompt}")
        samples, _ = _record()
        if samples is None:
            print("   Skipping this one.")
            continue
        speech, seconds = speaker.speech_part(samples)
        if seconds < speaker.MIN_ENROLL:
            print(f"   That was only {seconds:.1f} s of speech, too short to learn from. It will be left out; carry on.")
        clips.append(samples)
    microphone.close_microphone()
    try:
        result = speaker.enroll(clips)
    except ValueError as error:
        print(f"\nNot enough to learn your voice: {error}\nRun this again in a quieter room, closer to the microphone.")
        return 1
    print(f"\nDone. Learned your voice from {result['used']} sentences ({result['skipped']} left out).")
    print(f"  How alike your own sentences are to each other: lowest {result['lowest']:.2f}, average {result['mean']:.2f}")
    print(f"  A voice must score at least {result['threshold']:.2f} to be accepted (set VOICE_MATCH in .env to change it).")
    print("  Test it now with:  python enroll_voice.py --test")
    print("  The lock is on by default once you have enrolled (VOICE_LOCK=auto). Say 'turn off the voice lock' or set VOICE_LOCK=off to stop it.")
    return 0


def test():
    if not speaker.enrolled():
        print("There is no voice print yet. Run:  python enroll_voice.py")
        return 1
    if not _ready():
        return 1
    print(f"A voice must score {speaker.threshold():.2f} or more. Say anything; press Ctrl+C to stop.\n")
    try:
        while True:
            samples, audio = _record()
            if samples is None:
                continue
            verdict = speaker.accept(audio) if speaker.lock_active() else speaker.Verdict(True, None, "off")
            speech, seconds = speaker.speech_part(samples)
            try:
                value = speaker.score(speech) if seconds >= 0.4 else None
            except speaker.SpeakerUnavailable as error:
                print(f"   cannot judge: {error}")
                continue
            shown = "too short to judge" if value is None else f"score {value:.2f}"
            print(f"   {shown} ({seconds:.1f} s of speech): {'ACCEPTED' if verdict.ok else 'REJECTED'} ({verdict.reason})\n")
    except KeyboardInterrupt:
        print()
    finally:
        microphone.close_microphone()
    return 0


if __name__ == "__main__":
    if "--delete" in sys.argv:
        print("Voice print deleted." if speaker.delete_print() else "There was no voice print.")
        sys.exit(0)
    if "--status" in sys.argv:
        print(speaker.status())
        print(f"Voice print file: {speaker.PRINT_FILE} ({'exists' if speaker.enrolled() else 'not made yet'}); model: "
              f"{'downloaded' if speaker.MODEL_FILE.exists() else 'not downloaded'}")
        sys.exit(0)
    sys.exit(test() if "--test" in sys.argv else enroll())
