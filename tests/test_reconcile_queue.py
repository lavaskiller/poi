#!/usr/bin/env python3
"""Dataset filtering and progress counts for the reconcile queue."""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
from unittest import mock

import server


class ReconcileQueueDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.tmp.name, "eval_set_reconciled.csv")
        fields = ["dataset", "photo", "gt_mapkit", "input_place_name", "capture_lat", "capture_lon"]
        with open(self.csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows([
                {"dataset": "alpha", "photo": "a1.jpg", "gt_mapkit": "NON_MAPKIT"},
                {"dataset": "alpha", "photo": "a2.jpg", "gt_mapkit": "NON_MAPKIT"},
                {"dataset": "beta", "photo": "b1.jpg", "gt_mapkit": "NON_MAPKIT"},
                {"dataset": "beta", "photo": "ignored.jpg", "gt_mapkit": "Matched"},
                {"dataset": "", "photo": "unnamed.jpg", "gt_mapkit": "NON_MAPKIT"},
                {"dataset": "__all__", "photo": "reserved.jpg", "gt_mapkit": "NON_MAPKIT"},
            ])

    def tearDown(self):
        self.tmp.cleanup()

    def queue(self, dataset=None):
        with mock.patch.object(server, "CSV_PATH", self.csv_path), \
             mock.patch.object(server, "_load_gt_overrides", return_value={("alpha", "a1.jpg"): "Place"}), \
             mock.patch.object(server, "_load_original_mapkit_outputs", return_value={}):
            return server.gt_reconcile_queue(dataset=dataset)

    def test_all_datasets_includes_per_dataset_progress(self):
        result = self.queue()
        self.assertEqual((result["total_non_mapkit"], result["done"], result["remaining"]), (5, 1, 4))
        self.assertEqual(
            [case["dataset"] for case in result["cases"]],
            ["alpha", "beta", "", "__all__"],
        )
        self.assertEqual(result["datasets"], [
            {"name": "", "total": 1, "done": 0, "remaining": 1},
            {"name": "__all__", "total": 1, "done": 0, "remaining": 1},
            {"name": "alpha", "total": 2, "done": 1, "remaining": 1},
            {"name": "beta", "total": 1, "done": 0, "remaining": 1},
        ])

    def test_selected_dataset_limits_cases_and_counts(self):
        result = self.queue("beta")
        self.assertEqual(result["selected_dataset"], "beta")
        self.assertEqual((result["total_non_mapkit"], result["done"], result["remaining"]), (1, 0, 1))
        self.assertEqual([case["photo"] for case in result["cases"]], ["b1.jpg"])

    def test_unknown_dataset_is_an_empty_queue(self):
        result = self.queue("missing")
        self.assertEqual((result["total_non_mapkit"], result["done"], result["remaining"]), (0, 0, 0))
        self.assertEqual(result["cases"], [])

    def test_empty_and_reserved_dataset_names_can_be_selected(self):
        unnamed = self.queue("")
        self.assertEqual([case["photo"] for case in unnamed["cases"]], ["unnamed.jpg"])
        reserved = self.queue("__all__")
        self.assertEqual([case["photo"] for case in reserved["cases"]], ["reserved.jpg"])


if __name__ == "__main__":
    unittest.main()
