# New Jarvis

A voice assistant for Windows, written in Python. You can talk to it or type to it, and it works with no paid
service at all. If you have an Anthropic API key it can also use Claude to understand free-form speech.

It started as a 2022 tutorial project and was rebuilt in 2026: one tool for every job, one brain interface for
both Claude and the free built-in commands, a proper window, and a password in front of everything.

## Start it

```
pip install -r requirements.txt          # Python 3.14 on Windows
copy .env.example .env                   # then edit .env
python gate.py --set-password            # choose your unlock password (stored as a salted hash)
```

| Launcher | What it is |
|---|---|
| `python JarvisGUI.py` | The window. Works from anywhere, including VS Code's Run button. |
| `python Startup.py` | The terminal. Say or type a wake word (`hey jarvis`, `wake up`), then the password. It needs a real terminal (in VS Code: Ctrl+`) because it asks for your password. |

Both ask for the password before anything starts, through the same module (`gate.py`). Nothing else starts a session.
Say **sleep** to lock it again, **quit** to close it.

**Check the microphone:** `python microphone.py` shows a level meter while you speak and tells you which step fails
(Windows privacy switch, device, backend, Google's speech service). Voice needs the internet: speech is recognised by
Google's free web endpoint, which is unofficial. If the microphone or that service stops working, Jarvis falls back to
typed commands and says why.

## Settings (`.env`)

Everything that varies lives in `.env` (see `.env.example` for every setting with its explanation). The ones you will
touch:

| Setting | Meaning |
|---|---|
| `USER_NAME`, `DEFAULT_CITY`, `HOME_CURRENCY` | How Jarvis addresses you, where weather defaults to, what "dollar rate" converts into |
| `INPUT_MODE` | `voice` or `text` (text never touches the microphone) |
| `MIC_BACKEND`, `MIC_DEVICE` | `auto`, `sounddevice` or `winmm`; pick a specific microphone by part of its name |
| `TTS_ENABLED`, `TTS_VOICE` | Turn the spoken voice off (replies stay on screen), or choose a Windows voice such as Zira |
| `TTS_VOLUME`, `TTS_RATE` | Voice volume (0 to 100) and speed (-10 slower to 10 faster) |
| `MIC_PAUSE` | Seconds of silence that end a sentence (1.3). Raise it if Jarvis cuts you off while you think |
| `SPEECH_LANGUAGE`, `SPEECH_LANGUAGE_FALLBACK` | The accent Google's speech recognition expects: `en-pk` (default), `en-in`, `en-us`, `en-gb`. Try another if Jarvis mishears you; the fallback is tried once when the first understood nothing |
| `MIC_BEEP` | A short beep when the microphone has just been opened: it means "speak now" |
| `STARTUP_GREETING` | `short` (one sentence), `full` (adds weather, time table, to-do list, low battery) or `silent` |
| `GUI_ANIMATIONS` | `false` gives still pictures in the window on a slow PC |
| `ANTHROPIC_API_KEY` | Optional. With it Jarvis uses Claude; without it, the free command understanding and chat below |
| `CHAT_ENGINE`, `OLLAMA_MODEL`, `CHAT_WEB_SEARCH` | Chat with the free model on this PC: which engine, which model (`auto` picks one), whether facts are looked up first |
| `LANGUAGE_MODEL` | `false` switches off the model you trained for loosely worded commands (see below) |
| `NASA_API_KEY` | A free personal key from api.nasa.gov removes the shared demo key's hourly limit |
| `WOLFRAM_APP_ID` | Optional, for "ask Wolfram ..." and for questions Wikipedia can't answer |
| `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | For sending email. Use an **app password**, never your real one |

## Chatting with Jarvis (a free AI model on this PC)

Commands (open, notes, timers...) are handled by the built-in patterns first, instantly. Anything else, such as
"why is the sky blue" or "I'm feeling tired, any advice", goes to a small AI model that runs **on your PC** through
[Ollama](https://ollama.com): free, no account, no card, and it works offline.

**Set it up once**

1. Install Ollama (free) and open it once so it keeps running in the tray.
2. Get a model. For this kind of PC (about 8 GB RAM, no graphics card) `ollama pull qwen2.5:1.5b` is the one to start
   with: it begins speaking 3 to 5 seconds after you ask. `ollama pull llama3.2:3b` writes a little better but takes
   6 to 10 seconds, which is slow for talking.
3. Start Jarvis. The start-up line says which model it will chat with.

With `OLLAMA_MODEL=auto` (the default) Jarvis picks the biggest installed model that fits in the memory that is free at
that moment, but never one bigger than `CHAT_AUTO_MAX_MB` (1600 MB), so the 3B is only used when you ask for it:
`OLLAMA_MODEL=llama3.2:3b`. `python training/speedtest_models.py` times every installed model on your PC.

**What it does**

* Speaks the answer **sentence by sentence while the model is still writing it**, and shows it in the window as one
  message. If the model is slow to start Jarvis says "One moment, sir."
* **Looks facts up first** (Wikipedia, and a web search for news-type questions), because small models invent facts they
  don't know. Only the question's words are sent to Wikipedia or DuckDuckGo. `CHAT_WEB_SEARCH=false` switches this off.
* **Remembers the conversation** (`CHAT_MEMORY_TURNS`) and **what you tell it to remember**, kept in
  `DataBase/memory.json`:

| Say | What happens |
|---|---|
| "remember that my brother is Ali" | It keeps the fact for good; the chat model knows it from then on |
| "what do you remember about me" | It reads the facts back |
| "forget that my brother is Ali", "forget my facts" | It forgets one fact, or all of them |
| "new chat", or the NEW CHAT button | A fresh conversation (the facts stay) |

("take a note that ..." still writes a note; "remember that ..." is for the chat's memory.)

If Ollama isn't running, Jarvis falls back to the free key below (if you set one), then to a web answer, then to
"did you mean ...". It never crashes because a model is missing.

**Settings:** `CHAT_ENGINE` (`auto`, `ollama` or `cloud`), `OLLAMA_MODEL`, `CHAT_AUTO_MAX_MB`, `OLLAMA_KEEP_ALIVE` (how long the model stays in
RAM after your last question), `CHAT_MEMORY_TURNS`, `CHAT_WEB_SEARCH`, `CHAT_PRELOAD` (load the model at start-up).
The first question after the model has been idle can take 10 to 25 seconds while it loads; after that a reply starts
within a few seconds.

## How Jarvis listens

* **The microphone stays open** between phrases (and is released after 45 idle seconds, or when the session ends), so the first word
  of a command is never lost to a microphone that is still starting. After a fresh start there is a beep: speak after it.
* **A sentence that stops in the middle is not the end.** If what you said ends with "can you add a", "remove the last" or
  "tell me about the", Jarvis keeps listening (up to 4 seconds, twice) and joins the rest on.
* **He does not listen to himself.** He waits until he has finished speaking (plus a third of a second for the echo), throws away
  what the microphone heard while he talked, and ignores a phrase recorded while a reminder was speaking.
* **Google's other guesses are used.** Speech recognition returns several possible sentences; Jarvis takes the first one he knows
  as a command ("remove the last note" rather than "remove the last not"), then the best guess.
* **A quiet voice is made louder** before it is sent, the loudness that counts as speech is kept within sensible limits, and the
  room is measured again now and then or after three tries that heard nothing.
* **He tells you why** when he heard something but could not make it out, or your voice is too quiet for the microphone.
* **The Windows microphone volume matters most.** At start-up Jarvis checks it and says so if it is muted or under 50 percent (the
  usual reason words go missing). Say "what is my microphone volume", "set the microphone volume to 80", "raise the mic" or
  "unmute the microphone", or run `python audio_levels.py` (`--mic 80` sets it).
* Check the whole chain with `python microphone.py` (it asks you to say a sentence and shows the levels).

## Understanding loosely worded commands (a model you train yourself)

The built-in patterns catch the usual ways of saying a command. For everything they miss ("yo got the time", "it's way too
loud in here", "snap my display"), Jarvis has a second chance: a small language model that **you train on your own PC** from
the phrases in `training/nlu/*.txt`. It learns which of 59 kinds of request a sentence is (the time, the weather, the volume,
a screenshot, opening a folder...). When it is sure, the sentence runs as the plain command it stands for; when it is not sure,
or the sentence is an ordinary question, nothing happens and the chat model answers as before. It needs no internet and no GPU.

```
python training/train_nlu.py                       teach it (about 2 minutes) and save it as models/nlu.joblib
python training/train_nlu.py --report              only measure how well it learns; saves nothing
python training/train_nlu.py --try "turn it up"    what the saved model makes of a sentence
python training/train_nlu.py --unmatched           things you said that no command understood: candidates for the phrase files
```

* **Teach it more:** open any file in `training/nlu/`, add a line under the right `## heading`, and train again. Phrases that
  are not commands go under `## chat`. The trainer refuses a phrase listed under two headings, and a heading it doesn't know.
* **How good is it:** `--report` keeps a quarter of the phrasings back and tests on those, so the score is for wordings it never
  saw (95% on them, with the working point set so that a command runs as the wrong thing less than 0.5% of the time). The report
  is saved in `training/reports/`. Your own sentences from `training/nlu_real.txt` are never trained on; they show how it does
  on real speech.
* **Safe by design:** locking the screen, sending an email and forgetting what you told Jarvis are checked with you first
  ("Did you want me to lock the screen?"); shutting down and restarting always ask "are you sure?". It prints what it
  understood, e.g. `understood 'snap my display' as 'take a screenshot', 97% sure`, so you can see every guess in the log.
* `LANGUAGE_MODEL=false` in `.env` turns it off; without `models/nlu.joblib` it does nothing at all.

## When you word things a little differently

Jarvis does not need your exact words. After the built-in patterns, he tries, in order: a reading of the request by its
parts (action + thing + which one, so "can you remove the third task I am done from the to do", "delete the last tas" and
"remove not number 2" for a note all work), a repair of typos and speech-recognition slips in command words ("networds",
"holder"), number words as digits ("fifteen percent of two hundred", "a dollar in rupees"), and the language model you
trained. Anything that deletes asks yes or no first, and if he still cannot tell what you mean he says he has changed
nothing instead of pretending.

## Looking back at your conversations

Jarvis keeps a private record of every session, one file a day in `Logs/conversations/`: what you said or typed, what he
answered, what answered it (`command`, `chat`, `fallback`, `reset`), how long the chat model took, and when each session
started and ended. Read it any time:

```
python transcript.py              today
python transcript.py --days 3     the last three days
python transcript.py --you        only what you said, handy for finding what Jarvis didn't understand
python transcript.py --delete     delete every saved conversation (asks first)
```

It stays on this PC (`Logs/` is not in version control). `LOG_CONVERSATIONS=false` in `.env` records nothing, and records
older than `CONVERSATION_LOG_DAYS` (30) days are deleted when a session starts. Passwords typed in the unlock window are never
part of it. Show it to whoever is helping you improve Jarvis: it is the quickest way to see what went wrong.

## Answering any question with a free online key (optional)

A faster alternative to the model on your PC. Make a free key with no card at console.groq.com (Groq) or
aistudio.google.com (Gemini) and paste it as `LLM_API_KEY` in `.env`; Jarvis recognises which service it belongs to.
Your questions then go to that service. Set `CHAT_ENGINE=cloud` to use only that, or leave it on `auto` to use the
model on your PC first and the key as the backup.

## What you can say

Phrases are matched loosely; these are examples. Two commands can go in one breath when you join them with "then":
"take a screenshot, then open the note, then go to sleep" (Jarvis only splits when every piece is a command he knows).

| Area | Examples |
|---|---|
| Time and weather | "what time is it", "weather in London", "where am I" |
| Money and maths | "bitcoin price", "100 dollars in rupees", "what is 15 percent of 200", "convert 5 miles to kilometres" |
| Chat and memory | "why is the sky blue", "I'm feeling tired, any advice", "remember that my brother is Ali", "what do you remember about me", "new chat" |
| Knowledge | "who is Alan Turing", "tell me about the Roman Empire", "translate good morning to Urdu", "ask Wolfram integral of x squared" |
| Your day | "remind me in 10 minutes to drink water", "add buy bread to my to-do list", "schedule dentist on Friday", "what's on my to-do list for tomorrow", "make a to-do list" (asks task by task; "call Ali at 5 pm" also sets a reminder), "remove task 2", "remove buy bread from my to-do list", "cross off dentist", "clear my to-do list", "clear all notes and tasks" (asks yes or no first), "delete the last note", "take a note that ...", "open my latest note", "add study from 6 to 9 in the morning to my time table", "what's on my time table", "read page 5 of the book story" |
| This PC | "battery", "how much RAM do I have", "disk space", "what is my IP address", "how is my PC doing", "take a screenshot", "where are my screenshots", "open the screenshot", "open Chrome", "close Chrome", "open drive D", "open downloads", "show desktop", "volume up", "mute", "next song", "play despacito" |
| Power | "shut down the computer", "restart the computer", "put the computer to sleep" (each asks "are you sure?" first), "cancel the shutdown" |
| Space | "NASA picture of the day", "Mars photos", "Perseverance photo", "tell me about Jupiter", "how far is the Moon", "asteroids this week", "where is the ISS", "next SpaceX launch", "how many Starlink satellites" |
| The wider world | "COVID cases in Pakistan", "business names for coffee shop", "tell me a joke", "random fact", "I'm bored", "give me some advice", "dog picture", "free game Warframe", "Minecraft server play.example.com", "show Lahore on the map", "how far is Lahore" |
| Accounts and files | "send an email" (asks who, subject and message, reads it back, sends only after a clear yes), "wifi password for Home" (shown on screen and clipboard, never spoken), "download this YouTube video" (copy the link first), "Instagram profile picture of natgeo", "create a folder named Projects on the desktop" |
| Tools | "open calculator", "open calendar", "open currency converter", "open the system calendar" (Windows' own) |
| For fun | "crack a password", "hack a random person": pure fiction with made-up data; nothing real is touched |

## How it is put together

```
Startup.py, JarvisGUI.py      the two launchers (both go through gate.py)
gate.py                       password (salted hash) and the optional camera check
transcript.py                 the private record of conversations (and python transcript.py to read it)
MainCode.py                   one session: greet, then take commands until sleep or quit
JarvisAdvancedBot/
  tools/                      every ability, written once (64 tools), used by both brains
  LocalBrain.py               the free brain: patterns -> tools. Order matters, see its header
  NLU.py                      the second chance: your own trained model for loosely worded commands
  ChatBrain.py                chat with a model on this PC (Ollama): streaming, memory, facts, lookups
  FreeBrain.py                the backup: a free online key, or a web answer
  JarvisAiBrain.py            the Claude brain: the same tools, chosen by Claude
microphone.py, winmm_mic.py   voice input: sounddevice, with a built-in Windows fallback; no PyAudio
speech.py                     the one place Jarvis speaks, through Windows' own voice (and prints, so sound-off still works)
gui/                          the PyQt5 window, the unlock dialog, and the CustomTkinter tools
calc.py, rates.py             arithmetic and exchange rates, shared by the tools and the windows
DataBase/                     your notes, tasks, books, screenshots, face model, sounds
training/                     the models you train: nlu/ (phrases), train_nlu.py, speedtest_models.py
models/                       what training saves (kept out of version control)
tests/                        offline tests (no microphone, speaker, network, camera or email needed)
```

Add a new ability by writing a tool in `JarvisAdvancedBot/tools/` (a function with a docstring and the `@beta_tool`
decorator), adding it to that module's `TOOLS` list, and adding one pattern in `LocalBrain.py`. Claude finds it
automatically.

## Tests

```
python -m unittest discover -s tests            # offline: no microphone, speaker, network, camera or email
python tests/live_check.py                      # asks the real services; run it when something seems broken
```

Web services change. If a tool starts failing, `tests/live_check.py` shows which one, and the fix is in one file.

## When something goes wrong

* **"It prints a prompt and exits"** when run from VS Code's Run button: `Startup.py` needs a real terminal. Use
  `python JarvisGUI.py`, or open a terminal with Ctrl+`.
* **Jarvis doesn't chat, or says "I can't reach Ollama":** open Ollama from the Start menu, and check there is a model with
  `ollama list`. If the model is missing, `ollama pull llama3.2:3b`. If answers are slow, close big programs (Chrome uses a
  lot of RAM) or use the smaller model with `OLLAMA_MODEL=qwen2.5:1.5b` (the default already prefers it).
* **No sound, or it stops talking:** run `python speech.py`. It says three sentences and tells you if any came back
  too fast to have been spoken. Also check the Windows volume and output device. `TTS_ENABLED=false` gives text only;
  `TTS_VOICE=Zira` picks a voice.
  `DataBase/Voices/*.reg` are optional registry files (run as administrator) that make Microsoft's Heera, Mark and
  Ravi voices available.
* **NASA says "too many times this hour":** put a free personal key from api.nasa.gov in `NASA_API_KEY`.
* **YouTube download fails:** `pip install -U yt-dlp` (YouTube changes often).
* **Starlink count says to ask later:** CelesTrak allows one download every two hours; the answer is then kept for 12.
* **Email login refused:** Gmail, Yahoo and iCloud need an app password in `EMAIL_PASSWORD`.
* **Forgot the password:** `python gate.py --set-password`.
* **Face check says it couldn't confirm you:** it is only an extra after the password. It needs a webcam and your own
  face model in `DataBase/FaceDetectionModule/trainer/`. To make a fresh one (new haircut, new glasses, a different room):
  `python DataBase/FaceDetectionModule/SampleGenerator.py` (look at the camera and slowly turn your head; it adds 30 photos to
  the ones you already have), then `python DataBase/FaceDetectionModule/ModelTrainer.py` (it keeps the old model as
  `trainer.previous.yml`). Test it alone with `python DataBase/FaceDetectionModule/FaceRecognition.py`.
* **Face check says "This OpenCV can't recognise faces":** OpenCV 5 removed the face detector and recogniser. Use version 4:
  `pip uninstall -y opencv-python opencv-contrib-python` and then `pip install "opencv-contrib-python<5"`.

## Privacy and safety

* `.env`, your notes, tasks, downloads, face model, `DataBase/memory.json` and the conversation record are kept out of version control (`.gitignore`).
* The chat model runs on this PC. The only things sent out are the words of a factual question (to Wikipedia, or
  DuckDuckGo for news-type questions) when `CHAT_WEB_SEARCH` is on.
* Wi-Fi passwords and generated passwords go to the screen or clipboard, never through the model or the speaker.
* Shutting down, restarting, sleeping and sending email always need a clear yes first.
* Email will not attach `.env` files or the face model.
* The animated pictures are small sprite sheets in `gui/resources/`; `python gui/make_assets.py <folder>` rebuilds them
  from the original GIFs (kept in your personal archive).
