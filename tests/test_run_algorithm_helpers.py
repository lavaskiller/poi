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


class DatasetPreflightTests(unittest.TestCase):
    @staticmethod
    def _row(photo="a.jpg", **overrides):
        row = {
            "dataset": "sample",
            "photo": photo,
            "country": "Canada",
            "gt_mapkit": "Canonical Place",
            "gt_confidence": "confirmed_user",
        }
        row.update(overrides)
        return row

    def test_summary_and_build_cases_agree_for_runnable_dataset(self):
        rows = [self._row()]
        candidates = {("mapkit", "sample/a.jpg"): []}
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", candidates)
        cases = ra.build_cases(rows, {}, candidates, "sample", [])
        self.assertTrue(summary["runnable"])
        self.assertEqual(summary["eligible"], len(cases))
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 1)
        self.assertEqual(summary["runnable_now"], 1)

    def test_missing_artifact_blocks_preflight_and_runner(self):
        rows = [self._row()]
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", {})
        self.assertFalse(summary["runnable"])
        self.assertEqual(summary["blockers"], {"missing_candidate_artifact": 1})
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 0)
        self.assertEqual(summary["runnable_now"], 0)
        with self.assertRaises(ra.RunError):
            ra.build_cases(rows, {}, {}, "sample", [])

    def test_lossy_artifact_blocks_preflight_and_runner(self):
        rows = [self._row()]
        candidates = {("mapkit", "sample/a.jpg"): [
            {"name": "Candidate", "lossy_top3_summary": True},
        ]}
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", candidates)
        self.assertFalse(summary["runnable"])
        self.assertEqual(summary["blockers"], {"lossy_candidate_artifact": 1})
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 1)
        self.assertEqual(summary["runnable_now"], 0)
        with self.assertRaises(ra.RunError):
            ra.build_cases(rows, {}, candidates, "sample", [])

    def test_exclusion_reasons_use_runner_policy(self):
        rows = [
            self._row("missing-gt.jpg", gt_mapkit=""),
            self._row("korea.jpg", country="South Korea", gt_kakao="Kakao Place"),
            self._row("non-poi.jpg", gt_confidence="non_poi"),
        ]
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", {})
        self.assertEqual(summary["eligible"], 0)
        self.assertEqual(summary["exclusions"], {
            "no_gt": 1,
            "korea_pending_kakao": 1,
            "non_poi": 1,
        })
        self.assertEqual(ra.build_cases(rows, {}, {}, "sample", []), [])


if __name__ == "__main__":
    unittest.main()
