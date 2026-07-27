#!/usr/bin/env python3
"""Confidence-gate payload + OCR strength contracts (docs/confidence-gate.md)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

POLICY_PATH = ROOT / "examples" / "poi_confidence_policy.py"
SPEC = importlib.util.spec_from_file_location("poi_confidence_policy", POLICY_PATH)
policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(policy)


def _ocr_strength(name: str, ocr_text: str) -> str:
    info = policy.ocr_name_support(name, ocr_text)
    raw = info.get("strength") or "none"
    if raw == "full_name":
        return "full"
    if raw == "all_meaningful_tokens":
        return "tokens"
    return "none"


import scene_agreement as scene_mod  # noqa: E402


class SceneAgreementTests(unittest.TestCase):
    """Photo scene ↔ pick agreement (a-priori gate signal, never GT)."""

    def test_category_match(self):
        # restaurant pick + food/restaurant scene → strong agreement
        a = scene_mod.scene_agreement(
            "restaurant:0.9|food:0.8", pick_category="restaurant", pick_name="Mai's Kitchen"
        )
        self.assertGreater(a, 0.5)

    def test_name_cue_is_weaker_than_category(self):
        cat = scene_mod.scene_agreement("cafe:0.9", pick_category="cafe", pick_name="X")
        name = scene_mod.scene_agreement("cafe:0.9", pick_category="", pick_name="Blue Coffee")
        self.assertGreater(cat, name)
        self.assertGreater(name, 0.0)

    def test_no_scene_or_no_pick_is_zero(self):
        self.assertEqual(scene_mod.scene_agreement("", pick_category="restaurant"), 0.0)
        self.assertEqual(scene_mod.scene_agreement("restaurant:0.9", pick_category="", pick_name=""), 0.0)

    def test_agreement_clamped_unit_interval(self):
        a = scene_mod.scene_agreement("restaurant:1.0", pick_category="restaurant", pick_name="Grill")
        self.assertGreaterEqual(a, 0.0)
        self.assertLessEqual(a, 1.0)

    def test_low_confidence_scene_ignored(self):
        # Below min_conf → no agreement.
        a = scene_mod.scene_agreement("restaurant:0.05", pick_category="restaurant", min_conf=0.12)
        self.assertEqual(a, 0.0)

    def test_parse_scene_labels(self):
        pairs = scene_mod.parse_scene_labels("outdoor:0.96|sky:0.88")
        self.assertEqual(pairs[0][0], "outdoor")
        self.assertAlmostEqual(pairs[0][1], 0.96, places=2)


class OcrStrengthTests(unittest.TestCase):
    def test_full_name_substring(self):
        self.assertEqual(
            _ocr_strength("Blue Bottle Coffee", "Welcome to Blue Bottle Coffee today"),
            "full",
        )

    def test_all_meaningful_tokens(self):
        # Tokens present but not as contiguous full name → tokens.
        self.assertEqual(
            _ocr_strength("Blue Bottle", "Bottle shop Blue roasted"),
            "tokens",
        )

    def test_generic_only_is_not_support(self):
        self.assertEqual(_ocr_strength("Cafe", "best Cafe nearby"), "none")
        self.assertFalse(policy.ocr_name_support("Cafe", "best Cafe nearby")["supported"])

    def test_generic_name_flag(self):
        self.assertFalse(policy._meaningful_name_tokens("Cafe"))
        self.assertTrue(policy._meaningful_name_tokens("Blue Bottle"))


@unittest.skipUnless(
    (ROOT / "poi-data" / "eval_set_reconciled.csv").is_file()
    and (ROOT / "poi-data" / "generated" / "mapkit_candidates.jsonl").is_file(),
    "local poi-data + MapKit candidates required",
)
class BuildConfidenceSimTests(unittest.TestCase):
    def test_payload_fields(self):
        import server

        report = server.build_confidence_sim("all")
        self.assertGreater(report["n"], 0)
        case = report["cases"][0]
        for key in (
            "ocr_strength",
            "ocr_supported",
            "generic_name",
            "app_poi_dist_m",
            "spatial_agreement",
            "spatial_conflict",
            "single_candidate",
            "cand_dists",
            "vlm_support",
            "margin_m",
            "correct",
            "correct_exact",
            "correct_relations",
            "match_kind",
            "scene_top1",
            "scene_agreement",
            "scene_conflict",
        ):
            self.assertIn(key, case)
        self.assertIn(case["ocr_strength"], ("full", "tokens", "none"))
        # scene_agreement is an a-priori [0,1] additive input (never GT).
        for c in report["cases"]:
            self.assertGreaterEqual(c["scene_agreement"], 0.0)
            self.assertLessEqual(c["scene_agreement"], 1.0)
        self.assertIn("signals", report)
        sig = report["signals"]
        self.assertEqual(sig["n"], report["n"])
        self.assertEqual(
            sig["ocr_full"] + sig["ocr_tokens"] + sig["ocr_none"],
            report["n"],
        )
        # correct back-compat default is exact
        for c in report["cases"]:
            self.assertEqual(c["correct"], c["correct_exact"])
            # relations is a superset of exact (canonical credit never revokes exact)
            if c["correct_exact"]:
                self.assertTrue(c["correct_relations"])


if __name__ == "__main__":
    unittest.main()
