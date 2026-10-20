"""The window. The voice libraries must be loaded before PyQt5 is (see native_libs.py), so that happens here, first."""
import native_libs

native_libs.preload()
