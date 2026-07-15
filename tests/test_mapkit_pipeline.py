import csv
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import match_score  # noqa: E402
import run_algorithm  # noqa: E402


class MapKitPipelineTests(unittest.TestCase):
    def test_rich_probe_tsv_preserves_candidate_metadata(self):
        candidates = [
            {
                "name": "City Museum",
                "category": "MKPOICategoryMuseum",
                "provider_place_id": "mapkit-id",
                "rank": 1,
                "distance_m": 5.5,
                "lat": 1.25,
                "lon": 2.5,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "probe.tsv"
            output = pathlib.Path(directory) / "candidates.jsonl"
            with source.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["photo", "top3_wide", "wide_candidates_json"],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "photo": "photo.jpg",
                        "top3_wide": "",
                        "wide_candidates_json": json.dumps(candidates),
                    }
                )

            count = match_score.convert_mapkit_tsv(str(source), str(output))
            record = json.loads(output.read_text(encoding="utf-8").strip())

        self.assertEqual(count, 1)
        self.assertEqual(record["category"], "MKPOICategoryMuseum")
        self.assertEqual(record["provider_place_id"], "mapkit-id")
        self.assertEqual(record["lat"], 1.25)
        self.assertEqual(record["distance_m"], 5.5)

    def test_legacy_top3_probe_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "legacy.tsv"
            output = pathlib.Path(directory) / "candidates.jsonl"
            with source.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(
                    file, fieldnames=["photo", "top3_wide"], delimiter="\t"
                )
                writer.writeheader()
                writer.writerow(
                    {"photo": "photo.jpg", "top3_wide": "Alpha@3m | Beta@14m"}
                )

            count = match_score.convert_mapkit_tsv(str(source), str(output))
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(count, 2)
        self.assertEqual(records[0]["name"], "Alpha")
        self.assertEqual(records[0]["distance_m"], 3.0)
        self.assertEqual(records[0]["category"], "")
        self.assertIsNone(records[0]["provider_place_id"])

    def test_harness_passes_metadata(self):
        source = {
            ("mapkit", "photo.jpg"): [
                {
                    "name": "City Museum",
                    "rank": 1,
                    "distance_m": 5.5,
                    "category": "MKPOICategoryMuseum",
                    "provider_place_id": "mapkit-id",
                    "lat": 1.25,
                    "lon": 2.5,
                }
            ]
        }
        candidates = run_algorithm._candidate_names(source, "mapkit", "photo.jpg", {})
        self.assertEqual(candidates[0]["category"], "MKPOICategoryMuseum")
        self.assertEqual(candidates[0]["provider_place_id"], "mapkit-id")
        self.assertEqual(candidates[0]["lat"], 1.25)

    def test_subprocess_timeout_is_optional_and_enforced_when_set(self):
        with tempfile.TemporaryDirectory() as directory:
            script = pathlib.Path(directory) / "slow.py"
            script.write_text(
                "import time\n"
                "def predict(case):\n"
                "    time.sleep(0.15)\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )
            cases = [{"input": {}, "_gt": "", "_dataset": "test", "_photo": "x"}]
            original_timeout = run_algorithm.RUN_TIMEOUT_S
            try:
                run_algorithm.RUN_TIMEOUT_S = None
                predictions = run_algorithm._run_subprocess(str(script), "python", cases)
                self.assertEqual(predictions[0]["prediction"], "ok")

                run_algorithm.RUN_TIMEOUT_S = 0.03
                with self.assertRaisesRegex(run_algorithm.RunError, "0.03s"):
                    run_algorithm._run_subprocess(str(script), "python", cases)
            finally:
                run_algorithm.RUN_TIMEOUT_S = original_timeout


if __name__ == "__main__":
    unittest.main()
