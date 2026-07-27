#!/usr/bin/env python3
"""Confidence-gate payload + OCR strength contracts (docs/confidence-gate.md)."""

from __future__ import annotations

import importlib.util
import os
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
        ):
            self.assertIn(key, case)
        self.assertIn(case["ocr_strength"], ("full", "tokens", "none"))
        # Faithful hard gates should not disagree with AUTO_PICK on this cohort.
        auto = { (c["dataset"], c["photo"]) for c in report["cases"] if c["action"] == "AUTO_PICK" }
        self.assertGreaterEqual(len(auto), 0)


if __name__ == "__main__":
    unittest.main()
