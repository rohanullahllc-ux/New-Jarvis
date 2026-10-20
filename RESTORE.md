# Setting Jarvis up again on a fresh Windows

**The easy way: double-click `Setup-Jarvis.bat`** (in the Jarvis folder). It finds Python or offers to install it, installs everything, downloads the models,
asks how you like things, and (if you choose "Bring back my earlier Jarvis from a backup") puts your settings, password, notes, voice print, face model and models back.
It only does what is missing, so you can run it again any time. The full story, with what each step does, is in [MANUAL.md](MANUAL.md) section 2.

What you need to bring to the new PC:

1. **The Jarvis folder.** Either copy it from your backup drive (for example `F:\Backup-2026-10-20\Jarvis-FINAL\New Jarvis`; it also holds your `.env`, notes, voice print and models), or
   `git clone https://github.com/rohanullahllc-ux/New-Jarvis.git` (the code only; the first clone of a private repository opens a browser window to sign in to GitHub).
   Put it somewhere on the new PC and scan it with the antivirus first if it came from a drive that has been in other computers.
2. **Your backup**, if you cloned from GitHub: the drive that holds your `Jarvis-Backup-...` folder or the copy of the Jarvis folder.
3. Optionally the Ollama models (`C:\Users\<you>\.ollama\models`, about 3 GB), saved next to the backup, so the chat model needs no download.

Then run `Setup-Jarvis.bat`, choose **restore**, and follow the questions.

---

## By hand (if the wizard cannot run)

### 1. Install the tools (once)

1. **Python 3.14** from python.org (tick "Add python.exe to PATH").
2. **Git** from git-scm.com (only if you want to clone).
3. **Microsoft Visual C++ Redistributable (x64)**, the latest, from Microsoft (https://aka.ms/vs/17/release/vc_redist.x64.exe): the voice libraries need it.
4. **Ollama** from ollama.com (the free local chat model), then in a terminal:  `ollama pull qwen2.5:1.5b`

### 2. Get the code and the libraries

```
git clone https://github.com/rohanullahllc-ux/New-Jarvis.git
cd New-Jarvis
pip install -r requirements.txt
```

### 3. Your settings and your data

* Copy your saved `.env` back into the project folder. Without it: copy `.env.example` to `.env`, fill in your name and city (or use `Admin-Panel.bat`), and set the password with  `python gate.py --set-password`.
* Copy back your `DataBase/Notes`, `DataBase/Tasks`, `DataBase/TimeTable`, `DataBase/memory.json`, `DataBase/shortcuts.json`, `DataBase/contacts.json` if you saved them.
  (`python backup_jarvis.py --restore "<your backup folder>"` does this for a `Jarvis-Backup-...` folder.)

### 4. The models (downloaded again; none is in GitHub)

```
python -m piper.download_voices en_GB-alan-medium --download-dir models/piper     the natural voice (more: en_US-ryan-medium, en_US-lessac-medium, en_GB-northern_english_male-medium)
python stt.py --download                    Whisper, which hears you offline (STT_MODEL in .env)
python wakeword.py --download               "hey Jarvis"
python speaker.py --download                the model that tells your voice from others
python training/train_nlu.py                Jarvis's own command-understanding model (about a minute)
```

### 5. Teach him you again

```
python enroll_voice.py                      your voice print (about three minutes)
python DataBase/FaceDetectionModule/SampleGenerator.py     then   python DataBase/FaceDetectionModule/ModelTrainer.py    (your face, if you use it)
```

### 6. Check that everything works

```
python setup_jarvis.py --check              looks at everything and says what is missing (changes nothing)
python microphone.py                        the microphone, its Windows volume and speech recognition
python speech.py                            his voice
python -m unittest discover -s tests        all the tests (about 1,500)
python JarvisGUI.py                         start him
```

---

## What GitHub does NOT have (save these yourself)

| What | Where it is | Matters because |
|---|---|---|
| `.env` | project folder | your password hash, keys and settings |
| `DataBase/Notes`, `Tasks`, `TimeTable`, `memory.json`, `shortcuts.json`, `contacts.json`, `Books`, `ScreenShot` | `DataBase/` | your own notes, tasks, lists and files |
| `DataBase/FaceDetectionModule/samples`, `trainer` | `DataBase/FaceDetectionModule/` | your face photos and model |
| `DataBase/voiceprint.npz` | `DataBase/` | your voice print (can simply be made again) |
| `Logs/` | project folder | the conversation records |
| `models/` | project folder | the downloaded models (can be downloaded again) |
| `training/nlu_real.txt` | `training/` | the sentences you really said, used to measure the language model |
| Ollama's models | `C:\Users\<you>\.ollama` | downloaded again with `ollama pull` |
| `Jarvis Personal Archive` | `C:\Users\<you>\Documents` | your books, videos, music, photos, school certificate and the old GUI artwork, moved out of the project in the 2026 rebuild (Jarvis does not need them to run; they are on the HDD in `Backup-2026-10-20\C-Users-not-yet-backed-up\Documents`) |

The admin panel's **Backup and restore** page (or `python backup_jarvis.py --to F:\`) saves all of the above except the models and Ollama's models into one folder.
