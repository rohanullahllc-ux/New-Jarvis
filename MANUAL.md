# Jarvis user manual

How to set Jarvis up, talk to him, change him, and fix him when something is wrong. It is written for the person who uses him, not for
programmers (the files for programmers are `CLAUDE.md` and `docs/PROJECT_GUIDE.md`).

**The five things to remember**

1. **First time on a PC (or after reinstalling Windows):** double-click **`Setup-Jarvis.bat`**. It does everything and asks what you like.
2. **Every day:** double-click **`Start-Jarvis.bat`** (or the Jarvis shortcut on the desktop), then say **"hey Jarvis"**, clap twice, or press START.
3. **To change anything:** click **ADMIN** in the Jarvis window (or say **"open the admin panel"**). It asks for your password.
4. **If something is wrong:** run `Setup-Jarvis.bat` again. It looks at everything and fixes only what is missing. Section 11 lists the usual troubles.
5. **Keep a backup:** admin panel, Backup and restore, **Back up now**, onto another drive. Section 10.

---

## 1. What Jarvis is

Jarvis is a voice assistant for Windows that you can talk to or type to. He runs on your own PC: his voice, his hearing, the "hey Jarvis"
wake word, the clap detector, the knowledge of your voice, and the chat model all work with **no internet and no account**. A password
stands in front of everything. He can tell you the time and weather, keep notes and to-do lists, set reminders, open programs, files and
websites, look after your PC, answer questions, send email, and chat about almost anything.

What you need: Windows 10 or 11, a microphone for talking (not needed for typing), and about 6 GB of free disk space.

---

## 2. First day: setting Jarvis up

### 2.1 On a new or freshly installed PC

1. Put the Jarvis folder on the PC (copy it from your backup drive, or `git clone` it). **Scan it with your antivirus first** if it came from
   a drive that has been plugged into other computers.
