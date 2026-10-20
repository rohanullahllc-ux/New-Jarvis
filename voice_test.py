"""Test the whole voice chain on YOUR voice, in one go:

    python voice_test.py

Ten sentences are shown. Say each one after the beep. For every one it shows what Whisper (on this PC) heard and how long that took,
what Google heard (when the internet is there and STT_ENGINE allows it), and whether the voice lock would accept your voice. At
the end: how many each got exactly right. Nothing is saved except the results printed here.
"""
import re
import sys
import time

import speech_recognition as sr

import microphone
import speaker
import stt

SENTENCES = ["what time is it", "open the task folder", "add a task buy milk", "remove the last task", "set a timer for two minutes",
             "what is the weather in london", "show my notes", "make a to do list", "take a screenshot", "set the microphone volume to eighty"]
NUMBERS = {"two": "2", "eighty": "80", "five": "5", "ten": "10"}


def words(text):
    """The words of a sentence in a form that ignores the small differences that do not matter: ok/okay, digits, punctuation."""
    found = re.findall(r"[a-z0-9]+", (text or "").lower())
    return ["okay" if word == "ok" else NUMBERS.get(word, word) for word in found]


def same_words(heard, wanted):
    return words(heard) == words(wanted)


def main():
    if not microphone._ensure_ready():
        print("The microphone is not working. Run:  python microphone.py")
        return 1
    whisper_ok = stt.available()
    google_ok = stt.STT_ENGINE != "whisper"
    print(f"Whisper: {'ready (' + stt.STT_MODEL + ')' if whisper_ok else 'not set up (python stt.py --download)'} | "
          f"Google: {'allowed' if google_ok else 'switched off (STT_ENGINE=whisper)'} | "
          f"voice lock: {speaker.status()}\n")
    score = {"whisper": 0, "google": 0}
    times = []
    for number, sentence in enumerate(SENTENCES, 1):
        print(f"[{number}/{len(SENTENCES)}]  Say:  {sentence}")
        audio = None
        for _ in range(2):
            audio = microphone._capture(timeout=12, phrase_time_limit=10)
            if audio is not None:
                break
            print("   I did not hear anything; try again after the beep.")
        if audio is None:
            continue
        loud = microphone._louder(audio)
        line = []
        if whisper_ok:
            started = time.time()
            try:
                heard = stt.transcribe(loud)
            except stt.SpeechRecognitionFailed as error:
                heard = f"(failed: {error})"
            took = time.time() - started
            times.append(took)
            score["whisper"] += same_words(heard, sentence)
            line.append(f"Whisper: {heard!r} ({took:.1f}s){' OK' if same_words(heard, sentence) else ''}")
        if google_ok:
            try:
                said = sr.Recognizer().recognize_google(loud, language=microphone.LANGUAGE)
            except sr.UnknownValueError:
                said = ""
            except sr.RequestError:
                said = "(no internet)"
            score["google"] += same_words(said, sentence)
            line.append(f"Google: {said!r}{' OK' if same_words(said, sentence) else ''}")
        if speaker.lock_active():
            verdict = speaker.accept(audio)
            line.append(f"voice: {'yours' if verdict.ok else 'NOT accepted'}" + (f" ({verdict.score:.2f})" if verdict.score is not None else f" ({verdict.reason})"))
        print("   " + " | ".join(line) + "\n")
    microphone.close_microphone()
    print(f"Exactly right out of {len(SENTENCES)}:  " + ", ".join(f"{name} {count}" for name, count in score.items()
                                                                 if (name == "whisper" and whisper_ok) or (name == "google" and google_ok)))
    if times:
        print(f"Whisper took {sum(times) / len(times):.1f}s on average. (Small differences such as 'ok'/'okay' and '2'/'two' are not counted as mistakes.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
