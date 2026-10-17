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
| `STARTUP_GREETING` | `short` (one sentence), `full` (adds weather, time table, to-do list, low battery) or `silent` |
| `GUI_ANIMATIONS` | `false` gives still pictures in the window on a slow PC |
| `ANTHROPIC_API_KEY` | Optional. With it Jarvis uses Claude; without it, the free command understanding below |
| `NASA_API_KEY` | A free personal key from api.nasa.gov removes the shared demo key's hourly limit |
| `WOLFRAM_APP_ID` | Optional, for "ask Wolfram ..." and for questions Wikipedia can't answer |
| `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | For sending email. Use an **app password**, never your real one |

## What you can say

Phrases are matched loosely; these are examples.

| Area | Examples |
|---|---|
| Time and weather | "what time is it", "weather in London", "where am I" |
| Money and maths | "bitcoin price", "100 dollars in rupees", "what is 15 percent of 200", "convert 5 miles to kilometres" |
| Knowledge | "who is Alan Turing", "tell me about the Roman Empire", "translate good morning to Urdu", "ask Wolfram integral of x squared" |
| Your day | "remind me in 10 minutes to drink water", "add buy bread to my to-do list", "what's on my to-do list", "take a note that ...", "add study from 6 to 9 in the morning to my time table", "what's on my time table", "read page 5 of the book story" |
| This PC | "battery", "how much RAM do I have", "disk space", "what is my IP address", "take a screenshot", "open Chrome", "close Chrome", "open drive D", "open downloads", "show desktop", "volume up", "mute", "next song", "play despacito" |
| Power | "shut down the computer", "restart the computer", "put the computer to sleep" (each asks "are you sure?" first), "cancel the shutdown" |
| Space | "NASA picture of the day", "Mars photos", "Perseverance photo", "tell me about Jupiter", "how far is the Moon", "asteroids this week", "where is the ISS", "next SpaceX launch", "how many Starlink satellites" |
| The wider world | "COVID cases in Pakistan", "business names for coffee shop", "tell me a joke", "random fact", "I'm bored", "give me some advice", "dog picture", "free game Warframe", "Minecraft server play.example.com", "show Lahore on the map", "how far is Lahore" |
| Accounts and files | "send an email" (asks who, subject and message, reads it back, sends only after a clear yes), "wifi password for Home" (shown on screen and clipboard, never spoken), "download this YouTube video" (copy the link first), "Instagram profile picture of natgeo", "create a folder named Projects on the desktop" |
| Tools | "open calculator", "open calendar", "open currency converter" |
| For fun | "crack a password", "hack a random person": pure fiction with made-up data; nothing real is touched |

## How it is put together

```
Startup.py, JarvisGUI.py      the two launchers (both go through gate.py)
gate.py                       password (salted hash) and the optional camera check
MainCode.py                   one session: greet, then take commands until sleep or quit
JarvisAdvancedBot/
  tools/                      every ability, written once (59 tools), used by both brains
  LocalBrain.py               the free brain: patterns -> tools. Order matters, see its header
  JarvisAiBrain.py            the Claude brain: the same tools, chosen by Claude
microphone.py, winmm_mic.py   voice input: sounddevice, with a built-in Windows fallback; no PyAudio
speech.py                     the one place Jarvis speaks, through Windows' own voice (and prints, so sound-off still works)
gui/                          the PyQt5 window, the unlock dialog, and the CustomTkinter tools
calc.py, rates.py             arithmetic and exchange rates, shared by the tools and the windows
DataBase/                     your notes, tasks, books, screenshots, face model, sounds
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
* **Face check says it couldn't confirm you:** it is only an extra after the password. It needs your own model in
  `DataBase/FaceDetectionModule/trainer/` (made with `SampleGenerator.py` and `ModelTrainer.py` there) and a webcam.

## Privacy and safety

* `.env`, your notes, tasks, downloads and face model are kept out of version control (`.gitignore`).
* Wi-Fi passwords and generated passwords go to the screen or clipboard, never through the model or the speaker.
* Shutting down, restarting, sleeping and sending email always need a clear yes first.
* Email will not attach `.env` files or the face model.
* The animated pictures are small sprite sheets in `gui/resources/`; `python gui/make_assets.py <folder>` rebuilds them
  from the original GIFs (kept in your personal archive).
