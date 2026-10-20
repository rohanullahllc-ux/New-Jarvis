"""Jarvis's self-setup: gets a bare Windows PC, or a freshly restored copy of the folder, to a working Jarvis, and asks you what you like.

    Setup-Jarvis.bat                 double-click it (it finds Python, or offers to install it, and starts the wizard)
    python setup_jarvis.py           the wizard itself
    python setup_jarvis.py --check   only look and report (changes nothing)

Everything in this package uses the standard library only, because it runs before anything has been installed. The pieces:

    console.py    what is printed and asked (and the scripted answers that tests and unattended runs use)
    effects.py   the things that touch the outside world: programs run, files downloaded, signatures checked (tests replace them)
    system.py    what this PC is: Windows, Python, memory, disk, internet, sound devices, the Visual C++ runtime, Ollama, models
    steps.py     the steps of the wizard, one class each: check() says if it is done, run() does it
    questions.py the questions about you, with the recommended answers
    restore.py   finding a backup of an earlier Jarvis and bringing your data back
    windows.py   shortcuts and "start with Windows"
    runner.py    runs the steps in order and tells you plainly what happened
    cli.py       the command line
"""
