"""Train Jarvis's own language-understanding model (it learns what kind of request a sentence is).

    python training/train_nlu.py                      learn from training/nlu/*.txt and save models/nlu.joblib
    python training/train_nlu.py --report             only measure how well it learns (nothing is saved)
    python training/train_nlu.py --try "turn it up"   what the saved model makes of a sentence
    python training/train_nlu.py --unmatched          things you said that no command understood: candidates for the phrases

How it works, in plain words: every phrase in training/nlu/*.txt is expanded into several noisy versions (please, um, typos,
speech-to-text slips). The model counts which short letter groups ("tim", "ime", "e i") go with which kind of request and learns
how strongly each one points to it. A quarter of the phrasings are kept back, so the score printed by --report is for wordings
the model has never seen. Training takes well under a minute and needs no GPU.
"""
import argparse
import collections
import datetime
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from JarvisAdvancedBot import NLU  # noqa: E402
from training import nlu_phrases as phrases  # noqa: E402

REPORT_DIR = Path(__file__).with_name("reports")
VARIANTS = 8                                # versions of every phrase the model learns from (the phrase itself + 7 noisy ones)
CHAT_EXTRA = 1500                           # made-up ordinary questions added to the hand-written ones
GATE = 0.95                                 # the accuracy on never-seen wordings that Stage 2 promised


def _normalizer():
    """What LocalBrain does to a sentence before the model sees it, so training sees the same thing."""
    from JarvisAdvancedBot import LocalBrain
    return LocalBrain.normalize


def build_examples(bank, rng, normalize, variants=VARIANTS, extra_chat=CHAT_EXTRA):
    """([sentence], [kind]) ready for training: every phrase and its noisy variants, normalised like real input."""
    texts, labels = [], []
    for family, phrase_list in bank.items():
        pool = phrases.concrete(phrase_list, rng)
        if family == NLU.CHAT:
            pool += phrases.made_up_chat(rng, extra_chat)
        for phrase in pool:
            for version in phrases.variants(phrase, rng, variants if family != NLU.CHAT else max(3, variants // 2)):
                cleaned = normalize(version)
                if cleaned:
                    texts.append(cleaned)
                    labels.append(family)
    return texts, labels


def make_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, make_pipeline as pipe
    letters = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2)
    words = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"[a-z0-9']+")
    return pipe(FeatureUnion([("letters", letters), ("words", words)]), LogisticRegression(C=20, max_iter=400))


def predictions(model, texts):
    """[(kind, probability, runner-up probability)] for each sentence."""
    out = []
    for row in model.predict_proba(texts):
        order = row.argsort()[::-1]
        out.append((str(model.classes_[order[0]]), float(row[order[0]]), float(row[order[1]])))
    return out


def judge(guesses, truth, threshold, margin):
    """How a model would behave at this threshold. 'Accepted' means Jarvis would run the command it guessed."""
    commands = [(g, t) for g, t in zip(guesses, truth) if t != NLU.CHAT]
    chats = [(g, t) for g, t in zip(guesses, truth) if t == NLU.CHAT]

    def accepted(guess):
        kind, top, second = guess
        return kind != NLU.CHAT and top >= threshold and top - second >= margin

    ran_right = sum(1 for g, t in commands if accepted(g) and g[0] == t)
    ran_wrong = sum(1 for g, t in commands if accepted(g) and g[0] != t)
    chat_hijacked = sum(1 for g, _ in chats if accepted(g))
    return {
        "threshold": threshold, "margin": margin,
        "commands_run_right": ran_right / max(1, len(commands)),             # understood and done
        "commands_run_wrong": ran_wrong / max(1, len(commands)),             # a different command than meant
        "chat_hijacked": chat_hijacked / max(1, len(chats)),                 # a question mistaken for a command
        "precision": ran_right / max(1, ran_right + ran_wrong + chat_hijacked),
    }


def choose_operating_point(guesses, truth):
    """The threshold that lets the most commands through while a wrong action stays rare (under 0.5% of chat sentences taken for
    a command, under 0.5% of commands done as the wrong thing)."""
    best = None
    for margin in (0.1, 0.2, 0.3, 0.4):
        for threshold in [round(0.5 + 0.01 * step, 2) for step in range(0, 49)]:
            score = judge(guesses, truth, threshold, margin)
            if score["chat_hijacked"] <= 0.005 and score["commands_run_wrong"] <= 0.005:
                if best is None or score["commands_run_right"] > best["commands_run_right"]:
                    best = score
    return best or judge(guesses, truth, 0.95, 0.4)


