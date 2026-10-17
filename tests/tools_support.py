"""Shared fixtures for the tools tests.

Nothing built on ToolCase touches the network, the real DataBase folder, the browser, the keyboard,
the clipboard, e-mail or the power button: HTTP is faked, DataBase is a temporary folder, and each
test intercepts whatever side effect it exercises.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic.lib.tools import ToolError  # noqa: E402
import rates  # noqa: E402
from JarvisAdvancedBot.tools import _common  # noqa: E402


class FakeResponse:
    """Just enough of requests.Response for the tools."""

    def __init__(self, data=None, status=200, text=None, content=None):
        self.status_code = status
        self._data = data
        self.text = text if text is not None else (json.dumps(data) if data is not None else "")
        self.content = content if content is not None else self.text.encode("utf-8")
        self.ok = status < 400

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


class Http:
    """Stands in for requests.get: answers by the first route whose fragment appears in the URL."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, fragment, response):
        """``response`` is a FakeResponse, an exception to raise, or ``function(url, params)`` returning either."""
        self.routes.append((fragment, response))
        return self

    def __call__(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        for fragment, response in self.routes:
            if fragment in url:
                result = response(url, dict(params or {})) if callable(response) else response
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected request to {url}")

    def urls(self):
        return [url for url, _ in self.calls]

    def params_for(self, fragment):
        return next(params for url, params in self.calls if fragment in url)


class ToolCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name)
        self.opened = []
        self.http = Http()
        for patcher in (
            mock.patch.object(_common, "DB", self.db),
            mock.patch("requests.get", self.http),
            mock.patch("webbrowser.open", side_effect=lambda url, *a, **k: self.opened.append(url) or True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        _common.clear_cache()
        rates._cache.clear()

    def fails(self, call, *fragments):
        """Assert the tool raises ToolError containing every fragment; returns the message."""
        with self.assertRaises(ToolError) as caught:
            call()
        message = str(caught.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message
