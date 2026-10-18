"""Time the AI models installed in Ollama on this PC:  python training/speedtest_models.py

For each model it measures how long Jarvis would take to start talking (the end of the first sentence) and how fast the
words (tokens) come after that, then recommends the biggest model that is still quick enough. Each model is unloaded afterwards so
it doesn't keep holding your RAM.

    python training/speedtest_models.py                        every installed model
    python training/speedtest_models.py --models qwen2.5:1.5b  only the ones you name
    python training/speedtest_models.py --limit 12             accept up to 12 seconds to the first sentence
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

PROMPTS = (
    "Who wrote the play Hamlet?",
    "Explain in two sentences why the sky is blue.",
    "I'm feeling a bit tired today. Any advice?",
)
SYSTEM = "You are Jarvis, a helpful voice assistant. Answer in one to three short spoken sentences, in plain text."
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
DEFAULT_LIMIT = 8.0                         # seconds to the end of the first sentence that still feels quick


def installed_models(base):
    """Every model Ollama has on disk, as (name, size in bytes), or None if Ollama isn't running."""
    try:
        reply = requests.get(base + "/api/tags", timeout=5)
        reply.raise_for_status()
        return [(m["name"], m.get("size", 0)) for m in reply.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return None


def time_one_answer(base, model, prompt):
    """Ask one question and return (seconds to first word, seconds to end of first sentence, tokens per second)."""
    body = {"model": model, "stream": True, "keep_alive": "5m", "options": {"num_predict": 120, "temperature": 0.6},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    started = time.perf_counter()
    first_word = first_sentence = None
    text, speed = "", 0.0
    with requests.post(base + "/api/chat", json=body, stream=True, timeout=300) as reply:
        reply.raise_for_status()
        for line in reply.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                text += piece
                first_word = first_word or time.perf_counter() - started
                if first_sentence is None and SENTENCE_END.search(text):
                    first_sentence = time.perf_counter() - started
            if chunk.get("done"):
                if chunk.get("eval_duration"):
                    speed = chunk["eval_count"] / (chunk["eval_duration"] / 1e9)
                break
    total = time.perf_counter() - started
    return first_word or total, first_sentence or total, speed


def test_model(base, model, prompts=PROMPTS):
    """Load the model, ask the prompts, and return the median timings."""
    started = time.perf_counter()
    requests.post(base + "/api/chat", json={"model": model, "messages": [], "keep_alive": "5m"}, timeout=600).raise_for_status()
    load = time.perf_counter() - started
    runs = [time_one_answer(base, model, prompt) for prompt in prompts]
    requests.post(base + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)      # free the RAM again
    return {"model": model, "load": load, "first_word": statistics.median(r[0] for r in runs),
            "first_sentence": statistics.median(r[1] for r in runs), "speed": statistics.median(r[2] for r in runs)}


def recommend(results, sizes, limit=DEFAULT_LIMIT):
    """The biggest (most capable) model whose first sentence arrives within the limit; else the quickest one."""
    quick = [r for r in results if r["first_sentence"] <= limit]
    if quick:
        return max(quick, key=lambda r: sizes.get(r["model"], 0))["model"]
    return min(results, key=lambda r: r["first_sentence"])["model"] if results else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", nargs="*", help="model names to test (default: every installed model)")
    parser.add_argument("--limit", type=float, default=DEFAULT_LIMIT, help="seconds to the first sentence that count as quick")
    args = parser.parse_args(argv)

    base = config.OLLAMA_URL.rstrip("/")
    models = installed_models(base)
    if models is None:
        print("Ollama isn't running. Start it from the Start menu (Ollama), then run this again.")
        return 1
    sizes = dict(models)
    names = args.models or [name for name, _ in models]
    if not names:
        print("No models installed yet. Get one with:  ollama pull qwen2.5:1.5b")
        return 1

    results = []
    print(f"{'model':28} {'size':>8} {'load':>7} {'1st word':>9} {'1st sentence':>13} {'tokens/s':>9}")
    for name in names:
        try:
            r = test_model(base, name)
        except (requests.RequestException, ValueError) as error:
            print(f"{name:28} failed: {error}")
            continue
        results.append(r)
        print(f"{name:28} {sizes.get(name, 0) / 1e9:6.1f}GB {r['load']:6.1f}s {r['first_word']:8.1f}s {r['first_sentence']:12.1f}s {r['speed']:9.1f}")

    best = recommend(results, sizes, args.limit)
    if best:
        print(f"\nRecommended: {best}  (the biggest model that starts speaking within {args.limit:g} s)")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
