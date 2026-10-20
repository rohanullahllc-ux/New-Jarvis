# Setting Jarvis up again on a fresh Windows

GitHub holds the **code**. It deliberately does not hold your private files or the big downloaded models (see the last section), so
keep those somewhere else (another drive, not the Windows drive) before wiping a PC.

## 1. Install the tools (once)

1. **Python 3.14** from python.org (tick "Add python.exe to PATH").
2. **Git** from git-scm.com (the default options are fine).
3. **Microsoft Visual C++ Redistributable (x64)**, the latest, from Microsoft: PyTorch and the voice models need it.
4. **Ollama** from ollama.com (the free local chat model), then in a terminal:  `ollama pull qwen2.5:1.5b`

## 2. Get the code

```
git clone https://github.com/rohanullahllc-ux/New-Jarvis.git
cd New-Jarvis
pip install -r requirements.txt
```

The first `git clone` of a private repository opens a browser window to sign in to GitHub.

## 3. Your settings and your data

* Copy your saved `.env` back into the project folder. Without it: copy `.env.example` to `.env`, fill in `USER_NAME`,
  `DEFAULT_CITY` and so on, and set the password with  `python gate.py --set-password`.
* Copy back your `DataBase/Notes`, `DataBase/Tasks`, `DataBase/TimeTable`, `DataBase/memory.json` if you saved them.

## 4. The models (they are downloaded again; none is in GitHub)

```
python -m piper.download_voices en_GB-alan-medium --download-dir models/piper     the natural voice (more: en_US-ryan-medium, en_US-lessac-medium, en_GB-northern_english_male-medium)
python stt.py --download                    Whisper, which hears you offline (STT_MODEL in .env)
python wakeword.py --download               "hey Jarvis"
python speaker.py --download                the model that tells your voice from others
python training/train_nlu.py                Jarvis's own command-understanding model (about a minute)
```

## 5. Teach him you again

```
python enroll_voice.py                      your voice print (about three minutes)
python DataBase/FaceDetectionModule/SampleGenerator.py     then   python DataBase/FaceDetectionModule/ModelTrainer.py    (your face, if you use it)
```

## 6. Check that everything works

```
python microphone.py                        the microphone, its Windows volume and speech recognition
python speech.py                            his voice
python -m unittest discover -s tests        all the tests (about 1,150)
python JarvisGUI.py                         start him
```

## What GitHub does NOT have (save these yourself)

| What | Where it is | Matters because |
|---|---|---|
| `.env` | project folder | your password hash, keys and settings |
| `DataBase/Notes`, `Tasks`, `TimeTable`, `memory.json`, `Books`, `ScreenShot` | `DataBase/` | your own notes, tasks and files |
| `DataBase/FaceDetectionModule/samples`, `trainer` | `DataBase/FaceDetectionModule/` | your face photos and model |
| `DataBase/voiceprint.npz` | `DataBase/` | your voice print (can simply be made again) |
| `Logs/` | project folder | the conversation records |
| `models/` | project folder | the downloaded models (can be downloaded again, steps above) |
| `training/nlu_real.txt` | `training/` | the sentences you really said, used to measure the language model |
| Ollama's models | `C:\Users\<you>\.ollama` | downloaded again with `ollama pull` |
