import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mapkit_weighted", ROOT / "examples" / "mapkit_weighted.py"
)
algorithm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(algorithm)


class MapKitWeightedTests(unittest.TestCase):
    def test_category_filter_dedupe_penalty_and_ambiguity(self):
        case = {
            "nearby_candidates": [
                {
                    "name": "Central Parking Garage",
                    "distance_m": 2,
                    "category": "MKPOICategoryParking",
                    "provider_place_id": "parking",
                },
                {
                    "name": "Museum Entrance",
                    "distance_m": 8,
                    "category": "MKPOICategoryMuseum",
                    "provider_place_id": "entrance",
                },
                {
                    "name": "City Museum",
                    "distance_m": 20,
                    "category": "MKPOICategoryMuseum",
                    "provider_place_id": "museum",
                },
                {
                    "name": "Coffee Shop",
                    "distance_m": 8,
                    "category": "MKPOICategoryCafe",
                    "provider_place_id": "cafe",
                },
                {
                    "name": "Duplicate museum result",
                    "distance_m": 25,
                    "category": "museum",
                    "provider_place_id": "museum",
                },
            ]
        }

        result = algorithm.resolve(case)

        self.assertEqual(result["selected"]["name"], "City Museum")
        self.assertEqual(result["decision"], "ambiguous")
        self.assertNotIn(
            "Central Parking Garage", [item["name"] for item in result["candidates"]]
        )
        self.assertEqual(
            1,
            sum(
                item.get("provider_place_id") == "museum"
                for item in result["candidates"]
            ),
        )
        entrance = next(
            item for item in result["candidates"] if item["name"] == "Museum Entrance"
        )
        self.assertTrue(entrance["is_access_point"])
        self.assertEqual(entrance["auxiliary_multiplier"], 3.0)

    def test_legacy_candidates_remain_supported(self):
        result = algorithm.resolve(
            {"nearby_candidates": [{"name": "Alpha", "rank": 1}, {"name": "Beta", "rank": 2}]}
        )
        self.assertEqual(result["selected"]["name"], "Alpha")

    def test_predict_uses_scalar_protocol(self):
        prediction = algorithm.predict(
            {
                "nearby_candidates": [
                    {
                        "name": "City Museum",
                        "distance_m": 20,
                        "category": "MKPOICategoryMuseum",
                    }
                ]
            }
        )
        self.assertEqual(prediction["prediction"], "City Museum")
        self.assertIn("category=museum", prediction["reason"])


if __name__ == "__main__":
    unittest.main()
