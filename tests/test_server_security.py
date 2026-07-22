#!/usr/bin/env python3
"""Security helper tests for server.py (no live HTTP server required)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest import mock


def _load_server_module():
    """Load server.py as a module without executing __main__."""
    root = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(root, "server.py")
    # Ensure tools/ is importable the same way server expects.
    tools = os.path.join(root, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("poi_server", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Avoid binding ports / starting threads during import side effects.
    with mock.patch.dict(os.environ, {"POI_PORT": "18420"}, clear=False):
        spec.loader.exec_module(mod)
    return mod


class BlockedStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server_module()

    def test_blocks_git_and_source(self):
        self.assertTrue(self.srv._is_blocked_static(".git/config"))
        self.assertTrue(self.srv._is_blocked_static("server.py"))
        self.assertTrue(self.srv._is_blocked_static("tools/run_algorithm.py"))

    def test_allows_web_assets(self):
        # Public UI paths should not be blocked by name alone.
        self.assertFalse(self.srv._is_blocked_static("web/dist/index.html"))
        self.assertFalse(self.srv._is_blocked_static("web/dist/assets/index.js"))


class OriginHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server_module()

    def test_default_allowed_origins_include_vite(self):
        # Default set is used when env is unset at import time.
        if self.srv.ALLOWED_ORIGINS is not None:
            self.assertIn("http://localhost:5173", self.srv.ALLOWED_ORIGINS)
            self.assertIn("http://127.0.0.1:8420", self.srv.ALLOWED_ORIGINS)


if __name__ == "__main__":
    unittest.main()
