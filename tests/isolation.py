"""Things on the PC that runs the tests which must not change what the tests expect."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def no_voice_lock():
    """For setUpModule: a voice print saved on this PC must not make the listening tests refuse the voices they use."""
    import speaker
    patcher = mock.patch.object(speaker, "lock_active", return_value=False)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def no_whisper():
    """For setUpModule: the tests of the listening chain must never load Whisper (they stand in for Google's service)."""
    import stt
    patcher = mock.patch.object(stt, "available", return_value=False)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def no_natural_voice():
    """For setUpModule: the tests that check the Windows voice must never load Piper or make the PC speak for real."""
    import tts_piper
    patcher = mock.patch.object(tts_piper, "available", return_value=False)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def no_windows_audio():
    """For setUpModule: the tests never read or change the real Windows microphone volume (the program puts it right at start-up).

    Tests of that very thing replace `subprocess.run` or the functions of audio_levels themselves."""
    import audio_levels
    patcher = mock.patch.object(audio_levels, "_run", side_effect=audio_levels.AudioError("the tests never touch the real Windows audio"))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def no_personal_lists():
    """For setUpModule: the shortcuts and contacts made in the admin panel are the user's own; tests must neither read nor change them
    ("open college portal" must not open a real site because someone has a shortcut of that name)."""
    import contacts
    import shortcuts
    for module in (contacts, shortcuts):
        patcher = mock.patch.object(module, "file", return_value=Path("no such personal list.json"))
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def isolated_database():
    """For setUpModule: notes, tasks, the time table and what Jarvis was told to remember go to a temporary folder for the whole module.

    A test that runs a real command ("take a note ... buy milk") would otherwise write into the real DataBase: tests of that kind left
    notes in the user's own Notes folder every time the suite ran."""
    from JarvisAdvancedBot import ChatBrain
    from JarvisAdvancedBot.tools import _common
    folder = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(folder.cleanup)
    for patcher in (mock.patch.object(_common, "DB", Path(folder.name)), mock.patch.object(ChatBrain, "FACTS_FILE", Path(folder.name) / "memory.json")):
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)
    _common.clear_cache()
    unittest.addModuleCleanup(_common.clear_cache)


def no_language_model():
    """For setUpModule: pretend the language model trained on this PC does not exist until the module's tests are done.

    Tests that run real command routing expect a sentence no pattern understands to go on to the chat brain; a model saved in
    models/nlu.joblib would turn some of those sentences into commands. (The same tests also get no personal shortcuts or contacts,
    and a temporary DataBase.)"""
    no_personal_lists()
    isolated_database()
    from JarvisAdvancedBot import NLU
    patcher = mock.patch.object(NLU, "MODEL_FILE", Path("no such language model.joblib"))
    patcher.start()
    NLU.reset()
    unittest.addModuleCleanup(patcher.stop)
    unittest.addModuleCleanup(NLU.reset)