2. Double-click **`Setup-Jarvis.bat`**. A black window opens and talks to you in plain words.
3. If the PC has no Python, it offers to install it (free, from python.org or with Windows' own `winget`). Say yes.
4. It first asks what you want: **set up a brand-new Jarvis**, **bring back my earlier Jarvis from a backup**, **check this Jarvis and fix what is missing**, or
   **start completely fresh** (section 2.3). Then **Express** (it asks only what matters) or **Custom** (it asks about every setting); then it does these steps, skipping any that
   are already done:

| Step | What it does | Needs the internet? |
|---|---|---|
| Looking at this PC | Windows, Python, memory, disk space, microphones, what is installed. Suggests models that suit your PC. | no |
| Bringing your data back | Only if you chose "restore from a backup" (section 2.2). | no |
| About you | Your name, what to call you ("sir", "boss"...), your city and currency, whether you want the chat brain, shortcuts. | no |
| The Visual C++ runtime | Microsoft's free runtime that the voice libraries need; a "lite" Windows often lacks it. Checked for Microsoft's signature before it is run. | yes, 25 MB |
| The Python packages | About 30 free libraries, from pypi.org. The longest step: 5 to 20 minutes. | yes, 1 to 2 GB |
| Voices and speech models | The natural voice, offline hearing (Whisper), "hey Jarvis", the voice-recognition model. | yes, about 300 MB |
| The chat model (Ollama) | Ollama (free) and one small AI model, so he can chat about anything. Optional. | yes, about 1 GB |
| How Jarvis sounds and hears you | You hear each voice and choose one; how to wake him; which microphone. | no |
| The password | Your unlock password, typed twice. Only a scrambled form is stored. | no |
| Your voice and your face | Optional lessons: he learns your voice (3 minutes) so he answers only you; your face (a minute) for the camera check. | no |
| His language model | Trains his own small model for loosely worded commands (about 2 minutes). | no |
| Shortcuts and start-up | A desktop shortcut; opening him when you log in (only if you said yes). | no |
| Trying it all | Loads every part, checks the microphone, lets him speak. Optionally runs his 1,500 self-tests. | no |

5. At the end it prints a summary. Green `[ OK ]` is done; `[WARN]` means he works but something needs a look; `[FAIL]` says exactly what to do.
   **If you close the window or lose the internet, nothing is half-finished: run `Setup-Jarvis.bat` again and it carries on.**

Everything it prints is also written to `Logs/setup.log` (never any password).

### 2.2 Bringing back your old Jarvis from a backup

Run `Setup-Jarvis.bat` and choose **"Bring back my earlier Jarvis from a backup"**. It looks on all your drives for a backup (a
`Jarvis-Backup-...` folder made by the admin panel, or a copy of the whole Jarvis folder such as the one on your backup drive), shows what is
in it, and asks which parts to bring back: settings and password, notes and tasks, voice print, face model, shortcuts and contacts,
conversation records, and (to save downloads) the models. Saved chat models next to the backup are put back too, so Ollama needs no download.

Nothing of yours is overwritten without a copy: a file that would be replaced is first saved under `Backups/replaced-before-restore-...`.
If the backup's `.env` mentions a microphone that this PC does not have, Jarvis drops that choice and uses the Windows default.

### 2.3 Other ways to run the setup

| You type (in the Jarvis folder) | What it does |
|---|---|
| `Setup-Jarvis.bat` | The wizard. Safe to run any time. |
| `Setup-Jarvis.bat --check` | Only looks and reports (a health check). Changes nothing. |
| `Setup-Jarvis.bat --dry-run` | Shows what it would do. Changes nothing. |
| `Setup-Jarvis.bat --yes` | Takes every recommended answer without asking. |
| `Setup-Jarvis.bat --custom` | Asks about every setting. |
| `Setup-Jarvis.bat --mode reset` | **Start completely fresh.** Saves a checked copy of your settings, password, notes, to-do lists, voice print, face model, shortcuts and conversation records into the `Backups` folder, clears them, and sets Jarvis up as if he were brand new (your books, screenshots and the downloaded models stay). It asks before clearing, and `--yes` alone never clears anything. The same thing is the **Start over (brand new)...** button on the admin panel's Overview page. |
| `Setup-Jarvis.bat --only models,voice` | Just those steps (`--list-steps` shows their names). |
| `Setup-Jarvis.bat --answers answers.json` | Takes answers from a file (an unattended setup). |

---

## 3. Starting, waking and stopping

**Starting.** Double-click `Start-Jarvis.bat` or the desktop shortcut. (If Jarvis cannot load, the window explains why and points to the setup.)
You can also run `python JarvisGUI.py` (the window) or `python Startup.py` (the terminal version; needs a real terminal because it asks for the password).

**The password.** Jarvis asks for it before anything starts. Three wrong tries and the dialog closes. Forgotten it? Open a terminal in the
Jarvis folder and run `python gate.py --set-password`.

**Waking him.** While the window is open and he is asleep he listens (using about 6 percent of one processor core) for:

* **"hey Jarvis"**, recognised on your PC, and/or
* **a clap pattern** (two claps by default), and
* the **START** button.

Any of them opens the password dialog. Nothing you say while he is asleep is recorded or sent anywhere. Change this in the admin panel,
Waking and security (turn the wake word or claps off, change the number of claps, make them more or less sensitive).

**Only your voice.** After the voice lesson (`Setup-Jarvis.bat`, or the admin panel's "Teach him my voice...") he answers only you: any other
voice is heard and ignored, with a note in the log. It is a convenience, not a lock: a recording of your voice can fool it, and a cold or a
noisy room can make it refuse you. The typed box and the buttons always work. Say **"turn off the voice lock"** (or **"turn on the voice lock"**)
to switch it for this session; make it permanent with the admin panel's "Only answer my voice".

**Sleeping and leaving.** Say **"sleep"** (he locks again and waits to be woken) or **"quit"**. The SLEEP and QUIT buttons do the same.

---

## 4. The window

| Where | What it is |
|---|---|
| Top right: **ADMIN** | Opens the admin panel (asks for the password). Works while he sleeps. |
| Top right: the coloured word | LOCKED, STARTING, READY, LISTENING or WORKING. |
| Left: the ring, the clock, **System** | What brain he uses, whether he is listening hands-free, whether he speaks, your name. |
| Left: **START**, **SLEEP**, **QUIT** | Wake him (asks the password), put him to sleep, close him. |
| Middle: the conversation | What you said and what he answered. Everything he says appears here too, so the window works with the sound off. |
| Middle, bottom: the box | Type a command and press Enter. **SEND** does the same. **NEW CHAT** starts a fresh conversation. |
| The microphone button | Push to talk: click, speak one command. |
| **HANDS-FREE** | He keeps listening for commands without clicking. |
| Bottom right: **LOG** | Shows or hides the technical log (useful when something is wrong). |
| Right: **Quick links**, **Tools** | One-click websites, the calculator, the calendar, the currency converter, and the theme music. |

---

## 5. Talking to him

### 5.1 How to phrase things

You do not need his exact words. He ignores words around a command (**"ok now could you please open the notes folder, sir"** is
**"open the notes folder"**), copes with the "-ing" form speech recognition writes ("opening task folder"), repairs small slips of the ear, and
understands two commands in one breath: **"take a screenshot, then open the note, then go to sleep"** (he only splits when every piece is a
command he knows). A thank-you in front of a request is just a lead-in; on its own it gets "you're welcome".

If a sentence is not a command, he answers it as a question with the chat model (section 5.4). If he cannot tell what you meant he says
so and **changes nothing**.

### 5.2 What you can say

These are examples; the wording is flexible. Everything in the boxes below is tested: `tests/test_docs.py` makes sure he still understands each one.

<!-- say:start -->

**Time, weather, place**
"what time is it" · "what's the date" · "what day is it" · "is it AM or PM" · "what's the weather" · "weather in London" · "what's the weather in Peshawar tomorrow" · "where am I"

**Money and maths**
"bitcoin price" · "dollar rate" · "100 dollars in rupees" · "what is 15 percent of 200" · "convert 5 miles to kilometres" · "how many feet in a mile" · "cube root of 27"

**Knowledge**
"who is Alan Turing" · "tell me about the Roman Empire" · "define serendipity" · "translate good morning to Urdu"

**Notes, to-do list, reminders, time table**
"take a note that call Ali" · "show my notes" · "read my last note" · "open my latest note" · "delete the last note" · "add buy bread to my to-do list" · "what's on my to-do list" · "what's on my to-do list for tomorrow" · "schedule dentist on Friday" · "remove task 2" · "make a to-do list" (he asks task by task) · "clear my to-do list" · "clear all notes and tasks" · "remind me in 10 minutes to drink water" · "set a timer for 5 minutes" · "add study from 6 to 9 in the morning to my time table" · "what's on my time table"

**This PC**
"battery" · "how much RAM do I have" · "disk space" · "what is my IP address" · "how is my PC doing" · "take a screenshot" · "where are my screenshots" · "open the screenshot" · "open Chrome" · "close Chrome" · "open drive D" · "open downloads" · "open the task folder" · "open the notes folder" · "show desktop" · "lock the screen" · "volume up" · "volume down" · "mute" · "next song" · "play despacito"

**Microphone and voice**
"what is my microphone volume" · "set the microphone volume to 80" · "unmute the microphone" · "turn off the voice lock" · "turn on the voice lock" · "is the voice lock on"

**Power** (each one first asks you to confirm)
"shut down the computer" · "restart the computer" · "put the computer to sleep" · "cancel the shutdown"

**Tools and websites**
"open calculator" · "open calendar" · "open currency converter" · "open the system calendar" · "open youtube" · "open gmail" · "search google for python tutorials" · "play some music on youtube"

**Space**
"NASA picture of the day" · "where is the ISS" · "tell me about Jupiter" · "how far is the Moon" · "asteroids this week" · "next SpaceX launch" · "Mars photos"

**The wider world**
"COVID cases in Pakistan" · "business names for coffee shop" · "tell me a joke" · "random fact" · "I'm bored" · "give me some advice" · "dog picture" · "free game Warframe" · "show Lahore on the map" · "how far is Lahore" · "generate a password"

**Accounts and files**
"send an email" (he asks who, the subject and the message, reads it back, and sends only after a clear yes) · "wifi password for Home" (shown on screen and clipboard, never spoken) · "create a folder named Projects on the desktop" · "Instagram profile picture of natgeo" · "download this YouTube video" (copy the link first)

**Chat and memory**
"remember that my brother is Ali" · "what do you remember about me" · "forget my facts"

**Himself**
"hello" · "how are you" · "who are you" · "what is my name" · "thank you" · "what can you do" · "open the admin panel" · "open Jarvis settings" · "what are my shortcuts"

<!-- say:end -->

**Session words** (handled by the session itself): "new chat" (a fresh conversation; what you asked him to remember stays) · "sleep" · "go to sleep" · "quit" · "goodbye".

### 5.3 Things that always ask first

Shutting down, restarting and sleeping the PC, sending email, clearing notes or tasks, and forgetting what you told him all need a clear **yes**.
He will not delete files, folders or programs by voice (too risky); he says so and touches nothing. Wi-Fi passwords and generated
passwords go to the screen or the clipboard, never through the speaker or the chat model.

### 5.4 Chatting about anything

Anything that is not a command ("why is the sky blue", "I'm feeling tired, any advice") goes to a small AI model that runs **on your PC**
through Ollama: free, no account, works offline. He speaks the answer sentence by sentence while it is still being written. Facts are
looked up first on Wikipedia (and DuckDuckGo for news) because small models invent facts; switch that off in the admin panel,
Privacy and records, **Look facts up on the internet first**. The first question after a pause can take 10 to 25 seconds while the model
loads; after that a reply starts within a few seconds.

* **"remember that my brother is Ali"** keeps a fact for good; **"what do you remember about me"** reads them back; **"forget my facts"** clears them.
* **"new chat"** (or the NEW CHAT button) starts a fresh conversation.
* If Ollama is not running he falls back to a free online key (if you set one), then to a web answer, then to "did you mean...". He never crashes because a model is missing.

---

## 6. Your own shortcuts and contacts

**Shortcuts** let you open your own things by name. In the admin panel, **Your shortcuts**, press **Add a shortcut...**: say what you will say
("college portal"), choose what it opens (a website, a folder, a file or a program) and where it goes. Then **"open college portal"** (or
"open my college portal", "launch the college portal website") opens it. A shortcut beats a built-in meaning of the same words.
**"What are my shortcuts"** lists them. A shortcut whose folder or file has been moved is marked in the list.

**Contacts** let you answer **"send an email"** with a name. In **Your contacts**, add a name and an email address (and a phone number or note
if you like). When he asks "Who should I send it to?", say **"Ali"**. An address you type or say ("john at gmail dot com") still works.

Both lists are saved the moment you change them, are yours (not in git), and are included in backups.

---

## 7. The admin panel

Open it with the **ADMIN** button, by saying **"open the admin panel"**, or on its own with **`Admin-Panel.bat`** (it works even when the
main window will not start, so a wrong setting can always be put right). It asks for your Jarvis password. If no password is set yet, it opens
at once and the **Waking and security** page tells you to set one.

**Using it.** The list on the left has the pages. Type in **Search settings** to find a setting by any word in its name or explanation.
Tick **Show advanced settings** for the settings meant for experts. A setting you changed turns yellow; one with a wrong value shows a red note
and blocks the save until you correct it. **usual** puts back a setting's usual value. At the bottom:

| Button | What it does |
|---|---|
| **SAVE** | Shows the changes (passwords and keys hidden) and, if you agree, writes them to `.env`. A copy of the old `.env` is kept. |
| **Save and restart Jarvis** | The same, then closes Jarvis and opens him again so every change is read afresh (only when opened from the Jarvis window). |
| **Revert** | Puts every box back to what is saved. |
| **Close** | Asks first if there are unsaved changes. |

Most settings take effect the next time Jarvis starts; the password and the shortcut/contact lists work at once.

| Page | What is on it |
|---|---|
| **Overview** | Where Jarvis lives, how many settings differ from the usual, any wrong values found in `.env`, and the same health check the setup makes. Buttons: Check again, Run the setup wizard, **Start over (brand new)...**, Open the manual, Open the log folder. |
| **About you** | Your name, what he calls you, your city, your currency. |
| **How Jarvis speaks** | Speak out loud, which voice, the natural voice (with **Hear the chosen voice** and **Add more voices...**), speaking volume and speed, the start-up greeting. |
| **How Jarvis hears you** | Talk or type, speech recognition, the Whisper model, your accent, the microphone (with **Test the microphone**), the pause that ends a sentence, the beep, the Windows microphone volume. |
| **Waking and security** | The wake word and its sensitivity, claps, only-my-voice, the camera check; **Change password...**, **Teach him my voice...**, **Test my voice...**, **Teach him my face...** and a line saying what he already knows. |
| **Thinking and chatting** | Where answers come from, the chat model (with what Ollama has installed and **Download a model...**), memory length, the free online key, the Claude key. |
| **Accounts and online services** | Your email address and app password, the mail server, Wolfram Alpha and NASA keys. |
| **Privacy and records** | Whether facts are looked up on the internet; whether conversations are recorded and for how many days. |
| **The window** | Moving pictures on or off; **Open Jarvis when I log in to Windows**; a desktop shortcut. |
| **Your shortcuts**, **Your contacts** | Section 6. |
| **Backup and restore** | Tick what to back up, choose the folder (your backup drive), **Back up now** (every file is checked afterwards); **Look for backups on my drives** and **Restore the selected one...**. |
| **Advanced** | Every line of `.env` (secrets hidden), including settings of your own; add or remove one; **Undo the last save**; open `.env` in Notepad. |

---

## 8. Every setting

This table is written from the master list of settings (`settings_registry.py`), so it is always complete. The names in capitals are the
names in the `.env` file; the admin panel shows the plain labels.

<!-- settings:start (written by python settings_registry.py --write-manual) -->

#### About you

Who you are and where you are, so that greetings, weather and money fit you.

| Setting | What it does | Usual value |
|---|---|---|
| **Your name**<br>`USER_NAME` | How Jarvis greets you, for example "Good morning Mr Khan". | `Mr Khan` |
| **What Jarvis calls you**<br>`ADDRESS_AS` | The short word Jarvis puts in his replies, such as "Ok sir". Whatever you choose replaces "sir" everywhere. | `sir` |
| **Your city**<br>`DEFAULT_CITY` | Used for the weather and for "where am I" when you do not name a city. | `Peshawar` |
| **Your currency**<br>`HOME_CURRENCY` | "Dollar rate" and "100 dollars in rupees" convert into this currency. Use its three-letter code. | `PKR` |

#### How Jarvis speaks

His voice, its volume and speed, and what he says when he starts.

| Setting | What it does | Usual value |
|---|---|---|
| **Speak out loud**<br>`TTS_ENABLED` | Off means Jarvis answers in text only, which is much faster. The replies still appear in the window. | `true` |
| **Which voice**<br>`TTS_ENGINE` | Automatic uses the natural voice (Piper, made on this PC) when one is installed and the Windows voice otherwise. Choices: `auto`, `piper`, `windows`. | `auto` |
| **The natural voice**<br>`PIPER_VOICE` | Which natural voice speaks. python tts_piper.py --demo plays every installed voice, and the setup wizard can add more. | `en_GB-alan-medium` |
| **The Windows voice**<br>`TTS_VOICE` | Only used when the natural voice is not. Part of a Windows voice name, for example Zira or David. Blank = the Windows default. | (empty) |
| **Speaking volume**<br>`TTS_VOLUME` | How loud Jarvis speaks, 0 to 100. From 0 to 100 percent. | `100` |
| **Speaking speed**<br>`TTS_RATE` | -10 is slower, 10 is faster, 0 is normal. Run python speech.py to hear the result. From -10 to 10. | `0` |
| **What he says when he starts**<br>`STARTUP_GREETING` | One short greeting, or the full report (weather, today's time table, your to-do list and a low-battery warning), or nothing. Choices: `short`, `full`, `silent`. | `short` |

#### How Jarvis hears you

The microphone, the speech recognition, and how long a pause ends your sentence.

| Setting | What it does | Usual value |
|---|---|---|
| **Talk or type**<br>`INPUT_MODE` | Voice means you talk to Jarvis. Text means you type your commands instead and the microphone is never touched. Choices: `voice`, `text`. | `voice` |
| **Speech recognition**<br>`STT_ENGINE` | Automatic uses Whisper on this PC and asks Google only when Whisper heard nothing. Whisper never uses the internet. Google is the old way and needs the internet. Choices: `auto`, `whisper`, `google`. | `auto` |
| **Whisper model**<br>`STT_MODEL` | tiny.en is the quickest, base.en is the balance, small.en is the most accurate and the slowest. A bigger one needs a stronger PC. Choices: `tiny.en`, `base.en`, `small.en`. | `base.en` |
| **Your accent (for Google)**<br>`SPEECH_LANGUAGE` | The accent Google's speech recognition expects: en-pk is Pakistani English. If a different one hears you better, use that. | `en-pk` |
| **Second accent to try**<br>`SPEECH_LANGUAGE_FALLBACK` | Tried once when the first accent understood nothing. | `en-us` |
| **Microphone**<br>`MIC_DEVICE` | Blank = the Windows default microphone. Otherwise part of its name (for example Realtek or Headset) or its number: python microphone.py --list shows them. | (empty) |
| **Microphone method**<br>`MIC_BACKEND` | Automatic tries sounddevice first and falls back to Windows' own winmm. Force one only if the other misbehaves. Choices: `auto`, `sounddevice`, `winmm`. | `auto` |
| **Pause that ends a sentence**<br>`MIC_PAUSE` | Seconds of silence that end what you are saying. Raise it if Jarvis cuts you off while you think; lower it for quicker answers. From 0.5 to 5 seconds. | `1.3` |
| **Beep when he starts listening**<br>`MIC_BEEP` | A short beep when the microphone has just been opened. It means "speak now". | `true` |
| **Windows microphone volume**<br>`MIC_VOLUME` | A microphone that is muted, or turned down under 50 percent in Windows, is the commonest reason Jarvis misses words. When he finds it like that at start-up he sets it to this many percent (he never turns a louder one down). 0 = never touch Windows' setting. From 0 to 100 percent. | `80` |

#### Waking and security

How he is woken, whose voice he answers, and the password in front of everything.

| Setting | What it does | Usual value |
|---|---|---|
| **Wake with "hey Jarvis"**<br>`WAKE_WORD` | While the window is open and he is asleep, saying "hey Jarvis" wakes him (he then asks for the password as usual). It is recognised on this PC; no sound is sent anywhere. | `true` |
| **Wake word sensitivity**<br>`WAKE_SENSITIVITY` | Higher hears "hey Jarvis" more easily but wakes by mistake more often. Lower it if he wakes when nobody called him. From 0.05 to 0.95. | `0.5` |
| **Wake by clapping**<br>`CLAP_WAKE` | Clapping wakes him (he then asks for the password as usual). | `true` |
| **Number of claps**<br>`CLAP_COUNT` | How many claps in a row wake him. From 1 to 4. | `2` |
| **Clap sensitivity**<br>`CLAP_SENSITIVITY` | Higher counts softer claps. Raise it if your claps are missed, lower it if typing or talking wakes him. From 0.25 to 4. | `1.0` |
| **Only answer my voice**<br>`VOICE_LOCK` | Automatic switches it on once you have taught him your voice (python enroll_voice.py). Always means he answers only you. Off means he answers any voice. The typed box and the buttons always work. Choices: `auto`, `owner`, `off`. | `auto` |
| **How alike a voice must be**<br>`VOICE_MATCH` | How alike a voice must be to yours to be accepted (0.2 to 0.9). 0 = the level chosen when you taught him your voice. From 0.2 to 0.9. | `0` |
| **Look at the camera after the password**<br>`FACE_CHECK` | After the password Jarvis glances at the webcam for extra confirmation. It never blocks you: the password is what lets you in. | `true` |

#### Thinking and chatting

The AI model that answers questions the built-in commands do not cover.

| Setting | What it does | Usual value |
|---|---|---|
| **Where answers come from**<br>`CHAT_ENGINE` | Automatic uses Ollama (the AI model on this PC) when it is running, with a free online key as the backup. Ollama means only the model on this PC. Cloud means only the online key. Choices: `auto`, `ollama`, `cloud`. | `auto` |
| **Chat model**<br>`OLLAMA_MODEL` | Automatic picks the biggest installed model that fits in the free memory, up to the size limit below. Or name one, for example qwen2.5:1.5b (quicker) or llama3.2:3b (writes a little better). | `auto` |
| **Biggest model Automatic may pick**<br>`CHAT_AUTO_MAX_MB` | "Automatic" never picks a model bigger than this many MB: a 3B model starts speaking 6 to 10 seconds after you ask on a CPU, a 1.5B one 3 to 5 seconds. From 300 to 64000 MB. | `1600` |
| **How long the model stays loaded**<br>`OLLAMA_KEEP_ALIVE` | How long the model stays in memory after your last question: 10m is ten minutes, 0 unloads it at once. | `10m` |
| **How much of the conversation he keeps in mind**<br>`CHAT_MEMORY_TURNS` | The most question-and-answer pairs kept in mind in one conversation. When the limit is reached the oldest half is forgotten at once, which keeps answers quick. From 2 to 50. | `8` |
| **Load the chat model at start-up**<br>`CHAT_PRELOAD` | Answers sooner, but uses 1 to 2 GB of memory from the start. Leave it off on a PC with 8 GB or less. | `false` |
| **Use his own trained language model**<br>`LANGUAGE_MODEL` | Jarvis's own model (made by python training/train_nlu.py) helps him understand loosely worded commands. It is only used when models/nlu.joblib exists, and never to shut down without asking. | `true` |
| **Where Ollama listens**<br>`OLLAMA_URL` | Leave it out unless Ollama runs on another computer. ("localhost" is rewritten to 127.0.0.1 because on many Windows PCs "localhost" waits two seconds for IPv6 to fail first, on every request.) | `http://127.0.0.1:11434` |
| **Free online AI key**<br>`LLM_API_KEY` | Optional. A free key (no card) from console.groq.com or aistudio.google.com. Jarvis works out which service it belongs to. It is the faster alternative to the model on this PC, or its backup. | (empty) |
| **Online AI service**<br>`LLM_PROVIDER` | Normally leave this on automatic. Choices: `auto`, `groq`, `gemini`, `openrouter`, `ollama`, `custom`. | `auto` |
| **Online AI model**<br>`LLM_MODEL` | Blank = a good free model for that service. | (empty) |
| **Online AI address**<br>`LLM_BASE_URL` | Only for the "custom" service: any OpenAI-compatible address. | (empty) |
| **Claude key**<br>`ANTHROPIC_API_KEY` | Optional. With a key Jarvis understands natural speech and uses Claude; without one he uses his built-in free command understanding. https://console.anthropic.com | (empty) |
| **Claude model**<br>`CLAUDE_MODEL` | claude-opus-5-5 is the most capable; claude-sonnet-5-5 and claude-haiku-5-5 are cheaper. | `claude-opus-5-5` |
| **How hard Claude thinks**<br>`CLAUDE_EFFORT` | Low gives the quickest replies; medium or high think more before answering. Choices: `low`, `medium`, `high`. | `low` |

#### Accounts and online services

Email and the optional online services. Every one of them is optional.

| Setting | What it does | Usual value |
|---|---|---|
| **Your email address**<br>`EMAIL_ADDRESS` | For sending email by voice. Gmail, Yahoo, Outlook and iCloud work. | (empty) |
| **Email app password**<br>`EMAIL_PASSWORD` | Use an app password (Gmail, Yahoo and iCloud all offer them), never your real password. | (empty) |
| **Mail server**<br>`EMAIL_SMTP_HOST` | Leave blank and Jarvis works it out from the address (Gmail, Yahoo, Outlook, iCloud). | (empty) |
| **Mail server port**<br>`EMAIL_SMTP_PORT` | Almost always 587. From 1 to 65535. | `587` |
| **Wolfram Alpha key**<br>`WOLFRAM_APP_ID` | Optional, for "ask Wolfram ..." questions. https://developer.wolframalpha.com | (empty) |
| **NASA key**<br>`NASA_API_KEY` | A free personal key from api.nasa.gov removes the shared DEMO_KEY's hourly limit. | `DEMO_KEY` |

#### Privacy and records

What is written down, for how long, and what is sent out of this PC.

| Setting | What it does | Usual value |
|---|---|---|
| **Look facts up on the internet first**<br>`CHAT_WEB_SEARCH` | Before the chat model answers a factual question, Jarvis looks it up (Wikipedia; DuckDuckGo for news) so that a small model does not invent facts. The words of the question are sent there. Off keeps every question on this PC. | `true` |
| **Keep a record of conversations**<br>`LOG_CONVERSATIONS` | A private record of what you said and what Jarvis answered, one file a day in Logs/conversations. It never leaves this PC. Read it with python transcript.py. Off records nothing. | `true` |
| **Keep the record for**<br>`CONVERSATION_LOG_DAYS` | Records older than this many days are deleted when a session starts. 0 = keep for ever. From 0 to 3650 days. | `30` |

#### The window

How the window looks and behaves.

| Setting | What it does | Usual value |
|---|---|---|
| **Moving pictures in the window**<br>`GUI_ANIMATIONS` | Off shows still pictures, which is lighter on a slow PC. | `true` |

<!-- settings:end -->

---

## 9. Privacy and safety

* Your `.env` (password hash, keys), notes, tasks, voice print, face model, conversation records and the downloaded models stay on this PC and are kept out of git.
* The password is stored only as a salted hash. If you ever had a plain-text password in `.env`, the setup (or the admin panel's Change password) scrambles it.
* The chat model, the voice, the hearing, the wake word and the claps all run on your PC. The only things sent out are: the words of a factual question to Wikipedia/DuckDuckGo (if allowed),
  email you tell him to send, weather and similar look-ups, and downloads during setup.
* The setup only runs installers it has checked: the Visual C++ runtime must be signed by Microsoft, Python by the Python Software Foundation, and Ollama must have a valid signature.
* A backup is a plain folder, **not encrypted**, and holds your `.env` and voice print: keep it on a drive you control, and unplug it when you are not backing up.
* Email will not attach `.env` files or the face model. Shutting down, restarting, sleeping and sending email always need a yes.

---

## 10. Backups, moving to a new PC, restoring

**Back up.** Admin panel, **Backup and restore**: tick the parts, choose the folder on your backup drive, press **Back up now**. It makes
`Jarvis-Backup-<date>_<time>` with your files, a SHA-256 of every one (it re-checks them), and a README. (Add **The downloaded models** to the tick
list if you want them in it; they can always be downloaded again.) From a terminal: `python backup_jarvis.py --to F:\`.

**Also keep the whole folder.** Copying the entire Jarvis folder to your backup drive (without its `.venv`, if it has one) is the simplest complete backup, and the setup can restore from it.
The Ollama models live in `C:\Users\<you>\.ollama\models` (about 3 GB); copy that folder too if you want to avoid downloading them again.

**Code on GitHub.** The program itself is in a private GitHub repository (`rohanullahllc-ux/New-Jarvis`). GitHub deliberately does **not** hold `.env`, your notes, your voice print,
your logs or the models (section 9): those come from your backup.

**A new PC or a reinstalled Windows.** Copy the folder back (or `git clone`), double-click `Setup-Jarvis.bat`, choose **Bring back my earlier Jarvis**. Section 2.2.

**Undo a settings change.** Admin panel, Advanced, **Undo the last save** (the ten newest copies of `.env` are kept as `.env.bak-<time>`).

---

## 11. When something is wrong

Start with **`Setup-Jarvis.bat --check`** (or the admin panel's Overview): it looks at everything and says what is wrong. Then `Setup-Jarvis.bat` fixes it.

| What you see | What to do |
|---|---|
| **The setup says Python was not found** | Say yes when it offers to install it, or install Python 3.14 from python.org (tick "Add python.exe to PATH") and run the setup again. If `python` opens the Microsoft Store, that is Windows' shortcut, not Python: install the real one. |
| **"DLL load failed" or Jarvis closes at once** | The Visual C++ runtime is missing: run `Setup-Jarvis.bat` (it installs it). |
| **He does not hear me, or misses words** | Run `python microphone.py` (it checks Windows' privacy switch, the device, the volume and recognition). Turn on Settings > Privacy > Microphone, including "Let desktop apps access your microphone". The Windows microphone volume should be about 80 percent (he fixes it at start-up unless `MIC_VOLUME` is 0). Say "what is my microphone volume". |
| **He answers nobody / ignores me** | The voice lock may not recognise you (a cold, a noisy room, a different microphone). Say "turn off the voice lock", or redo the voice lesson in the admin panel. The typed box always works. |
| **He wakes by himself, or does not wake** | Admin panel, Waking and security: lower the wake word sensitivity if he wakes by mistake, raise it if he does not wake; the same for claps. `python clap.py --live` shows what the clap detector hears. |
| **No sound / he stops talking** | Run `python speech.py`. Check the Windows volume and output device. `TTS_ENABLED=false` gives text only. |
| **He is slow to understand me** | The speech model may be too big for the PC: admin panel, How Jarvis hears you, **Whisper model: tiny.en**. `python voice_test.py` times everything. |
| **He does not chat / "I can't reach Ollama"** | Open Ollama from the Start menu; check `ollama list`; download a model in the admin panel (Thinking and chatting). If answers are slow, close big programs (Chrome uses a lot of memory) or use `qwen2.5:1.5b`. |
| **The admin panel does not accept my password** | Use the password you set; if you forgot it: `python gate.py --set-password`. |
| **A setting does not seem to work** | Most take effect at the next start: use **Save and restart Jarvis**. The Overview page lists any value in `.env` that he would not understand (for example `STARTUP_GREETING=long`). |
| **NASA says "too many times this hour"** | Put a free personal key from api.nasa.gov in the admin panel (Accounts and online services). |
| **Email login refused** | Gmail, Yahoo and iCloud need an *app password*, not your real one. |
| **YouTube download fails** | `pip install -U yt-dlp` (YouTube changes often). |
| **The face check says it could not confirm you** | It is only an extra after the password. Redo the face lesson (new haircut, glasses, a different room). If it says OpenCV cannot recognise faces, install version 4: `pip install "opencv-contrib-python<5"`. |
| **Everything stopped after I changed something** | Admin panel > Advanced > **Undo the last save**, or run `Admin-Panel.bat` if the window will not open. |
| **Anything else** | Open the **LOG** in the window, read `Logs/setup.log` and `Logs/conversations/` (`python transcript.py`), and show them to whoever is helping. |

---

## 12. Where things are

| Folder or file | What it holds |
|---|---|
| `Setup-Jarvis.bat`, `Start-Jarvis.bat`, `Admin-Panel.bat` | The three double-click launchers. |
| `.env` | Your settings and password hash. `.env.bak-...` are the copies kept before each change. `.env.example` is the full commented list. |
| `DataBase/Notes`, `Tasks`, `TimeTable`, `memory.json` | Your notes, to-do lists, time table, and what you told him to remember. |
| `DataBase/shortcuts.json`, `contacts.json` | Your shortcuts and contacts. |
| `DataBase/voiceprint.npz` | Your voice print. `DataBase/FaceDetectionModule/` holds your face photos and model. |
| `DataBase/setup_state.json` | What the setup wizard did last time (no secrets). |
| `models/` | Voices, Whisper, the wake word, the voice-recognition model, and his own language model (re-downloadable). |
| `Logs/conversations/`, `Logs/setup.log` | The private record of conversations (one file a day) and of the setup. |
| `Backups/` | Files that a restore replaced, kept so nothing is lost. |
| `tests/` | His self-tests (`python -m unittest discover -s tests`). |

---

## 13. Words you may meet

* **Python** is the language Jarvis is written in. **pip** installs its libraries.
* **Ollama** is the free program that runs the chat model on your PC. **Whisper** hears you; **Piper** is his natural voice. Both run on your PC.
* **`.env`** is the settings file. **Hash** is the scrambled form of a password that cannot be turned back.
* **Wake word** is the phrase ("hey Jarvis") that wakes him. **Voice lock** makes him answer only your voice.
* **Dry run** means "show me what you would do, but change nothing".
