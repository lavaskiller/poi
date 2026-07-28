#!/usr/bin/env python3
"""Unit tests for the group-aware frozen eval split."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import eval_split as es  # noqa: E402


class GeocellAndGroupTests(unittest.TestCase):
    def test_geocell_rounds(self):
        self.assertEqual(es.geocell("37.123456", "127.987654"), "37.123,127.988")

    def test_geocell_bad_coords_none(self):
        self.assertIsNone(es.geocell("", ""))
        self.assertIsNone(es.geocell("abc", "1"))

    def test_group_clusters_same_place(self):
        a = {"dataset": "d", "username": "u", "capture_lat": "37.12341",
             "capture_lon": "127.12342", "photo": "a.jpg"}
        b = {"dataset": "d", "username": "u", "capture_lat": "37.12344",
             "capture_lon": "127.12339", "photo": "b.jpg"}
        # Same ~110m cell, user, and dataset → same group despite different photos.
        self.assertEqual(es.group_key(a), es.group_key(b))

    def test_group_falls_back_to_photo_without_gps(self):
        a = {"dataset": "d", "username": "u", "photo": "a.jpg"}
        b = {"dataset": "d", "username": "u", "photo": "b.jpg"}
        self.assertNotEqual(es.group_key(a), es.group_key(b))


class AssignSplitTests(unittest.TestCase):
    def test_deterministic_and_stable(self):
        g = "d|u|37.123,127.123"
        self.assertEqual(es.assign_split(g, es.DEFAULT_SALT, es.DEFAULT_RATIOS),
                         es.assign_split(g, es.DEFAULT_SALT, es.DEFAULT_RATIOS))

    def test_only_three_splits(self):
        for i in range(200):
            s = es.assign_split(f"g{i}", es.DEFAULT_SALT, es.DEFAULT_RATIOS)
            self.assertIn(s, ("train", "val", "test"))

    def test_salt_changes_assignment_distribution(self):
        groups = [f"g{i}" for i in range(500)]
        a = [es.assign_split(g, "salt-a", es.DEFAULT_RATIOS) for g in groups]
        b = [es.assign_split(g, "salt-b", es.DEFAULT_RATIOS) for g in groups]
        self.assertNotEqual(a, b)


class MembershipLeakTests(unittest.TestCase):
    def setUp(self):
        self._orig = es.ra.row_ineligibility
        es.ra.row_ineligibility = lambda row, cfg: None  # all eligible

    def tearDown(self):
        es.ra.row_ineligibility = self._orig

    def test_group_never_spans_splits(self):
        # Two photos sharing a place/session must land in the same split.
        rows = [
            {"dataset": "d", "username": "u", "capture_lat": "37.1234",
             "capture_lon": "127.1234", "photo": "a.jpg"},
            {"dataset": "d", "username": "u", "capture_lat": "37.1235",
             "capture_lon": "127.1234", "photo": "b.jpg"},
        ]
        mem = es.membership(rows, cfg={})
        self.assertEqual(mem[("d", "a.jpg")], mem[("d", "b.jpg")])

    def test_membership_covers_all_eligible(self):
        rows = [{"dataset": "d", "username": f"u{i}", "capture_lat": "37.1",
                 "capture_lon": "127.1", "photo": f"p{i}.jpg"} for i in range(20)]
        mem = es.membership(rows, cfg={})
        self.assertEqual(len(mem), 20)


if __name__ == "__main__":
    unittest.main()
