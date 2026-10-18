"""The phrase bank for Jarvis's language model: reading it, checking it, and growing it into training examples.

The phrases themselves are plain text in training/nlu/*.txt, one per line under a "## kind of request" heading, so anyone can add
lines. This module reads them, makes sure the headings are real, and turns each phrase into several noisy variants (politeness,
filler words, speech-to-text slips, typos), because people never say a command the same way twice.
"""
import random
import re
from pathlib import Path

from JarvisAdvancedBot import NLU

FOLDER = Path(__file__).with_name("nlu")
REAL_FILE = Path(__file__).with_name("nlu_real.txt")

PLACES = ["london", "lahore", "karachi", "islamabad", "peshawar", "new york", "paris", "dubai", "tokyo", "istanbul", "mecca",
          "riyadh", "delhi", "mumbai", "toronto", "sydney", "berlin", "rome", "moscow", "cairo", "kabul", "doha", "naran",
          "murree", "swat", "quetta", "multan", "faisalabad", "rawalpindi", "abbottabad", "manchester", "chicago", "singapore",
          "kuala lumpur", "madrid", "amsterdam", "beijing", "seoul", "kaghan", "gilgit"]


def tidy(phrase):
    return " ".join(phrase.lower().split())


def load(folder=FOLDER):
    """{family: [phrase, ...]} from every .txt file in the folder (family "chat" holds the sentences that are not commands).

    Raises ValueError for a heading that is not a known kind of request, for a line before any heading, and for the same phrase
    listed under two headings (the model could not learn both)."""
    bank, owner = {}, {}
    for path in sorted(Path(folder).glob("*.txt")):
        family = None
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#") and not line.startswith("##"):
                continue
            if line.startswith("##"):
                family = line.lstrip("#").strip()
                if family != NLU.CHAT and family not in NLU.FAMILIES:
                    raise ValueError(f"{path.name} line {number}: '{family}' is not a kind of request Jarvis knows "
                                     "(see FAMILIES in JarvisAdvancedBot/NLU.py)")
                bank.setdefault(family, [])
                continue
            if family is None:
                raise ValueError(f"{path.name} line {number}: a phrase before any '## heading'")
            phrase = tidy(line)
            if phrase in owner and owner[phrase] != family:
                raise ValueError(f"'{phrase}' is listed under both '{owner[phrase]}' and '{family}' ({path.name} line {number})")
            if phrase not in owner:
                owner[phrase] = family
                bank[family].append(phrase)
    return bank


def without_real(bank, real=None):
    """The bank minus any phrase that is exactly something the user really said: those sentences are kept for testing only, so
    the score on them shows how the model copes with speech it never saw."""
    held_out = {sentence for _, sentence in (real_utterances() if real is None else real)}
    return {family: [phrase for phrase in phrases if phrase not in held_out] for family, phrases in bank.items()}


def missing(bank):
    """The kinds of request that have no phrases yet."""
    return [family for family in [*NLU.FAMILIES, NLU.CHAT] if not bank.get(family)]


def split(bank, test_fraction=0.25, seed=7):
    """(train, test) banks that share no phrase: the model is judged on wordings it never saw while learning."""
    rng = random.Random(seed)
    train, test = {}, {}
    for family, phrases in bank.items():
        phrases = sorted(phrases)
        rng.shuffle(phrases)
        held = max(1, round(len(phrases) * test_fraction))
        test[family], train[family] = phrases[:held], phrases[held:]
    return train, test


def concrete(phrases, rng, per_template=4):
    """Fill the {place} blanks with real place names (several different ones per template)."""
    filled = []
    for phrase in phrases:
        if "{place}" in phrase:
            filled.extend(phrase.replace("{place}", place) for place in rng.sample(PLACES, per_template))
        else:
            filled.append(phrase)
    return filled


# ---------------------------------------------------------------- noise: how real people (and speech recognition) differ

