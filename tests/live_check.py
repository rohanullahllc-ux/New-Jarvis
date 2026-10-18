"""Live check: calls the safe tools against the real web services and tells you which ones work.

    python tests/live_check.py              # everything except Starlink (CelesTrak allows one download per 2 hours)
    python tests/live_check.py --all        # including Starlink
    python tests/live_check.py weather nasa # only tools whose name contains one of these words
    python tests/live_check.py chat         # only the chat model on this PC (needs Ollama running with a model)

Web services come and go, and this project once died of exactly that. Run this when something seems broken:
a "service said no" line names the service that failed; a "BUG" line is a mistake in Jarvis itself.

Nothing here touches your real notes or tasks (a temporary DataBase is used), opens a browser, presses a key,
sends an email, shuts anything down, or changes the clipboard.
"""
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anthropic.lib.tools import ToolError  # noqa: E402

import config  # noqa: E402
from JarvisAdvancedBot import tools  # noqa: E402
from JarvisAdvancedBot.tools import _common  # noqa: E402

CASES = [
    ("get_weather", {"city": "London"}),
    ("search_wikipedia", {"topic": "Hubble Space Telescope"}),
    ("get_crypto_price", {"coin": "bitcoin"}),
    ("convert_currency", {"amount": 10, "from_currency": "USD", "to_currency": "PKR"}),
    ("get_my_location", {}),
    ("show_on_map", {"place": "Islamabad"}),
    ("get_system_details", {"topic": "network"}),
    ("nasa_picture_of_the_day", {}),
    ("nasa_mars_photos", {"rover": "curiosity"}),
    ("nasa_mars_photos", {"rover": "perseverance"}),
    ("nasa_near_earth_objects", {}),
    ("get_iss_location", {}),
    ("spacex_company_info", {}),
    ("spacex_latest_launch", {"which": "latest"}),
    ("spacex_latest_launch", {"which": "next"}),
    ("get_disease_outbreak_stats", {"country": "Pakistan"}),
    ("get_random_fact", {}),
    ("get_random_activity", {}),
    ("get_random_advice", {}),
    ("get_dog_image", {}),
    ("get_joke", {}),
    ("hack_a_random_profile", {}),
    ("lookup_free_game", {"title": "warframe"}),
    ("lookup_minecraft_server", {"host": "play.cubecraft.net"}),
    ("instagram_profile_picture", {"username": "instagram", "download": True}),
    ("translate_text", {"text": "good morning", "target_language": "Urdu"}),
    ("ask_wolfram_alpha", {"question": "distance from Earth to Mars"}),
]
HEAVY = [("spacex_starlink_count", {})]
CHAT_QUESTIONS = ("What is the capital of Australia?", "and its population?", "Hello, how are you today?")


def check_chat(results):
    """Ask the chat model real questions: a factual one (looked up first), a follow-up, and some small talk."""
    from JarvisAdvancedBot import ChatBrain
    if not ChatBrain.available():
        print("[skipped ] chat: Ollama isn't running or has no model (see the README)")
        return
    print(f"chat model: {ChatBrain.choose_model()}")
    with tempfile.TemporaryDirectory(prefix="jarvis-chat-") as folder, \
            mock.patch.object(ChatBrain, "FACTS_FILE", Path(folder) / "memory.json"):
        ChatBrain.forget()
        for question in CHAT_QUESTIONS:
            started, first, sentences = time.time(), None, []
            try:
                for sentence in ChatBrain.reply_sentences(question):
                    first = first or time.time() - started
                    sentences.append(sentence)
            except Exception as error:                       # noqa: BLE001 - this is the point of the check
                results["bug"] += 1
                print(f"[BUG      ] chat: {type(error).__name__}: {error}")
                continue
            kind = "ok" if sentences else "service"
            results[kind] += 1
            label = "ok       " if sentences else "service said no"
            said = " ".join(sentences) or "no answer (is the model installed and Ollama running?)"
            print(f"[{label}] chat: {question!r} (first sentence after {first or time.time() - started:.1f}s)\n            {said[:200]}")
        ChatBrain.forget()


def main(arguments):
    run_all = "--all" in arguments
    words = [argument.lower() for argument in arguments if not argument.startswith("--")]
    cases = CASES + (HEAVY if run_all else [])
    chat = not words or "chat" in words
    if words:
        cases = [case for case in cases if any(word in case[0] for word in words)]
    results = {"ok": 0, "service": 0, "bug": 0}
    with tempfile.TemporaryDirectory(prefix="jarvis-live-") as folder, \
            mock.patch.object(_common, "DB", Path(folder)), \
            mock.patch("webbrowser.open", return_value=True):
        for name, arguments_for_tool in cases:
            if name == "ask_wolfram_alpha" and not config.WOLFRAM_APP_ID:
                print(f"[skipped ] {name}: no WOLFRAM_APP_ID in .env")
                continue
            started, tool = time.time(), getattr(tools, name)
            try:
                text, kind = str(tool(**arguments_for_tool)).replace("\n", " "), "ok"
            except ToolError as error:
                text, kind = str(error), "service"
            except Exception as error:                       # noqa: BLE001 - this is the point of the check
                text, kind = f"{type(error).__name__}: {error}", "bug"
            results[kind] += 1
            label = {"ok": "ok       ", "service": "service said no", "bug": "BUG      "}[kind]
            print(f"[{label}] {name} ({time.time() - started:.1f}s)\n            {text[:200]}")
    if chat:
        check_chat(results)
    print(f"\n{results['ok']} working, {results['service']} where a service said no, {results['bug']} bugs in Jarvis.")
    if results["service"]:
        print("A 'service said no' line is not always a fault: rate limits (NASA's demo key) and services that are busy pass by themselves.")
    return 1 if results["bug"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
