import hashlib
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_algorithm  # noqa: E402


class RunMetadataTests(unittest.TestCase):
    def test_evaluation_hash_supports_internal_and_persisted_cases(self):
        internal = [
            {"_dataset": "a", "_photo": "1.jpg", "_gt": "One", "input": {"ocr_text": "ignored"}},
            {"_dataset": "b", "_photo": "2.jpg", "_gt": "Two"},
        ]
        persisted = [
            {"dataset": "a", "photo": "1.jpg", "gt": "One", "prediction": "ignored"},
            {"dataset": "b", "photo": "2.jpg", "gt": "Two", "correct": True},
        ]
        self.assertEqual(
            run_algorithm.evaluation_set_sha256(internal),
            run_algorithm.evaluation_set_sha256(persisted),
        )

    def test_evaluation_hash_changes_with_order_or_label(self):
        cases = [
            {"dataset": "a", "photo": "1.jpg", "gt": "One"},
            {"dataset": "b", "photo": "2.jpg", "gt": "Two"},
        ]
        cohort_hash = run_algorithm.evaluation_set_sha256(cases)
        self.assertNotEqual(cohort_hash, run_algorithm.evaluation_set_sha256(list(reversed(cases))))
        changed = [dict(case) for case in cases]
        changed[0]["gt"] = "Changed"
        self.assertNotEqual(cohort_hash, run_algorithm.evaluation_set_sha256(changed))

    def test_data_snapshot_hash_is_deterministic_and_ordered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            first = root / "first.csv"
            second = root / "second.json"
            first.write_text("alpha", encoding="utf-8")
            second.write_text("beta", encoding="utf-8")
            paths = [str(first), str(second)]
            snapshot_hash = run_algorithm.data_snapshot_sha256(paths)
            self.assertEqual(snapshot_hash, run_algorithm.data_snapshot_sha256(paths))
            self.assertNotEqual(snapshot_hash, run_algorithm.data_snapshot_sha256(list(reversed(paths))))
            second.write_text("changed", encoding="utf-8")
            self.assertNotEqual(snapshot_hash, run_algorithm.data_snapshot_sha256(paths))

    def test_data_snapshot_hash_records_missing_optional_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            present = root / "present.csv"
            optional = root / "optional.jsonl"
            present.write_text("alpha", encoding="utf-8")
            missing_hash = run_algorithm.data_snapshot_sha256([str(present), str(optional)])
            self.assertEqual(
                missing_hash,
                run_algorithm.data_snapshot_sha256([str(present), str(optional)]),
            )
            optional.write_text("candidate", encoding="utf-8")
            self.assertNotEqual(
                missing_hash,
                run_algorithm.data_snapshot_sha256([str(present), str(optional)]),
            )

    def test_list_and_get_derive_legacy_cohort_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            cases = [{"dataset": "a", "photo": "1.jpg", "gt": "One", "prediction": "One", "correct": True}]
            record = {
                "name": "legacy",
                "safe_name": "legacy",
                "version": 1,
                "scope": "first-1",
                "mode": "exact",
                "metrics": {"n_eligible": 1, "correct": 1, "accuracy": 1.0, "accuracy_pct": 100},
                "cases": cases,
            }
            (root / "legacy__v1.json").write_text(json.dumps(record), encoding="utf-8")

            listed = run_algorithm.list_runs(str(root))[0]
            detailed = run_algorithm.get_run(str(root), "legacy", 1)
            expected = run_algorithm.evaluation_set_sha256(cases)

            self.assertEqual(listed["evaluation_set_sha256"], expected)
            self.assertTrue(listed["evaluation_set_sha256_derived"])
            self.assertIsNone(listed["data_snapshot_sha256"])
            self.assertEqual(detailed["evaluation_set_sha256"], expected)
            self.assertTrue(detailed["evaluation_set_sha256_derived"])

    def test_stored_cohort_identity_is_not_marked_derived(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            cohort_hash = hashlib.sha256(b"cohort").hexdigest()
            snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
            record = {
                "name": "current",
                "safe_name": "current",
                "version": 1,
                "evaluation_set_sha256": cohort_hash,
                "data_snapshot_sha256": snapshot_hash,
                "metrics": {},
                "cases": [],
            }
            (root / "current__v1.json").write_text(json.dumps(record), encoding="utf-8")

            listed = run_algorithm.list_runs(str(root))[0]
            detailed = run_algorithm.get_run(str(root), "current", 1)
            self.assertEqual(listed["evaluation_set_sha256"], cohort_hash)
            self.assertFalse(listed["evaluation_set_sha256_derived"])
            self.assertEqual(listed["data_snapshot_sha256"], snapshot_hash)
            self.assertFalse(detailed["evaluation_set_sha256_derived"])

    def test_host_runtime_metrics_on_score_and_list(self):
        preds = [
            {"prediction": "One", "error": None, "latency_ms": 10.0},
            {"prediction": "Two", "error": None, "latency_ms": 30.0},
            {"prediction": "", "error": "boom", "latency_ms": 5.0},
        ]
        cases = [
            {"_dataset": "a", "_photo": "1.jpg", "_gt": "One"},
            {"_dataset": "a", "_photo": "2.jpg", "_gt": "Two"},
            {"_dataset": "a", "_photo": "3.jpg", "_gt": "Three"},
        ]
        scored = run_algorithm._score(cases, preds, "exact")
        self.assertEqual(scored["correct"], 2)
        self.assertEqual(scored["latency_ms"]["n"], 3)
        self.assertEqual(scored["latency_ms"]["mean"], 15.0)
        self.assertEqual(scored["latency_ms"]["p50"], 10.0)
        self.assertEqual(scored["latency_ms"]["max"], 30.0)
        self.assertEqual(scored["cases"][0]["latency_ms"], 10.0)

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            record = {
                "name": "timed",
                "safe_name": "timed",
                "version": 1,
                "scope": "all",
                "mode": "exact",
                "metrics": {
                    "n_eligible": 3,
                    "correct": 2,
                    "accuracy": 2 / 3,
                    "accuracy_pct": 67,
                    "duration_ms": 42.5,
                    "latency_ms": scored["latency_ms"],
                    "runtime": {"device_class": "desktop_host", "notes": "host"},
                },
                "cases": scored["cases"],
            }
            (root / "timed__v1.json").write_text(json.dumps(record), encoding="utf-8")
            listed = run_algorithm.list_runs(str(root))[0]
            self.assertEqual(listed["duration_ms"], 42.5)
            self.assertEqual(listed["latency_ms"]["mean"], 15.0)
            self.assertEqual(listed["runtime"]["device_class"], "desktop_host")

    def test_host_runtime_info_marks_desktop_host(self):
        info = run_algorithm._host_runtime_info()
        self.assertEqual(info["device_class"], "desktop_host")
        self.assertIn("not mobile", info["notes"].lower())



if __name__ == "__main__":
    unittest.main()
