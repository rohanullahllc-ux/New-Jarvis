"""The wizard's questions. Each function asks a group of questions in plain words, with the recommended answer already chosen
(press Enter to take it), and saves the answers to .env as settings.

Express mode asks only what matters (your name, how to wake him, whether to chat); Custom mode asks about everything. A question
whose key is in the scripted answers is not asked, so the same code serves --answers files and the tests.
"""
import settings_registry as registry

VOICE_NAMES = {
    "en_GB-alan-medium": "Alan - a British man (the usual voice)",
    "en_US-ryan-medium": "Ryan - an American man",
    "en_GB-northern_english_male-medium": "A Northern English man",
    "en_US-lessac-medium": "Lessac - an American woman",
    "en_US-amy-medium": "Amy - an American woman",
    "en_GB-jenny_dioco-medium": "Jenny - a British woman",
    "en_US-joe-medium": "Joe - an American man",
}
VOICE_SIZE_MB = 63                  # one "medium" voice
OLLAMA_SIZE_MB = {"qwen2.5:1.5b": 986, "llama3.2:3b": 2020}
WHISPER_SIZE_MB = {"tiny.en": 75, "base.en": 145, "small.en": 480}
SAMPLE_SENTENCE = "Good evening. I am Jarvis, and this is how I will sound when I talk to you."


def check(key):
    """The validator for a question: the rules for the setting come from settings_registry."""
    return lambda text: registry.validate(key, text)


def friendly_voice(name):
    return VOICE_NAMES.get(name, name)


# ---------------------------------------------------------------- about you, the brain, privacy, Windows (asked early)

def about_you(ctx):
    c = ctx.console
    c.say("First, a little about you, so that his greetings, the weather and the money all fit you.")
    updates = {
        "USER_NAME": c.ask("USER_NAME", "What should Jarvis call you in greetings? (for example \"Good morning Mr Khan\")",
                           default=ctx.value("USER_NAME"), validate=check("USER_NAME")),
        "ADDRESS_AS": c.ask("ADDRESS_AS", "And what short word should he use in his replies? Today it is \"sir\" (\"Ok sir\").\n"
                            "Examples: sir, ma'am, boss, chief, captain - or anything you like.",
                            default=ctx.value("ADDRESS_AS"), validate=check("ADDRESS_AS")),
        "DEFAULT_CITY": c.ask("DEFAULT_CITY", "Which city are you in? (for the weather and \"where am I\")",
                              default=ctx.value("DEFAULT_CITY"), validate=check("DEFAULT_CITY")),
        "HOME_CURRENCY": c.ask("HOME_CURRENCY", "Which currency do you use? Give its three-letter code: PKR, USD, EUR, GBP, AED, INR...\n"
                               "(\"dollar rate\" and \"100 dollars in rupees\" convert into it.)",
                               default=ctx.value("HOME_CURRENCY"), validate=check("HOME_CURRENCY")),
    }
    if not ctx.express:
        accents = [(v, d) for v, d in registry.BY_KEY["SPEECH_LANGUAGE"].choices]
        updates["SPEECH_LANGUAGE"] = c.choose("SPEECH_LANGUAGE", "Which accent of English is yours? (Google's speech recognition uses it when Whisper "
                                              "hears nothing.)", accents, default=ctx.value("SPEECH_LANGUAGE"))
    ctx.save_settings(updates)
    return updates


def brain(ctx):
    """Whether to add the chat model, which ones, and the settings around it. Sets ctx.choices['install_ollama'] and ['ollama_models']."""
    c = ctx.console
    tier = ctx.tier
    ollama = ctx.facts.get("ollama", {})
    already = bool(ollama.get("models"))
    c.say("Jarvis does a lot by himself (time, weather, notes, opening things). To also chat about anything - \"why is the sky blue\",\n"
          "advice, explanations - he can use a free AI model that runs on this PC, with no account and no card.")
    want = c.confirm("install_ollama", "Do you want that? It needs Ollama (free) and a download of about 1 GB; the first answers take a few seconds.",
                     default=already or (tier is None or tier.name != "very light"),
                     help="Say no if the internet is slow or this PC has little memory; you can add it later from the admin panel.")
    ctx.choices["install_ollama"] = want
    ctx.choices["ollama_models"] = []
    updates = {}
    if want:
        options = [(m, f"{m}  (about {OLLAMA_SIZE_MB.get(m, 1000) / 1000:.1f} GB)" + ("  - quicker" if m == "qwen2.5:1.5b" else "  - writes a little better, slower"))
                   for m in (tier.ollama_models if tier else ("qwen2.5:1.5b",))]
        if ctx.express:
            picked = [options[0][0]]
        else:
            picked = c.choose_many("ollama_models", "Which model(s) should I download? (one is enough; the first is the quickest)", options,
                                   defaults=[options[0][0]])
        ctx.choices["ollama_models"] = picked or [options[0][0]]
        updates["CHAT_ENGINE"] = "auto"
        updates["OLLAMA_MODEL"] = "auto"
        if tier is not None:
            updates["CHAT_AUTO_MAX_MB"] = str(tier.auto_max_mb)
            updates["CHAT_PRELOAD"] = "true" if tier.preload else "false"
    if not ctx.express:
        updates["CHAT_WEB_SEARCH"] = "true" if c.confirm("CHAT_WEB_SEARCH", "Should he look facts up on the internet (Wikipedia, DuckDuckGo) before "
                                                         "answering a factual question? The words of the question are sent there.", default=True) else "false"
        key = c.secret("LLM_API_KEY", "Optional: a free online AI key (console.groq.com or aistudio.google.com) as a faster alternative or backup.\n"
                       "Press Enter to skip.", confirm_again=False)
        if key:
            updates["LLM_API_KEY"] = key
    ctx.save_settings(updates)
    return updates


