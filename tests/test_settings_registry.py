"""Tests for the list of settings:  python -m unittest tests.test_settings_registry -v

The list (settings_registry.py) and the program (config.py) both say what each setting is and what it is when nothing is set, so a
test compares them: a setting added to one and forgotten in the other must fail here, not on someone's PC."""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import settings_registry as registry  # noqa: E402

READERS = {"key", "number", "decimal", "flag"}


def settings_read_by_config():
    """{NAME: (reader, default)} for every setting config.py reads from the environment."""
    tree = ast.parse(Path(config.__file__).read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in READERS and node.args:
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue                                           # (the readers' own `key(name)` calls)
            default = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else ("" if node.func.id == "key" else None)
            found[first.value] = (node.func.id, default)
    return found


class AgreesWithConfigTests(unittest.TestCase):
    def test_every_setting_config_reads_is_in_the_list_and_the_other_way_round(self):
        read = set(settings_read_by_config())
        listed = set(registry.BY_KEY)
        self.assertEqual(sorted(read - listed), [], "config.py reads settings that settings_registry.py does not list")
        self.assertEqual(sorted(listed - read), [], "settings_registry.py lists settings that config.py never reads")

    def test_the_defaults_are_the_same_in_both(self):
        different = []
        for name, (reader, default) in settings_read_by_config().items():
            listed = registry.BY_KEY[name].default
            if reader == "flag":
                ok = listed == ("true" if default else "false")
            elif reader == "number":
                ok = listed == str(default)
            elif reader == "decimal":
                ok = float(listed) == float(default)
            else:
                ok = listed == str(default)
            if not ok:
                different.append(f"{name}: config.py says {default!r}, the list says {listed!r}")
        self.assertEqual(different, [])

    def test_the_kind_matches_the_way_config_reads_it(self):
        wrong = []
        for name, (reader, _) in settings_read_by_config().items():
            kind = registry.BY_KEY[name].kind
            ok = {"flag": kind == "bool", "number": kind == "int", "decimal": kind == "float", "key": kind in ("text", "choice", "secret")}[reader]
            if not ok:
                wrong.append(f"{name}: read as {reader} but listed as {kind}")
        self.assertEqual(wrong, [])


class ListShapeTests(unittest.TestCase):
    def test_every_setting_has_a_label_and_help_in_plain_words(self):
        for setting in registry.SETTINGS:
            self.assertTrue(setting.label.strip(), setting.key)
            self.assertGreater(len(setting.help), 15, setting.key)
            self.assertNotIn("\n", setting.help, setting.key)

    def test_every_strict_choice_includes_its_own_default(self):
        for setting in registry.SETTINGS:
            if setting.kind == "choice" and setting.strict:
                self.assertIn(setting.default, setting.choice_values(), setting.key)

    def test_every_default_passes_its_own_check(self):
        for setting in registry.SETTINGS:
            if setting.default == "":
                continue
            result = registry.validate(setting.key, setting.default)
            self.assertTrue(result.ok, f"{setting.key}: {result.message}")

    def test_only_the_harmless_demo_key_has_a_default_among_the_secrets(self):
        with_default = [s.key for s in registry.SETTINGS if s.secret and s.default]
        self.assertEqual(with_default, ["NASA_API_KEY"])

    def test_the_password_settings_are_hidden_from_the_ordinary_pages(self):
        shown = {s.key for g in registry.GROUPS for s in registry.settings_in(g.id)}
        self.assertNotIn("JARVIS_PASSWORD", shown)
        self.assertNotIn("JARVIS_PASSWORD_HASH", shown)
        self.assertEqual(len(shown) + 2, len(registry.SETTINGS))

    def test_advanced_settings_can_be_left_out(self):
        everything = registry.settings_in("brain")
        simple = registry.settings_in("brain", advanced=False)
        self.assertLess(len(simple), len(everything))
        self.assertTrue(all(not s.advanced for s in simple))

    def test_every_group_has_settings(self):
        for group in registry.GROUPS:
            self.assertTrue(registry.settings_in(group.id, hidden=True), group.id)


class ValidationTests(unittest.TestCase):
    def check(self, key, raw):
        return registry.validate(key, raw)

    def test_yes_and_no_are_understood_in_the_usual_words(self):
        for raw in ("Yes", "on", "1", "TRUE", "y"):
            self.assertEqual(self.check("TTS_ENABLED", raw).value, "true")
        for raw in ("No", "off", "0", "false", "n"):
            self.assertEqual(self.check("TTS_ENABLED", raw).value, "false")
        self.assertFalse(self.check("TTS_ENABLED", "maybe").ok)

    def test_numbers_must_be_numbers_inside_their_range(self):
        self.assertTrue(self.check("MIC_VOLUME", "80").ok)
        self.assertEqual(self.check("MIC_VOLUME", "120").message, "must be between 0 and 100 percent")
        self.assertFalse(self.check("MIC_VOLUME", "loud").ok)
        self.assertFalse(self.check("MIC_VOLUME", "").ok)
        self.assertEqual(self.check("MIC_PAUSE", "1.50").value, "1.5")
        self.assertFalse(self.check("MIC_PAUSE", "0.1").ok)
        self.assertEqual(self.check("TTS_RATE", "-3").value, "-3")

    def test_zero_is_allowed_where_it_means_automatic(self):
        self.assertTrue(self.check("VOICE_MATCH", "0").ok)
        self.assertTrue(self.check("VOICE_MATCH", "0.55").ok)
        self.assertFalse(self.check("VOICE_MATCH", "0.1").ok)
        self.assertTrue(self.check("CONVERSATION_LOG_DAYS", "0").ok)

    def test_a_strict_choice_must_be_one_of_the_choices_and_is_tidied(self):
        self.assertEqual(self.check("STARTUP_GREETING", "Full").value, "full")
        bad = self.check("STARTUP_GREETING", "long")
        self.assertFalse(bad.ok)
        self.assertIn("short, full, silent", bad.message)
        self.assertFalse(self.check("STARTUP_GREETING", "").ok)

    def test_a_loose_choice_accepts_anything_sensible(self):
        self.assertTrue(self.check("PIPER_VOICE", "my_own_voice-medium").ok)
        self.assertTrue(self.check("ADDRESS_AS", "your honour").ok)
        self.assertEqual(self.check("HOME_CURRENCY", "usd").value, "USD")
        self.assertFalse(self.check("HOME_CURRENCY", "dollars").ok)

    def test_patterns_catch_obvious_mistakes(self):
        self.assertTrue(self.check("EMAIL_ADDRESS", "ali@example.com").ok)
        self.assertFalse(self.check("EMAIL_ADDRESS", "ali at example").ok)
        self.assertTrue(self.check("EMAIL_ADDRESS", "").ok)
        self.assertTrue(self.check("OLLAMA_KEEP_ALIVE", "10m").ok)
        self.assertTrue(self.check("OLLAMA_KEEP_ALIVE", "-1").ok)
        self.assertFalse(self.check("OLLAMA_KEEP_ALIVE", "ten minutes").ok)
        self.assertFalse(self.check("OLLAMA_URL", "ollama.local").ok)
        self.assertTrue(self.check("SPEECH_LANGUAGE", "en-pk").ok)
        self.assertFalse(self.check("SPEECH_LANGUAGE", "english").ok)

    def test_a_setting_must_fit_on_one_line(self):
        self.assertFalse(self.check("USER_NAME", "two\nlines").ok)
        self.assertFalse(self.check("USER_NAME", "a\x00b").ok)

    def test_a_setting_of_your_own_is_accepted_as_it_is(self):
        self.assertEqual(self.check("RAPIDAPI_KEY", " abc ").value, "abc")

    def test_what_is_wrong_in_an_existing_env_file_is_found(self):
        found = dict(registry.problems({"STARTUP_GREETING": "long", "MIC_VOLUME": "80", "TTS_RATE": "99", "JARVIS_PASSWORD": "x", "OWN": "y"}))
        self.assertEqual(sorted(found), ["STARTUP_GREETING", "TTS_RATE"])

    def test_keys_of_your_own_are_reported_but_kept(self):
        self.assertEqual(registry.unknown_keys({"USER_NAME": "a", "RAPIDAPI_KEY": "b"}), ["RAPIDAPI_KEY"])

    def test_empty_numbers_and_switches_mean_the_usual_value(self):
        used = registry.effective({"MIC_VOLUME": "", "TTS_ENABLED": " ", "USER_NAME": "Ali", "DEFAULT_CITY": ""})
        self.assertEqual(used["MIC_VOLUME"], ("80", True))
        self.assertEqual(used["TTS_ENABLED"], ("true", True))
        self.assertEqual(used["USER_NAME"], ("Ali", False))
        self.assertEqual(used["DEFAULT_CITY"], ("", False))          # an empty text really is empty, as in config.py
        self.assertEqual(used["TTS_RATE"], ("0", True))


class FilesMadeFromTheListTests(unittest.TestCase):
    def test_the_example_file_is_exactly_what_the_list_makes(self):
        self.assertEqual(registry.check(), [])

    def test_the_example_keeps_comments_on_their_own_lines_and_every_setting_in_it(self):
        text = registry.render_env_example()
        for setting in registry.SETTINGS:
            self.assertRegex(text, rf"(?m)^(?:# )?{setting.key}=", setting.key)
        for line in text.splitlines():
            if "=" in line and not line.startswith("#"):
                self.assertNotIn(" #", line)
        self.assertRegex(text, r"(?m)^MIC_VOLUME=80$")
        self.assertIn("0 = never touch", re.sub(r"\s*\n#\s*", " ", text))

    def test_the_manual_table_names_every_visible_setting(self):
        table = registry.render_manual_table()
        for setting in registry.SETTINGS:
            if not setting.hidden:
                self.assertIn(f"`{setting.key}`", table)


if __name__ == "__main__":
    unittest.main()
