#!/usr/bin/env python3
"""Progress normalization for background jobs (ingest + pipeline)."""

from __future__ import annotations

import os
import sys
import unittest

# server.py lives at repo root; helpers under test are pure functions.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402


class SubstepFractionTests(unittest.TestCase):
    def test_done_over_total(self):
        self.assertAlmostEqual(
            server._substep_fraction({"done": 25, "total": 100}), 0.25)

    def test_terminal_status_is_complete(self):
        self.assertEqual(server._substep_fraction({"status": "done"}), 1.0)
        self.assertEqual(server._substep_fraction({"status": "skipped"}), 1.0)
        self.assertEqual(server._substep_fraction({"status": "error"}), 1.0)

    def test_unknown_total_is_zero(self):
        self.assertEqual(server._substep_fraction({"done": 3, "total": 0}), 0.0)
        self.assertEqual(server._substep_fraction({}), 0.0)


class NormalizeProgressTests(unittest.TestCase):
    def test_done_total_becomes_pct(self):
        out = server._normalize_progress({"done": 2, "total": 8, "step": "ocr"})
        self.assertEqual(out["pct"], 25.0)
        self.assertIn("message", out)

    def test_legacy_int_done_folds_live_substeps(self):
        # Old emitters used whole-stage ``done`` + live substeps only.
        out = server._normalize_progress({
            "done": 2,
            "total": 5,
            "step": "parallel",
            "substeps": {
                "ocr": {"done": 50, "total": 100, "status": "running"},
                "mapkit_nearby": {"done": 50, "total": 100, "status": "running"},
            },
        })
        self.assertEqual(out["pct"], 50.0)
        self.assertEqual(out["effective_done"], 2.5)
        self.assertTrue(
            "ocr" in out["message"] or "mapkit_nearby" in out["message"],
            out["message"],
        )

    def test_fractional_done_not_double_counted(self):
        # New pipeline already folds leaf fractions into ``done``.
        out = server._normalize_progress({
            "done": 2.5,
            "total": 5,
            "pct": 50.0,
            "step": "ocr_nearby",
            "substeps": {
                "exif": {"status": "done", "done": 1, "total": 1},
                "geocode": {"status": "done", "done": 1, "total": 1},
                "ocr": {"done": 50, "total": 100, "status": "running"},
                "mapkit_nearby": {"done": 50, "total": 100, "status": "running"},
                "gt_mapkit": {"status": "pending", "done": 0, "total": 0},
            },
        })
        self.assertEqual(out["pct"], 50.0)
        self.assertEqual(out["effective_done"], 2.5)

    def test_ingest_copy_maps_into_first_decile(self):
        out = server._normalize_progress(
            {"done": 50, "total": 100, "step": "copy"},
            job_step="ingest",
        )
        self.assertEqual(out["phase"], "ingest")
        self.assertEqual(out["pct"], 5.0)  # 50% of photo-copy → 5% overall

    def test_ingest_pipeline_maps_into_remaining_ninety(self):
        out = server._normalize_progress(
            {"done": 0, "total": 5, "step": "ingest_done"},
            job_step="ingest",
        )
        self.assertEqual(out["phase"], "pipeline")
        self.assertEqual(out["pct"], 10.0)  # pipeline at 0% → overall 10%

        mid = server._normalize_progress(
            {
                "done": 2.5,
                "total": 5,
                "step": "ocr_nearby",
                "substeps": {
                    "ocr": {"done": 1, "total": 1, "status": "done"},
                },
            },
            job_step="ingest",
        )
        # 50% of pipeline × 90 + 10 = 55
        self.assertEqual(mid["pct"], 55.0)

    def test_standalone_rerun_unchanged_scale(self):
        out = server._normalize_progress(
            {"done": 30, "total": 100, "step": "searching nearby POIs"},
            job_step="mapkit_nearby",
        )
        self.assertEqual(out["pct"], 30.0)
        self.assertNotIn("phase", out)


class PipelineProgressPayloadTests(unittest.TestCase):
    def test_leaf_weights_are_equal(self):
        sequence = ["exif", "geocode", "ocr", "mapkit_nearby", "gt_mapkit"]
        payload = server._pipeline_progress_payload(
            sequence,
            finished={"exif", "geocode"},
            live={
                "ocr": {"done": 50, "total": 100, "status": "running"},
                "mapkit_nearby": {"done": 0, "total": 100, "status": "running"},
            },
            step_label="ocr_nearby",
        )
        # 1 + 1 + 0.5 + 0 + 0 = 2.5 of 5
        self.assertEqual(payload["done"], 2.5)
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["pct"], 50.0)
        self.assertEqual(payload["step"], "ocr_nearby")

    def test_all_finished(self):
        sequence = ["exif", "geocode"]
        payload = server._pipeline_progress_payload(
            sequence, finished={"exif", "geocode"}, live={}, step_label="pipeline")
        self.assertEqual(payload["done"], 2.0)
        self.assertEqual(payload["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