def privacy(ctx):
    c = ctx.console
    if ctx.express:
        return {}
    c.say("Privacy: Jarvis can keep a private record of what you say to him and what he answers (it never leaves this PC).")
    keep = c.confirm("LOG_CONVERSATIONS", "Keep that record?", default=True)
    updates = {"LOG_CONVERSATIONS": "true" if keep else "false"}
    if keep:
        updates["CONVERSATION_LOG_DAYS"] = c.ask("CONVERSATION_LOG_DAYS", "For how many days? (0 = for ever)", default=ctx.value("CONVERSATION_LOG_DAYS"),
                                                validate=check("CONVERSATION_LOG_DAYS"))
    ctx.save_settings(updates)
    return updates


def email(ctx):
    c = ctx.console
    if ctx.express:
        return {}
    if not c.confirm("set_up_email", "Do you want to set up sending email by voice now? (You can do it later in the admin panel.)", default=False):
        return {}
    address = c.ask("EMAIL_ADDRESS", "Your email address (Gmail, Yahoo, Outlook or iCloud):", default=ctx.value("EMAIL_ADDRESS"), validate=check("EMAIL_ADDRESS"))
    password = c.secret("EMAIL_PASSWORD", "Its APP PASSWORD (not your real password - your email provider can make one for you):", confirm_again=False)
    updates = {"EMAIL_ADDRESS": address}
    if password:
        updates["EMAIL_PASSWORD"] = password
    ctx.save_settings(updates)
    return updates


def windows_choices(ctx):
    """How Jarvis fits into Windows. Sets ctx.choices['start_with_windows'], ['desktop_shortcut'], ['fix_mic_level']."""
    c = ctx.console
    c.say("How should Jarvis fit into Windows?")
    ctx.choices["desktop_shortcut"] = c.confirm("desktop_shortcut", "Put a Jarvis shortcut on the desktop?", default=True)
    ctx.choices["start_with_windows"] = c.confirm("start_with_windows", "Open the Jarvis window by itself whenever you log in to Windows?\n"
                                                  "(He then waits asleep for \"hey Jarvis\" or a clap. You can switch it off any time.)", default=False)
    fix = c.confirm("fix_mic_level", "A microphone that is muted or turned down low in Windows is the commonest reason a voice assistant misses words.\n"
                    "May Jarvis put the Windows microphone volume right (to 80 percent) when it is too low?", default=True)
    ctx.choices["fix_mic_level"] = fix
    updates = {"MIC_VOLUME": "80" if fix else "0"}
    tier = ctx.tier
    if not ctx.express or (tier is not None and tier.name in ("light", "very light")):
        animations = c.confirm("GUI_ANIMATIONS", "Show the moving pictures in the window? (They use a little processor time; off is lighter on a slow PC.)",
                               default=ctx.value("GUI_ANIMATIONS").lower() != "false")
        updates["GUI_ANIMATIONS"] = "true" if animations else "false"
    ctx.save_settings(updates)
    return updates


# ---------------------------------------------------------------- how he sounds and hears (asked once the models are there)

def speech_model(ctx):
    """Which Whisper model to use. Express: the one that suits this PC (unless a restored .env already chose). Returns the model."""
    c = ctx.console
    tier = ctx.tier
    recommended = tier.stt_model if tier is not None else "base.en"
    if ctx.mode == "restore" and ctx.env_values().get("STT_MODEL"):
        return ctx.value("STT_MODEL")                          # (the restored settings already say)
    if ctx.express:
        chosen = recommended
    else:
        options = [(m, f"{m}  (about {WHISPER_SIZE_MB[m]} MB)" + ("  <- suits this PC" if m == recommended else "")) for m in ("tiny.en", "base.en", "small.en")]
        chosen = c.choose("STT_MODEL", "Which speech-recognition model? A bigger one understands you better but is slower on a modest PC.", options, default=recommended)
    ctx.save_settings({"STT_MODEL": chosen})
    return chosen


