#!/usr/bin/env python3
"""Unit tests for run_algorithm naming, versioning, and atomic save."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import run_algorithm as ra  # noqa: E402


class SafeNameTests(unittest.TestCase):
    def test_slug_basic(self):
        self.assertEqual(ra._safe_name("Baseline Nearest"), "baseline-nearest")

    def test_strips_version_suffix(self):
        self.assertEqual(ra._safe_name("algo-v3"), "algo")
        self.assertEqual(ra._safe_name("algo__v12"), "algo")

    def test_empty_falls_back(self):
        self.assertEqual(ra._safe_name("   "), "algorithm")
        self.assertEqual(ra._safe_name(""), "algorithm")


class VersionPickTests(unittest.TestCase):
    def test_auto_increments(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("foo__v1.json", "foo__v2.json"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write("{}")
            self.assertEqual(ra._pick_version(d, "foo", "auto"), 3)

    def test_explicit_version(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ra._pick_version(d, "foo", "v7"), 7)

    def test_first_version(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ra._pick_version(d, "foo", "auto"), 1)


class AtomicSaveTests(unittest.TestCase):
    def test_delete_run_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ra.RunError):
                ra.delete_run(d, "nope", 1)

    def test_get_run_identity(self):
        with tempfile.TemporaryDirectory() as d:
            rec = {
                "name": "demo",
                "safe_name": "demo",
                "version": 1,
                "metrics": {"accuracy_pct": 10, "n_eligible": 1, "correct": 0},
                "cases": [],
            }
            path = os.path.join(d, "demo__v1.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            got = ra.get_run(d, "demo", 1)
            self.assertEqual(got["name"], "demo")
            with self.assertRaises(ra.RunError):
                ra.get_run(d, "other", 1)


if __name__ == "__main__":
    unittest.main()
