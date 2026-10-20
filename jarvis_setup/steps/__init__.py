"""The steps of the wizard, in the order they run."""
from .data import ProfileStep, RestoreStep
from .finish import SelfCheckStep
from .install import ModelsStep, OllamaStep, PackagesStep
from .machine import RuntimeStep, SystemStep
from .personal import IdentityStep, LanguageModelStep, PasswordStep, VoiceStep, WindowsStep


def all_steps():
    """Fresh step objects, in running order. (Restore comes before your answers so that a restored .env supplies them;
    the Visual C++ runtime comes before the packages that need it; the voice questions come after the models they play.)"""
    return [SystemStep(), RestoreStep(), ProfileStep(), RuntimeStep(), PackagesStep(), ModelsStep(), OllamaStep(), VoiceStep(),
            PasswordStep(), IdentityStep(), LanguageModelStep(), WindowsStep(), SelfCheckStep()]


BY_ID = {step.id: step for step in all_steps()}