def wanted_voices(ctx):
    """Which Piper voices to download so that there is a choice. Express: just the usual one."""
    c = ctx.console
    usual = ctx.value("PIPER_VOICE")
    if ctx.express:
        return [usual]
    options = [(name, f"{friendly_voice(name)}  (about {VOICE_SIZE_MB} MB)") for name in VOICE_NAMES]
    return c.choose_many("download_voices", "Which natural voices should I download, so that you can choose between them?", options, defaults=[usual]) or [usual]


def speaking(ctx, installed, play=None):
    """Pick the voice (hearing each one if you like), the speed and the start-up greeting. ``play(name)`` speaks a sample."""
    c = ctx.console
    updates = {}
    if not ctx.express:
        updates["TTS_ENABLED"] = "true" if c.confirm("TTS_ENABLED", "Should Jarvis speak out loud? (No means text only, which is much faster.)", default=True) else "false"
    if updates.get("TTS_ENABLED") == "false":
        ctx.save_settings(updates)
        return updates
    if installed:
        chosen = ctx.value("PIPER_VOICE")
        if len(installed) > 1 and play is not None and c.confirm("preview_voices", "Hear each voice now?", default=True, help="Turn the volume up a little."):
            for name in installed:
                c.say(f"Voice: {friendly_voice(name)}")
                play(name)
        options = [(name, friendly_voice(name)) for name in installed]
        chosen = c.choose("PIPER_VOICE", "Which voice should Jarvis use?", options, default=chosen if chosen in installed else installed[0]) if len(installed) > 1 else installed[0]
        updates["PIPER_VOICE"] = chosen
        updates["TTS_ENGINE"] = "auto"
    else:
        c.warn("No natural voice is installed, so Jarvis will use the Windows voice.")
    if not ctx.express:
        speed = c.choose("TTS_RATE", "How fast should he speak?", [("-2", "a little slower"), ("0", "normal"), ("2", "a little faster"), ("4", "faster")],
                         default=str(ctx.value("TTS_RATE")) if str(ctx.value("TTS_RATE")) in ("-2", "0", "2", "4") else "0")
        updates["TTS_RATE"] = speed
        greeting = c.choose("STARTUP_GREETING", "What should he say when he starts?",
                            [(v, d) for v, d in registry.BY_KEY["STARTUP_GREETING"].choices], default=ctx.value("STARTUP_GREETING"))
        updates["STARTUP_GREETING"] = greeting
    ctx.save_settings(updates)
    return updates


def hearing(ctx, microphones):
    """The microphone, how he is woken, which speech model, and whose voice he answers."""
    c = ctx.console
    tier = ctx.tier
    updates = {}
    mode = c.choose("INPUT_MODE", "Will you talk to Jarvis or type to him?", [("voice", "Talk to him (and type when I want to)"), ("text", "Type to him only")],
                    default=ctx.value("INPUT_MODE"))
    updates["INPUT_MODE"] = mode
    if mode == "text":
        ctx.save_settings(updates)
        return updates
    if len(microphones) > 1:
        options = [("", "Whatever Windows uses as the default (recommended)")] + [(name, name) for name in microphones]
        current = ctx.value("MIC_DEVICE")
        updates["MIC_DEVICE"] = c.choose("MIC_DEVICE", "Several microphones were found. Which one should Jarvis listen to?", options,
                                         default=current if current in dict(options) else "")
    elif not microphones:
        c.warn("Windows reports no microphone. Plug one in and enable it (Settings, System, Sound, Input); until then you can type to Jarvis.")
    wake = c.choose("wake_method", "How should you wake him while he sleeps with the window open?",
                    [("both", "Saying \"hey Jarvis\" or clapping"), ("word", "Only \"hey Jarvis\""), ("claps", "Only clapping"), ("buttons", "Neither: I will press START")],
                    default="both")
    updates["WAKE_WORD"] = "true" if wake in ("both", "word") else "false"
    updates["CLAP_WAKE"] = "true" if wake in ("both", "claps") else "false"
    if not ctx.express:
        if wake in ("both", "claps"):
            updates["CLAP_COUNT"] = c.choose("CLAP_COUNT", "How many claps wake him?", [("1", "one"), ("2", "two (usual)"), ("3", "three")], default=str(ctx.value("CLAP_COUNT")))
        updates["STT_ENGINE"] = c.choose("STT_ENGINE", "Should Google's speech recognition help when Whisper hears nothing?",
                                         [("auto", "Yes, as a second opinion (usual)"), ("whisper", "No: everything stays on this PC")], default="auto")
        updates["VOICE_LOCK"] = c.choose("VOICE_LOCK", "Should he answer only your voice? (needs the voice lesson in the next part)",
                                         [("auto", "Yes once he knows my voice (usual)"), ("owner", "Always only me"), ("off", "No: any voice")], default="auto")
    ctx.save_settings(updates)
    return updates
