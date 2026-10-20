"""Tests for the import order that keeps the voice libraries from crashing the window:  python -m unittest tests.test_native_libs -v"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_libs  # noqa: E402


class SafeTests(unittest.TestCase):
    def test_a_library_is_safe_when_it_is_already_loaded_or_the_window_library_is_not(self):
        with mock.patch.dict(sys.modules, {"PyQt5.QtCore": object(), "already_here": object()}):
            self.assertTrue(native_libs.safe("already_here"))              # loaded first: nothing left to crash
            self.assertFalse(native_libs.safe("not_loaded_yet"))           # Qt first, then this one: the crash
        with mock.patch.dict(sys.modules):
            sys.modules.pop("PyQt5.QtCore", None)
            self.assertTrue(native_libs.safe("not_loaded_yet"))


class PreloadTests(unittest.TestCase):
    def setUp(self):
        saved = list(native_libs.loaded)
        native_libs.loaded.clear()
        self.addCleanup(lambda: (native_libs.loaded.clear(), native_libs.loaded.extend(saved)))

    def test_each_library_is_loaded_once_and_a_missing_one_is_skipped(self):
        def fake_import(name):
            if name == "sherpa_onnx":
                raise ImportError("not installed")
            return object()

        with mock.patch.object(native_libs.importlib, "import_module", side_effect=fake_import) as load, \
                mock.patch.object(native_libs, "safe", return_value=True):
            self.assertEqual(native_libs.preload(), ["onnxruntime", "faster_whisper"])
            native_libs.preload()
        self.assertEqual(load.call_count, 4)                              # (the second call tried only the one that failed)

    def test_nothing_is_imported_when_the_window_library_got_in_first(self):
        with mock.patch.object(native_libs.importlib, "import_module") as load, mock.patch.object(native_libs, "safe", return_value=False):
            self.assertEqual(native_libs.preload(), [])
        load.assert_not_called()

    def test_the_gui_package_does_this_before_anything_else(self):
        import gui
        self.assertIs(gui.native_libs, native_libs)
        source = (Path(__file__).resolve().parents[1] / "gui" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("native_libs.preload()", source)
        self.assertNotIn("import PyQt5", source)                      # (this file must never be the one that loads Qt first)
        self.assertNotIn("from PyQt5", source)


if __name__ == "__main__":
    unittest.main()
