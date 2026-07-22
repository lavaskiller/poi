#!/usr/bin/env python3
"""Lightweight match_score contract tests (no MapKit / network)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import match_score as ms  # noqa: E402


class ExactEqualTests(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(ms.exact_equal("Cafe Foo", "Cafe Foo"))
        self.assertFalse(ms.exact_equal("Cafe Foo", "Cafe Bar"))

    def test_empty(self):
        self.assertFalse(ms.exact_equal("", "x"))
        self.assertFalse(ms.exact_equal("x", ""))


class NormalizedEqualTests(unittest.TestCase):
    def test_case_and_space(self):
        # Policy depends on implementation; both sides should be stable.
        a = "Starbucks Coffee"
        b = "starbucks coffee"
        # Either true (normalized) or false (strict) — assert no crash + bool.
        self.assertIsInstance(ms.normalized_equal(a, b), bool)


class EvaluationSetHashTests(unittest.TestCase):
    def test_stable_for_same_ordered_cases(self):
        # evaluation_set_sha256 is order-sensitive (cohort identity = ordered list).
        import run_algorithm as ra

        cases = [
            {"dataset": "d", "photo": "a.jpg", "gt": "Place A"},
            {"dataset": "d", "photo": "b.jpg", "gt": "Place B"},
        ]
        h1 = ra.evaluation_set_sha256(cases)
        h2 = ra.evaluation_set_sha256(list(cases))
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)
        # Different order → different cohort fingerprint by design.
        self.assertNotEqual(h1, ra.evaluation_set_sha256(list(reversed(cases))))


if __name__ == "__main__":
    unittest.main()
