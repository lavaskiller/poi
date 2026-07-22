#!/usr/bin/env python3
"""Unit tests for tools/check_deps.py."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


def _load_check_deps():
    root = Path(__file__).resolve().parent.parent
    path = root / "tools" / "check_deps.py"
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location("poi_check_deps", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CheckDepsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_check_deps()

    def test_skip_env(self):
        with mock.patch.dict(os.environ, {"POI_SKIP_DEPS_CHECK": "1"}, clear=False):
            out = self.mod.check_runtime_deps()
        self.assertTrue(out["ready"])
        self.assertTrue(out["skipped"])

    def test_parse_requirements_strips_pins(self):
        names = self.mod._parse_requirements(self.mod.REQUIREMENTS_PATH)
        self.assertIn("Pillow", names)

    def test_missing_pillow_fails(self):
        real_import = importlib.import_module

        def fake_import(name, *a, **k):
            if name == "PIL":
                raise ImportError("No module named PIL")
            return real_import(name, *a, **k)

        with mock.patch.dict(os.environ, {"POI_SKIP_DEPS_CHECK": ""}, clear=False):
            with mock.patch.object(self.mod.importlib, "import_module", side_effect=fake_import):
                # Keep platform checks happy on Darwin by leaving swift alone;
                # we only care that Pillow missing flips ready=False.
                out = self.mod.check_runtime_deps()
        self.assertFalse(out["ready"])
        keys = {m["key"] for m in out["missing"]}
        self.assertTrue(any(k.startswith("py:") for k in keys))

    def test_live_env_ready_or_reports(self):
        """On the developer machine deps should normally pass."""
        with mock.patch.dict(os.environ, {"POI_SKIP_DEPS_CHECK": ""}, clear=False):
            out = self.mod.check_runtime_deps()
        self.assertIn("ready", out)
        self.assertIn("items", out)
        # If this machine is fully set up, ready is True.
        if out["ready"]:
            self.assertEqual(out["missing"], [])


if __name__ == "__main__":
    unittest.main()