PREFIXES = ["", "", "", "", "", "", "jarvis ", "hey jarvis ", "ok ", "okay ", "okay jarvis ", "please ", "can you ", "could you ",
            "could you please ", "would you ", "will you ", "i want you to ", "i need you to ", "kindly ", "i mean ", "sorry ",
            "um ", "uh ", "so ", "and ", "now ", "alright ", "assistant ", "hey assistant ", "ok so ", "well ", "hmm ", "yeah ",
            "listen ", "hey ", "right ", "just "]
SUFFIXES = ["", "", "", "", "", "", " please", " for me", " now", " right now", " sir", " jarvis", " thanks", " if you can",
            " quickly", " buddy", " for me please", " will you", " okay", " again", " then"]
SPELLINGS = [("calendar", "calender"), ("screenshot", "screen shot"), ("to do", "todo"), ("time table", "timetable"),
             ("wifi", "wi-fi"), ("email", "e-mail"), ("shut down", "shutdown"), ("weather", "whether"), ("write", "right"),
             ("a.m.", "a m"), ("p.m.", "p m"), ("calculator", "calc"), ("pictures", "photos"), ("volume", "volum"),
             ("space station", "spacestation"), ("starlink", "star link"), ("spacex", "space x"), ("download", "downlod")]
DROPPABLE = {"a", "an", "the", "my", "me", "to", "of", "is", "it", "up", "for", "on", "do", "i"}
FILLERS = ["um", "uh", "like", "you know", "actually", "basically"]


def _typo(word, rng):
    if len(word) < 5:
        return word
    spot = rng.randrange(1, len(word) - 1)
    kind = rng.choice(("swap", "drop", "double"))
    if kind == "swap":
        return word[:spot] + word[spot + 1] + word[spot] + word[spot + 2:]
    if kind == "drop":
        return word[:spot] + word[spot + 1:]
    return word[:spot] + word[spot] + word[spot:]


def noisy(phrase, rng):
    """One plausible different way of saying ``phrase``: politeness, filler, a spelling variant, a dropped small word, a typo."""
    text = phrase
    if rng.random() < 0.25:
        old, new = rng.choice(SPELLINGS)
        text = text.replace(old, new)
    words = text.split()
    if len(words) > 3 and rng.random() < 0.2:
        small = [i for i, w in enumerate(words) if w in DROPPABLE and 0 < i < len(words) - 1]
        if small:
            del words[rng.choice(small)]
    if len(words) > 2 and rng.random() < 0.07:
        words.insert(rng.randrange(1, len(words)), rng.choice(FILLERS))
    if rng.random() < 0.15:
        spot = rng.randrange(len(words))
        words[spot] = _typo(words[spot], rng)
    text = " ".join(words)
    text = rng.choice(PREFIXES) + text + rng.choice(SUFFIXES)
    if rng.random() < 0.15:
        text = text.replace(" ", ", ", 1) if rng.random() < 0.5 else text + "?"
    return text.strip()


def variants(phrase, rng, count):
    """``phrase`` itself plus ``count - 1`` noisy versions."""
    return [phrase] + [noisy(phrase, rng) for _ in range(count - 1)]


# ---------------------------------------------------------------- made-up sentences that are not commands

TOPICS = ["photosynthesis", "gravity", "inflation", "democracy", "the internet", "a volcano", "the immune system", "evolution",
          "a solar eclipse", "the stock market", "electricity", "a neural network", "the french revolution", "the cold war",
          "nuclear energy", "solar panels", "the ozone layer", "a hurricane", "the renaissance", "the industrial revolution",
          "supply and demand", "the water cycle", "plate tectonics", "the theory of evolution", "a vaccine", "cryptocurrency",
          "the human brain", "the digestive system", "the greenhouse effect", "an earthquake", "the roman republic",
          "the silk road", "quantum physics", "a computer virus", "renewable energy", "the periodic table", "a tsunami",
          "the speed of sound", "genetic engineering", "the ottoman empire", "the mughal empire", "the printing press"]
