"""Things on the PC that runs the tests which must not change what the tests expect."""
import unittest
from pathlib import Path
from unittest import mock


def no_windows_audio():
    """For setUpModule: the tests never read or change the real Windows microphone volume (the program puts it right at start-up).

    Tests of that very thing replace `subprocess.run` or the functions of audio_levels themselves."""
    import audio_levels
    patcher = mock.patch.object(audio_levels, "_run", side_effect=audio_levels.AudioError("the tests never touch the real Windows audio"))
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def no_language_model():
    """For setUpModule: pretend the language model trained on this PC does not exist until the module's tests are done.

    Tests that run real command routing expect a sentence no pattern understands to go on to the chat brain; a model saved in
    models/nlu.joblib would turn some of those sentences into commands."""
    from JarvisAdvancedBot import NLU
    patcher = mock.patch.object(NLU, "MODEL_FILE", Path("no such language model.joblib"))
    patcher.start()
    NLU.reset()
    unittest.addModuleCleanup(patcher.stop)
    unittest.addModuleCleanup(NLU.reset)