def evaluate(bank, seed=7, say=print):
    """Train on three quarters of the phrasings and test on the rest. Returns (model, numbers) for the held-out part."""
    normalize = _normalizer()
    train_bank, test_bank = phrases.split(bank, seed=seed)
    texts, labels = build_examples(train_bank, random.Random(seed), normalize)
    say(f"  learning from {len(texts)} sentences ({len(set(labels))} kinds of request)...")
    started = time.time()
    model = make_pipeline().fit(texts, labels)
    say(f"  learned in {time.time() - started:.0f} seconds")
    test_texts, test_labels = build_examples(test_bank, random.Random(seed + 1), normalize, variants=5, extra_chat=300)
    guesses = predictions(model, test_texts)
    correct = sum(1 for g, t in zip(guesses, test_labels) if g[0] == t)
    spot = choose_operating_point(guesses, test_labels)
    per_kind = collections.defaultdict(lambda: [0, 0])
    confusions = collections.Counter()
    for (kind, _, _), truth in zip(guesses, test_labels):
        per_kind[truth][1] += 1
        if kind == truth:
            per_kind[truth][0] += 1
        else:
            confusions[(truth, kind)] += 1
    real = real_world(model, spot, normalize)
    return model, {
        "held_out_sentences": len(test_texts), "accuracy": correct / len(test_texts), "operating_point": spot,
        "per_kind": {k: v[0] / v[1] for k, v in sorted(per_kind.items(), key=lambda item: item[1][0] / item[1][1])},
        "confusions": [(a, b, n) for (a, b), n in confusions.most_common(12)], "real_world": real,
    }


def real_world(model, spot, normalize):
    """How the model does on sentences the user really said (training/nlu_real.txt), which it never trained on."""
    found = phrases.real_utterances()
    if not found:
        return None
    guesses = predictions(model, [normalize(sentence) or sentence for _, sentence in found])
    rows = []
    for (truth, sentence), (kind, top, second) in zip(found, guesses):
        runs = kind != NLU.CHAT and top >= spot["threshold"] and top - second >= spot["margin"]
        if truth == NLU.CHAT:
            outcome = "wrong" if runs else "right"                    # chat must stay chat
        elif runs:
            outcome = "right" if kind == truth else "wrong"          # done as meant, or done as something else
        else:
            outcome = "missed"                                        # not sure enough: left for the chat brain, as before
        rows.append({"said": sentence, "meant": truth, "guess": kind, "confidence": round(top, 2), "runs": runs,
                     "outcome": outcome, "ok": outcome == "right"})
    return rows


def train_final(bank, seed=7, say=print):
    """The model Jarvis will use: trained on every phrasing, not just three quarters of them."""
    texts, labels = build_examples(bank, random.Random(seed), _normalizer())
    say(f"  learning from {len(texts)} sentences...")
    return make_pipeline().fit(texts, labels), len(texts)


def save(model, spot, examples, path=NLU.MODEL_FILE):
    import joblib
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": model, "threshold": spot["threshold"], "margin": spot["margin"], "examples": examples,
                 "trained": datetime.datetime.now().isoformat(timespec="seconds"), "version": 1}, path, compress=3)
    NLU.reset()
    return path