PEOPLE = ["isaac newton", "marie curie", "nikola tesla", "genghis khan", "cleopatra", "muhammad ali jinnah", "allama iqbal",
          "abdul sattar edhi", "william shakespeare", "leonardo da vinci", "steve jobs", "bill gates", "malala yousafzai",
          "galileo", "charles darwin", "ada lovelace", "alexander the great", "abraham lincoln", "mahatma gandhi",
          "nelson mandela", "stephen hawking", "aristotle", "mozart", "ibn sina", "al khwarizmi", "tipu sultan", "queen victoria"]
COUNTRIES = ["france", "japan", "brazil", "egypt", "canada", "germany", "turkey", "indonesia", "norway", "kenya", "argentina",
             "thailand", "italy", "mexico", "spain", "morocco", "vietnam", "sweden", "nigeria", "peru", "poland", "greece",
             "iran", "afghanistan", "bangladesh", "saudi arabia", "south africa", "new zealand", "malaysia", "chile"]
DISHES = ["biryani", "pasta", "pancakes", "chicken karahi", "fried rice", "lentil soup", "omelette", "pizza dough", "samosas",
          "banana bread", "chocolate cake", "naan", "chicken curry", "tomato soup", "burgers", "falafel", "sushi", "paratha"]
PAIRS = [("a virus", "a bacteria"), ("weather", "climate"), ("speed", "velocity"), ("a star", "a planet"), ("mass", "weight"),
         ("a crocodile", "an alligator"), ("empathy", "sympathy"), ("an array", "a linked list"), ("python", "java"),
         ("a comet", "an asteroid"), ("fission", "fusion"), ("a republic", "a monarchy"), ("tea", "coffee"), ("heat", "temperature")]
SENTENCE_PATTERNS = [
    ("what is {topic}", TOPICS), ("explain {topic}", TOPICS), ("tell me about {topic}", TOPICS), ("how does {topic} work", TOPICS),
    ("why is {topic} important", TOPICS), ("what causes {topic}", TOPICS), ("give me a summary of {topic}", TOPICS),
    ("what are the effects of {topic}", TOPICS), ("can you explain {topic} simply", TOPICS), ("teach me about {topic}", TOPICS),
    ("who is {person}", PEOPLE), ("who was {person}", PEOPLE), ("tell me about {person}", PEOPLE), ("what did {person} do", PEOPLE),
    ("when was {person} born", PEOPLE), ("what is {person} famous for", PEOPLE), ("write a short biography of {person}", PEOPLE),
    ("what is the capital of {country}", COUNTRIES), ("how many people live in {country}", COUNTRIES),
    ("what language do they speak in {country}", COUNTRIES), ("tell me about {country}", COUNTRIES),
    ("what is the history of {country}", COUNTRIES), ("what food is {country} famous for", COUNTRIES),
    ("what is the population of {country}", COUNTRIES), ("is {country} a safe place to visit", COUNTRIES),
    ("how do i make {dish}", DISHES), ("what is the recipe for {dish}", DISHES), ("what are the ingredients of {dish}", DISHES),
    ("how long does it take to cook {dish}", DISHES), ("is {dish} healthy", DISHES),
]


def made_up_chat(rng, count):
    """``count`` ordinary questions built from the lists above, as more examples of what is NOT a command."""
    sentences = []
    for _ in range(count):
        pattern, words = rng.choice(SENTENCE_PATTERNS)
        key = re.search(r"\{(\w+)\}", pattern).group(1)
        sentences.append(pattern.replace("{" + key + "}", rng.choice(words)))
    for _ in range(count // 8):
        a, b = rng.choice(PAIRS)
        sentences.append(f"what is the difference between {a} and {b}")
    return sentences


def real_utterances(path=REAL_FILE):
    """[(family, sentence)] from things the user really said (training/nlu_real.txt: 'kind<TAB>sentence'), kept out of the
    training so they show how the model does on speech it never saw."""
    if not Path(path).is_file():
        return []
    found = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "\t" in line:
            family, _, sentence = line.partition("\t")
            found.append((family.strip(), tidy(sentence)))
    return found
