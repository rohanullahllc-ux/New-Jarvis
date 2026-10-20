# Jarvis roadmap

Rule: one phase at a time. After each phase Jarvis is tested live, the tests pass, and the user says "go" before the next one.
Everything is free and local first. This PC: i5-6200U, 2 cores, 8 GB RAM, no GPU.

## Done
- Stage 0 machine prep, Stage 1 chat over Ollama, Stage 2 own trained command model (waiting for the user's voice test).
- Voice input rebuilt, Windows microphone level kept right, wording-robust commands.

## Phase A: the voice package (removes the microphone and Google problems)  - BUILT 2026-10-20, waiting for the live gate
1. Natural offline voice (Piper) instead of the Windows voice. Done.
2. Offline speech recognition (Whisper) instead of Google; Google stays as the second opinion. Done.
3. Wake word "hey Jarvis" offline (openWakeWord), so he wakes by voice while the window is open. Done.
4. Clap detection (a double clap wakes him; the password is still asked). Done.
5. Only the owner's voice (voice print, `python enroll_voice.py`; "turn off the voice lock" as the way out). Done.
Gate (needs the user's voice, claps and a short session): `python voice_test.py` (10 sentences by voice), `python enroll_voice.py` then
`--test`, `python clap.py --live`, then `python JarvisGUI.py` and wake him by voice and by clapping. Tune STT_MODEL, WAKE_SENSITIVITY,
CLAP_SENSITIVITY and VOICE_MATCH from those numbers. Not started, on purpose: a tray icon / start-with-Windows background mode.

## Phase B: proactive assistant
Morning briefing, overdue tasks, low battery, reminders spoken on their own, daily summary. Settings to switch each off.

## Phase C: memory that learns you
Remembers habits and facts, searches your own notes and files by meaning (local embeddings), suggests things at the right time.

## Phase D: phone and remote control
Small private web page or Telegram bot: ask Jarvis, lock the PC, read the to-do list from the phone. Password and allow-list first.

## Phase E: screen and vision
"What is on my screen", read an error, summarise a PDF (screenshot + OCR + small vision model). Slow on this PC, by design.

## Phase F: agent mode (old Stage 5)
Jarvis plans several steps and uses his tools. Risky actions always ask yes or no; step cap; everything logged.

## Phase G: your own models (old Stages 3 and 4)
From-scratch GPT in PyTorch, then LoRA fine-tune into "jarvis-brain". Slow on this PC; nothing else depends on it.

## Phase H: computer control by sight
Clicking and typing by looking at the screen. Last, with confirmation on every step.

## Phase I: the user's own most advanced idea
To be described by the user, then fitted into the order above.
