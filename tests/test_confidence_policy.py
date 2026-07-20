import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "poi_confidence_policy", ROOT / "examples" / "poi_confidence_policy.py"
)
policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(policy)


def candidate(name, distance, place_id, category="restaurant"):
    return {
        "name": name, "distance_m": distance, "provider_place_id": place_id,
        "category": category,
    }


class ConfidencePolicyTests(unittest.TestCase):
    def test_no_usable_candidates_returns_none(self):
        result = policy.decide({"nearby_candidates": [{"name": "Parking Garage", "category": "parking"}]})
        self.assertEqual(result["action"], policy.NONE)
        self.assertEqual(result["reason_codes"], ["NO_USABLE_CANDIDATES"])

    def test_direct_tap_id_autopicks_tapped_candidate(self):
        result = policy.decide({
            "direct_tap_provider_id": "b",
            "nearby_candidates": [candidate("Alpha", 10, "a"), candidate("Beta", 20, "b")],
        })
        self.assertEqual(result["action"], policy.AUTO_PICK)
        self.assertEqual(result["selected"]["name"], "Beta")
        self.assertIn("DIRECT_TAP_PROVIDER_ID", result["reason_codes"])

    def test_single_candidate_without_evidence_opens_picker(self):
        result = policy.decide({"nearby_candidates": [candidate("Cafe Luna", 10, "a", "cafe")]})
        self.assertEqual(result["action"], policy.SHOW_PICKER)
        self.assertIn("SINGLE_CANDIDATE_UNCORROBORATED", result["reason_codes"])

    def test_single_candidate_with_full_ocr_name_autopicks(self):
        result = policy.decide({
            "ocr_text": "Welcome to Cafe Luna", "nearby_candidates": [candidate("Cafe Luna", 10, "a", "cafe")],
        })
        self.assertEqual(result["action"], policy.AUTO_PICK)
        self.assertIn("OCR_NAME_SUPPORT", result["reason_codes"])

    def test_vlm_alone_never_autopicks(self):
        result = policy.decide({
            "vlm_prediction": "Cafe Luna", "vlm_decision": "vlm_agrees_nearest",
            "nearby_candidates": [candidate("Cafe Luna", 10, "a", "cafe")],
        })
        self.assertEqual(result["action"], policy.SHOW_PICKER)

    def test_large_margin_with_weighted_nearest_agreement_autopicks(self):
        result = policy.decide({
            "nearby_candidates": [
                candidate("Alpha Cafe", 10, "a", "cafe"),
                candidate("Beta Cafe", 100, "b", "cafe"),
            ]
        })
        self.assertEqual(result["action"], policy.AUTO_PICK)
        self.assertIn("WEIGHTED_NEAREST_AGREE", result["reason_codes"])
        self.assertIn("LARGE_MARGIN", result["reason_codes"])

    def test_ambiguous_margin_opens_picker(self):
        result = policy.decide({
            "nearby_candidates": [
                candidate("Alpha Cafe", 10, "a", "cafe"),
                candidate("Beta Cafe", 20, "b", "cafe"),
            ]
        })
        self.assertEqual(result["action"], policy.SHOW_PICKER)
        self.assertIn("AMBIGUOUS_MARGIN", result["reason_codes"])

    def test_ocr_rejects_generic_category_only_match(self):
        support = policy.ocr_name_support("Cafe", "A cafe is visible")
        self.assertFalse(support["supported"])


if __name__ == "__main__":
    unittest.main()
