#!/usr/bin/env python3
"""Unit coverage for the CI gate scripts so a local `unittest` run reproduces
what CI enforces (import isolation + eval-config coherence)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"


def _load(mod_name: str, filename: str):
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    spec = importlib.util.spec_from_file_location(mod_name, _TOOLS / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ImportIsolationTests(unittest.TestCase):
    def test_backend_is_isolated(self):
        mod = _load("poi_check_import_isolation", "check_import_isolation.py")
        self.assertEqual(mod.main(), 0)


class EvalConfigTests(unittest.TestCase):
    def test_committed_config_is_coherent(self):
        mod = _load("poi_check_eval_config", "check_eval_config.py")
        self.assertEqual(mod.main(), 0)

    def test_incoherent_ratios_are_rejected(self):
        mod = _load("poi_check_eval_config", "check_eval_config.py")
        problems = []
        with tempfile.NamedTemporaryFile("w", suffix=".policy.json", delete=False) as fh:
            json.dump(
                {
                    "schema": "eval-split/v1",
                    "ratios": {"train": 0.6, "val": 0.2, "test": 0.9},
                    "source_csv_sha256": "0" * 64,
                    "counts": {"train": 1, "val": 1, "test": 1, "eligible": 9},
                },
                fh,
            )
            path = fh.name
        try:
            mod._check_split_policy(path, problems)
        finally:
            os.unlink(path)
        joined = " ".join(problems)
        self.assertIn("ratios sum", joined)
        self.assertIn("!= eligible", joined)


if __name__ == "__main__":
    unittest.main()
