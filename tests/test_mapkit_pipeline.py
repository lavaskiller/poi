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

    def test_legacy_top3_probe_is_rejected_by_default(self):
        # A top3-only probe never persisted the full candidate list; converting
        # it silently caps candidates at 3 and drops the ground truth whenever
        # MapKit ranked it 4+. That must not become a scored artifact by accident.
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

            with self.assertRaises(ValueError):
                match_score.convert_mapkit_tsv(str(source), str(output))
            self.assertFalse(output.exists())

    def test_legacy_top3_probe_converts_only_when_explicitly_marked_lossy(self):
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

            count = match_score.convert_mapkit_tsv(
                str(source), str(output), allow_lossy_top3=True
            )
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(count, 2)
        self.assertEqual(records[0]["name"], "Alpha")
        self.assertEqual(records[0]["distance_m"], 3.0)
        self.assertEqual(records[0]["category"], "")
        self.assertIsNone(records[0]["provider_place_id"])
        # Every lossy record is stamped so a scored run can refuse it.
        self.assertTrue(all(r.get("lossy_top3_summary") for r in records))

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

    def test_missing_artifact_is_not_synthesized_from_csv_top1(self):
        self.assertEqual(
            run_algorithm._candidate_names(
                {}, "mapkit", "photo.jpg", {"app_nearby_top1": "Invented@3m"}, "dataset"
            ),
            [],
        )
        with self.assertRaisesRegex(run_algorithm.RunError, "artifact unavailable"):
            run_algorithm.build_cases(
                [{"dataset": "dataset", "photo": "photo.jpg", "country": "Canada",
                  "gt_mapkit": "Expected", "gt_confidence": "confirmed_user",
                  "app_nearby_top1": "Invented@3m"}],
                {"confidence_rollup": {"confirmed_user": "user_selected"}}, {}, "all",
                ["nearby_candidates"], 5,
            )

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
                predictions, duration_ms = run_algorithm._run_subprocess(str(script), "python", cases)
                self.assertEqual(predictions[0]["prediction"], "ok")
                self.assertIsInstance(duration_ms, float)
                self.assertGreater(duration_ms, 0)
                self.assertIn("latency_ms", predictions[0])
                self.assertIsInstance(predictions[0]["latency_ms"], (int, float))

                run_algorithm.RUN_TIMEOUT_S = 0.03
                with self.assertRaisesRegex(run_algorithm.RunError, "0.03s"):
                    run_algorithm._run_subprocess(str(script), "python", cases)
            finally:
                run_algorithm.RUN_TIMEOUT_S = original_timeout


if __name__ == "__main__":
    unittest.main()
