"""Access control: the single source of truth for "is this person allowed in?".

Both launchers - Startup.py (terminal) and JarvisGUI.py (window) - call into this module,
so the password rules and the face check are defined in exactly one place and neither
launcher can drift out of step with the other or skip the check.

The password comes from .env, never from source code:

    JARVIS_PASSWORD_HASH   salted PBKDF2 hash (preferred) - create it with:  python gate.py --set-password
    JARVIS_PASSWORD        plain text (works, but anyone who can read .env can read it)

If neither is set, nobody gets in (fail closed).
"""
import getpass
import hashlib
import hmac
import os
import re
import sys

import config
from config import BASE_DIR

ITERATIONS = 600_000        # OWASP's 2023 guidance for PBKDF2-HMAC-SHA256
SCHEME = "pbkdf2_sha256"


def hash_password(password, salt=None, iterations=ITERATIONS):
    """Return ``pbkdf2_sha256$iterations$salt$hash`` (all hex) for storing in .env."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def _matches_hash(attempt, stored):
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != SCHEME:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", attempt.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False                       # a malformed stored value never lets anyone in


def password_configured():
    return bool(config.JARVIS_PASSWORD_HASH or config.JARVIS_PASSWORD)


def check_password(attempt):
    """True only if `attempt` matches the configured password."""
    attempt = (attempt or "").strip()
    if config.JARVIS_PASSWORD_HASH:
        return _matches_hash(attempt, config.JARVIS_PASSWORD_HASH)
    if config.JARVIS_PASSWORD:
        return hmac.compare_digest(attempt.encode("utf-8"), config.JARVIS_PASSWORD.encode("utf-8"))
    return False


def face_check():
    """Best-effort webcam confirmation. Returns True if a known face is seen; never raises.

    The password is what grants access - a missing camera, model or OpenCV just means
    "could not confirm", so callers treat this as an extra, not a requirement.
    """
    try:
        from DataBase.FaceDetectionModule.FaceRecognition import FaceRocog
        return bool(FaceRocog())
    except Exception as e:
        print(f": Face check skipped ({e})")
        return False


def store_password(new_password, env_path=None):
    """Save the hash of `new_password` to .env and clear any plain-text password."""
    env_path = env_path or (BASE_DIR / ".env")
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for name, value in (("JARVIS_PASSWORD_HASH", hash_password(new_password)), ("JARVIS_PASSWORD", "")):
        line = f"{name}={value}"
        if re.search(rf"(?m)^{name}=.*$", text):
            text = re.sub(rf"(?m)^{name}=.*$", lambda _: line, text)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    env_path.write_text(text, encoding="utf-8")


def _set_password_interactively():
    print("Choose a new Jarvis unlock password (what you type is hidden).")
    first = getpass.getpass("New password: ")
    if len(first.strip()) < 4:
        print("Too short - use at least 4 characters.")
        return 1
    if first != getpass.getpass("Repeat it:   "):
        print("The two entries differ - nothing was changed.")
        return 1
    store_password(first.strip())
    print("Saved. .env now holds only a salted hash; the plain-text password was cleared.")
    return 0


if __name__ == "__main__":
    if "--set-password" in sys.argv:
        sys.exit(_set_password_interactively())
    print("Usage: python gate.py --set-password")
    print("Password configured:", "yes" if password_configured() else "NO - set JARVIS_PASSWORD in .env")
