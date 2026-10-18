"""Things on the PC that runs the tests which must not change what the tests expect."""
import unittest
from pathlib import Path
from unittest import mock


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
