#!/usr/bin/env python3
"""Unit tests for the release gate scorecard + threshold evaluation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import release_gate as rg  # noqa: E402


def _case(ds, ph, pred="X", correct=False, canon=False, err=None, lat=10.0):
    return {"dataset": ds, "photo": ph, "prediction": pred, "correct": correct,
            "correct_canonical": canon, "error": err, "latency_ms": lat}


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.mem = {
            ("d", "a.jpg"): "test", ("d", "b.jpg"): "test",
            ("d", "c.jpg"): "test", ("d", "t.jpg"): "train",
        }
        self.rows = {
            ("d", "a.jpg"): {"dataset": "d", "category": "cafe",
                             "caption_ondevice": "sign", "app_nearby_n_wide": "3",
                             "country": "US"},
            ("d", "b.jpg"): {"dataset": "d", "category": "cafe",
                             "caption_ondevice": "", "app_nearby_n_wide": "0",
                             "country": "US"},
            ("d", "c.jpg"): {"dataset": "d", "category": "park",
                             "caption_ondevice": "x", "app_nearby_n_wide": "9",
                             "country": "JP"},
        }

    def test_only_test_split_counted(self):
        cases = [_case("d", "a.jpg", correct=True, canon=True),
                 _case("d", "b.jpg", canon=True),
                 _case("d", "c.jpg", pred="", ),            # abstain
                 _case("d", "t.jpg", correct=True, canon=True)]  # train, excluded
        sc = rg.scorecard_from(cases, self.mem, self.rows, "test")
        ov = sc["overall"]
        self.assertEqual(ov["total"], 3)
        self.assertEqual(ov["answered"], 2)               # a + b answered, c abstains
        self.assertEqual(ov["accuracy_exact"], round(1 / 3, 4))
        self.assertEqual(ov["accuracy_canonical"], round(2 / 3, 4))
        self.assertEqual(ov["coverage"], round(2 / 3, 4))

    def test_wrong_leak_counts_answered_incorrect(self):
        cases = [_case("d", "a.jpg", pred="wrong", canon=False),  # leak
                 _case("d", "b.jpg", pred="", canon=False),       # abstain, not leak
                 _case("d", "c.jpg", pred="ok", canon=True)]
        sc = rg.scorecard_from(cases, self.mem, self.rows, "test")
        self.assertEqual(sc["overall"]["wrong_leak_rate"], round(1 / 3, 4))

    def test_missing_test_ids_reported(self):
        cases = [_case("d", "a.jpg", canon=True)]
        sc = rg.scorecard_from(cases, self.mem, self.rows, "test")
        self.assertEqual(sc["test_ids_total"], 3)
        self.assertEqual(len(sc["test_ids_missing_from_run"]), 2)

    def test_slices_present(self):
        cases = [_case("d", "a.jpg", canon=True), _case("d", "c.jpg", canon=False)]
        sc = rg.scorecard_from(cases, self.mem, self.rows, "test")
        self.assertIn("category=cafe", sc["slices"])
        self.assertIn("has_ocr=ocr", sc["slices"])
        self.assertIn("country=JP", sc["slices"])


class EvaluateTests(unittest.TestCase):
    def _sc(self, **overall):
        base = {"total": 100, "answered": 90, "accuracy_exact": 0.5,
                "accuracy_canonical": 0.7, "coverage": 0.9,
                "wrong_leak_rate": 0.05, "p95_latency_ms": 100.0}
        base.update(overall)
        return {"split": "test", "run": "r__v1", "overall": base, "slices": {},
                "test_ids_total": 100, "test_ids_missing_from_run": []}

    def test_pass_when_within_tolerance(self):
        sc = self._sc()
        baseline = {"overall": {"accuracy_exact": 0.5, "accuracy_canonical": 0.7,
                                "coverage_min": 0.85, "wrong_leak_max": 0.08,
                                "p95_latency_ms_max": 150.0}}
        v = rg.evaluate(sc, baseline)
        self.assertTrue(v["passed"], v["checks"])

    def test_fail_on_accuracy_drop_beyond_tolerance(self):
        sc = self._sc(accuracy_canonical=0.6)  # baseline 0.7, tol 0.02
        baseline = {"overall": {"accuracy_canonical": 0.7}}
        v = rg.evaluate(sc, baseline)
        self.assertFalse(v["passed"])

    def test_fail_on_wrong_leak_ceiling(self):
        sc = self._sc(wrong_leak_rate=0.2)
        baseline = {"overall": {"wrong_leak_max": 0.08}}
        v = rg.evaluate(sc, baseline)
        self.assertFalse(v["passed"])

    def test_slice_floor_skipped_below_min_n(self):
        sc = self._sc()
        sc["slices"] = {"dataset=d": {"n": 2, "correct_canonical": 0,
                                      "accuracy_canonical": 0.0}}
        baseline = {"slices": {"dataset=d": 0.7}, "slice_min_n": 5}
        v = rg.evaluate(sc, baseline)
        # n<min_n → skipped, not failed
        self.assertTrue(v["passed"])
        self.assertTrue(any(c["status"] == "skip" and "slice" in c["check"]
                            for c in v["checks"]))

    def test_slice_floor_enforced_above_min_n(self):
        sc = self._sc()
        sc["slices"] = {"dataset=d": {"n": 20, "correct_canonical": 2,
                                      "accuracy_canonical": 0.1}}
        baseline = {"slices": {"dataset=d": 0.7}, "slice_min_n": 5}
        v = rg.evaluate(sc, baseline)
        self.assertFalse(v["passed"])


class EmitBaselineTests(unittest.TestCase):
    def test_emits_floors_from_scorecard(self):
        sc = {"split": "test", "run": "r__v1",
              "overall": {"total": 50, "answered": 45, "accuracy_exact": 0.44,
                          "accuracy_canonical": 0.65, "coverage": 0.9,
                          "wrong_leak_rate": 0.05, "p95_latency_ms": 80.0},
              "slices": {"dataset=d": {"n": 40, "correct_canonical": 26,
                                       "accuracy_canonical": 0.65}}}
        b = rg.emit_baseline(sc)
        self.assertEqual(b["overall"]["accuracy_canonical"], 0.65)
        self.assertEqual(b["overall"]["wrong_leak_max"], 0.07)
        self.assertEqual(b["overall"]["p95_latency_ms_max"], 100.0)
        self.assertIn("dataset=d", b["slices"])


if __name__ == "__main__":
    unittest.main()