def write_report(numbers, bank, folder=REPORT_DIR):
    folder.mkdir(parents=True, exist_ok=True)
    spot = numbers["operating_point"]
    lines = [
        f"Jarvis language model report, {datetime.datetime.now():%Y-%m-%d %H:%M}",
        f"phrases: {sum(len(v) for k, v in bank.items() if k != NLU.CHAT)} for commands in {len(bank) - 1} kinds, "
        f"{len(bank.get(NLU.CHAT, []))} for chat",
        f"never-seen wordings tested: {numbers['held_out_sentences']}",
        f"accuracy on them: {numbers['accuracy']:.1%}   (the target was {GATE:.0%})",
        f"working point: be at least {spot['threshold']:.0%} sure and {spot['margin']:.0%} ahead of the runner-up",
        f"  commands understood and done: {spot['commands_run_right']:.1%}",
        f"  commands done as the wrong thing: {spot['commands_run_wrong']:.2%}",
        f"  chat mistaken for a command: {spot['chat_hijacked']:.2%}",
        "", "weakest kinds (accuracy on never-seen wordings):"]
    lines += [f"  {kind:18} {score:.0%}" for kind, score in list(numbers["per_kind"].items())[:10]]
    lines += ["", "most common mix-ups (meant -> guessed, how many):"]
    lines += [f"  {a:18} -> {b:18} {n}" for a, b, n in numbers["confusions"]]
    if numbers["real_world"]:
        count = collections.Counter(row["outcome"] for row in numbers["real_world"])
        lines += ["", f"things you really said (never trained on): {count['right']} done right, {count['missed']} left for the chat "
                      f"brain (not sure enough), {count['wrong']} done wrong"]
        lines += [f"  {r['outcome']:6} {r['said']!r}: meant {r['meant']}, guessed {r['guess']} ({r['confidence']})"
                  for r in numbers["real_world"]]
    text = "\n".join(lines)
    (folder / "nlu_report.txt").write_text(text + "\n", encoding="utf-8")
    (folder / "nlu_report.json").write_text(json.dumps(numbers, indent=1), encoding="utf-8")
    return text


def unmatched(bank, days=7):
    """What you said recently that Jarvis answered with the chat model or a fallback (so no command understood it)."""
    import transcript
    known = {phrase for items in bank.values() for phrase in items}
    asked, seen = [], set()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for path in sorted(transcript.LOG_DIR.glob("*.jsonl")):
        if path.stem < cutoff.isoformat():
            continue
        last_you = None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("who") == "you":
                last_you = event["text"]
            elif event.get("who") == "jarvis" and last_you and not event.get("more"):
                if event.get("by") in ("chat", "fallback") and phrases.tidy(last_you) not in known and last_you not in seen:
                    seen.add(last_you)
                    asked.append(last_you)
                last_you = None
    return asked


def main(argv=None):
    parser = argparse.ArgumentParser(description="Train Jarvis's own language-understanding model.")
    parser.add_argument("--report", action="store_true", help="measure only; do not save a model")
    parser.add_argument("--try", dest="sentence", metavar="SENTENCE", help="show what the saved model makes of a sentence")
    parser.add_argument("--unmatched", action="store_true", help="list recent things you said that no command understood")
    parser.add_argument("--days", type=int, default=7, help="how many days back --unmatched looks (default 7)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    if args.sentence:
        if not NLU.available():
            print("There is no trained model yet. Run:  python training/train_nlu.py")
            return 1
        normalize = _normalizer()
        text = normalize(args.sentence) or args.sentence
        print(f"  heard as: {text!r}")
        for kind, chance in NLU.rank(text, 4):
            command = NLU.FAMILIES[kind].command if kind in NLU.FAMILIES else "(chat: the AI model answers)"
            print(f"  {chance:6.1%}  {kind:18} {command}")
        guess = NLU.interpret(text)
        print("  Jarvis would run:", guess.command if guess else "nothing (not sure enough, or it is chat)")
        return 0

    bank = phrases.without_real(phrases.load())
    gaps = phrases.missing(bank)
    if gaps:
        print("These kinds of request have no phrases yet:", ", ".join(gaps))
        return 1
    if args.unmatched:
        found = unmatched(bank, args.days)
        print(f"{len(found)} things you said in the last {args.days} days that no command understood:" if found
              else "Nothing new: every recent sentence was understood, or is already in the phrase files.")
        for sentence in found:
            print("  ", sentence)
        if found:
            print("\nAdd the ones that were commands to the right '## heading' in training/nlu/*.txt, then train again.")
        return 0

    print("Measuring on wordings the model has not seen...")
    _, numbers = evaluate(bank, args.seed)
    print(write_report(numbers, bank))
    if args.report:
        return 0 if numbers["accuracy"] >= GATE else 2
    print("\nTraining the model Jarvis will use...")
    model, examples = train_final(bank, args.seed)
    path = save(model, numbers["operating_point"], examples)
    print(f"Saved {path}. Jarvis uses it the next time it starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
