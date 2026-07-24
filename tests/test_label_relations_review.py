#!/usr/bin/env python3
"""Unit tests for eval_label_relations upsert / remove (canonical credit UI)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import match_score as ms  # noqa: E402


class LabelRelationsReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "eval_label_relations.v1.jsonl")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_alias_then_remove(self) -> None:
        rec = ms.upsert_label_alias(
            dataset="demo",
            photo="a.jpg",
            alias="Place Alias",
            gt_canonical_name="Place",
            path=self.path,
        )
        self.assertIn("Place Alias", rec["accepted_aliases"])
        loaded = ms.load_label_relations(self.path)
        self.assertIn(("demo", "a.jpg", "mapkit"), loaded)

        m = ms.match_prediction(
            "Place",
            "Place Alias",
            dataset="demo",
            photo="a.jpg",
            provider="mapkit",
            mode="exact",
            relations=loaded,
        )
        self.assertFalse(m["correct_strict"])
        self.assertTrue(m["correct_canonical"])
        self.assertEqual(m["match_kind"], "alias")

        out = ms.remove_label_credit(
            dataset="demo",
            photo="a.jpg",
            name="Place Alias",
            kind="alias",
            path=self.path,
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["removed_alias"])
        loaded2 = ms.load_label_relations(self.path)
        self.assertEqual(loaded2, {})

    def test_upsert_related_credit(self) -> None:
        ms.upsert_label_related(
            dataset="demo",
            photo="b.jpg",
            name="Shop In Mall",
            relation="in_mall",
            credit=1.0,
            gt_canonical_name="The Mall",
            path=self.path,
        )
        loaded = ms.load_label_relations(self.path)
        m = ms.match_prediction(
            "The Mall",
            "Shop In Mall",
            dataset="demo",
            photo="b.jpg",
            provider="mapkit",
            mode="exact",
            relations=loaded,
        )
        self.assertTrue(m["correct_canonical"])
        self.assertEqual(m["match_kind"], "related_credit")

        out = ms.remove_label_credit(
            dataset="demo",
            photo="b.jpg",
            name="Shop In Mall",
            kind="related",
            path=self.path,
        )
        self.assertTrue(out["removed_related"])
        loaded2 = ms.load_label_relations(self.path)
        self.assertEqual(loaded2, {})

    def test_alias_idempotent(self) -> None:
        ms.upsert_label_alias(
            dataset="d", photo="p.jpg", alias="A", gt_canonical_name="G", path=self.path
        )
        ms.upsert_label_alias(
            dataset="d", photo="p.jpg", alias="A", gt_canonical_name="G", path=self.path
        )
        rec = ms.get_label_relation_record("d", "p.jpg", path=self.path)
        self.assertEqual(rec["accepted_aliases"].count("A"), 1)


if __name__ == "__main__":
    unittest.main()
