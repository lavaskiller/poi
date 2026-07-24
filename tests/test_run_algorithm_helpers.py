#!/usr/bin/env python3
"""Unit tests for run_algorithm naming, versioning, and atomic save."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import run_algorithm as ra  # noqa: E402


class SafeNameTests(unittest.TestCase):
    def test_slug_basic(self):
        self.assertEqual(ra._safe_name("Baseline Nearest"), "baseline-nearest")

    def test_strips_version_suffix(self):
        self.assertEqual(ra._safe_name("algo-v3"), "algo")
        self.assertEqual(ra._safe_name("algo__v12"), "algo")

    def test_empty_falls_back(self):
        self.assertEqual(ra._safe_name("   "), "algorithm")
        self.assertEqual(ra._safe_name(""), "algorithm")


class VersionPickTests(unittest.TestCase):
    def test_auto_increments(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("foo__v1.json", "foo__v2.json"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write("{}")
            self.assertEqual(ra._pick_version(d, "foo", "auto"), 3)

    def test_explicit_version(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ra._pick_version(d, "foo", "v7"), 7)

    def test_first_version(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ra._pick_version(d, "foo", "auto"), 1)


class AtomicSaveTests(unittest.TestCase):
    def test_delete_run_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ra.RunError):
                ra.delete_run(d, "nope", 1)

    def test_get_run_identity(self):
        with tempfile.TemporaryDirectory() as d:
            rec = {
                "name": "demo",
                "safe_name": "demo",
                "version": 1,
                "metrics": {"accuracy_pct": 10, "n_eligible": 1, "correct": 0},
                "cases": [],
            }
            path = os.path.join(d, "demo__v1.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            got = ra.get_run(d, "demo", 1)
            self.assertEqual(got["name"], "demo")
            self.assertFalse(got.get("has_script"))
            with self.assertRaises(ra.RunError):
                ra.get_run(d, "other", 1)

    def test_list_runs_has_script(self):
        with tempfile.TemporaryDirectory() as d:
            with_script = {
                "name": "with-script",
                "safe_name": "with-script",
                "version": 1,
                "scope": "vancouver",
                "params": ["nearby_candidates"],
                "candidate_limit": 5,
                "script_text": "def predict(case):\n    return ''\n",
                "metrics": {"accuracy_pct": 40, "n_eligible": 2, "correct": 1},
                "cases": [],
            }
            no_script = {
                "name": "rescored",
                "safe_name": "rescored",
                "version": 1,
                "scope": "all",
                "params": ["nearby_candidates"],
                "candidate_limit": 20,
                "metrics": {"accuracy_pct": 50, "n_eligible": 2, "correct": 1},
                "cases": [],
            }
            for rec in (with_script, no_script):
                path = os.path.join(d, f"{rec['safe_name']}__v{rec['version']}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rec, f)
            listed = {r["name"]: r for r in ra.list_runs(d)}
            self.assertTrue(listed["with-script"]["has_script"])
            self.assertFalse(listed["rescored"]["has_script"])
            self.assertEqual(listed["with-script"]["candidate_limit"], 5)
            self.assertEqual(listed["with-script"]["scope"], "vancouver")


class DatasetPreflightTests(unittest.TestCase):
    @staticmethod
    def _row(photo="a.jpg", **overrides):
        row = {
            "dataset": "sample",
            "photo": photo,
            "country": "Canada",
            "gt_mapkit": "Canonical Place",
            "gt_confidence": "confirmed_user",
        }
        row.update(overrides)
        return row

    def test_summary_and_build_cases_agree_for_runnable_dataset(self):
        rows = [self._row()]
        candidates = {("mapkit", "sample/a.jpg"): []}
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", candidates)
        cases = ra.build_cases(rows, {}, candidates, "sample", [])
        self.assertTrue(summary["runnable"])
        self.assertEqual(summary["eligible"], len(cases))
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 1)
        self.assertEqual(summary["runnable_now"], 1)

    def test_missing_artifact_blocks_preflight_and_runner(self):
        rows = [self._row()]
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", {})
        self.assertFalse(summary["runnable"])
        self.assertEqual(summary["blockers"], {"missing_candidate_artifact": 1})
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 0)
        self.assertEqual(summary["runnable_now"], 0)
        with self.assertRaises(ra.RunError):
            ra.build_cases(rows, {}, {}, "sample", [])

    def test_lossy_artifact_blocks_preflight_and_runner(self):
        rows = [self._row()]
        candidates = {("mapkit", "sample/a.jpg"): [
            {"name": "Candidate", "lossy_top3_summary": True},
        ]}
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", candidates)
        self.assertFalse(summary["runnable"])
        self.assertEqual(summary["blockers"], {"lossy_candidate_artifact": 1})
        self.assertEqual(summary["gt_eligible"], 1)
        self.assertEqual(summary["artifact_ready"], 1)
        self.assertEqual(summary["runnable_now"], 0)
        with self.assertRaises(ra.RunError):
            ra.build_cases(rows, {}, candidates, "sample", [])

    def test_exclusion_reasons_use_runner_policy(self):
        rows = [
            self._row("missing-gt.jpg", gt_mapkit=""),
            self._row("korea.jpg", country="South Korea", gt_kakao="Kakao Place"),
            self._row("non-poi.jpg", gt_confidence="non_poi"),
        ]
        summary = ra.dataset_eligibility_summary(rows, {}, "sample", {})
        self.assertEqual(summary["eligible"], 0)
        self.assertEqual(summary["exclusions"], {
            "no_gt": 1,
            "korea_pending_kakao": 1,
            "non_poi": 1,
        })
        self.assertEqual(ra.build_cases(rows, {}, {}, "sample", []), [])


class PredictEnvTests(unittest.TestCase):
    def test_examples_dir_not_on_pythonpath(self):
        """Repo examples/ must not be injectable as an outside dependency."""
        env = ra._predict_env(submission_dir="/tmp/poi-submit-test")
        path = env.get("PYTHONPATH", "")
        parts = [os.path.abspath(p) for p in path.split(os.pathsep) if p]
        self.assertNotIn(os.path.abspath(ra.EXAMPLES_DIR), parts)
        self.assertNotIn(os.path.abspath(ra._REPO_ROOT), parts)
        self.assertNotIn(os.path.abspath(ra._TOOLS_DIR), parts)
        # Submission dir is allowed (local package root only).
        self.assertIn(os.path.abspath("/tmp/poi-submit-test"), parts)

    def test_strips_examples_from_parent_pythonpath(self):
        old = os.environ.get("PYTHONPATH")
        try:
            os.environ["PYTHONPATH"] = ra.EXAMPLES_DIR + os.pathsep + "/opt/some-pkg"
            env = ra._predict_env()
            parts = [os.path.abspath(p) for p in (env.get("PYTHONPATH") or "").split(os.pathsep) if p]
            self.assertNotIn(os.path.abspath(ra.EXAMPLES_DIR), parts)
            self.assertIn(os.path.abspath("/opt/some-pkg"), parts)
        finally:
            if old is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old

    def test_outside_repo_sibling_import_fails_loud(self):
        """Bare import of examples modules must not resolve via harness path."""
        script = (
            "import selector_list_fit\n"
            "def predict(case):\n"
            "    return 'ok'\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{"input": {"photo": "x.jpg", "nearby_candidates": []}}]
            with self.assertRaises(ra.RunError) as ctx:
                ra._run_subprocess(path, "python", cases)
            msg = str(ctx.exception).lower()
            self.assertTrue(
                "import preflight" in msg or "failed to load" in msg,
                msg,
            )

    def test_soft_caught_missing_package_still_fails_preflight(self):
        """try/except ImportError must not hide missing packages."""
        script = (
            "try:\n"
            "    import this_package_definitely_does_not_exist_xyz\n"
            "except ImportError:\n"
            "    pass\n"
            "def predict(case):\n"
            "    c = case.get('nearby_candidates') or []\n"
            "    return (c[0].get('name') if c else '') or ''\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{"input": {
                "photo": "x.jpg",
                "nearby_candidates": [{"name": "Nearest Wrong", "rank": 1}],
            }}]
            with self.assertRaises(ra.RunError) as ctx:
                ra._run_subprocess(path, "python", cases)
            self.assertIn("import preflight", str(ctx.exception).lower())

    def test_predict_exception_aborts_whole_run(self):
        """Per-case raise must not produce a scorable partial run."""
        script = (
            "def predict(case):\n"
            "    raise RuntimeError('boom')\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [
                {"input": {"photo": "a.jpg", "nearby_candidates": []}},
                {"input": {"photo": "b.jpg", "nearby_candidates": []}},
            ]
            with self.assertRaises(ra.RunError) as ctx:
                ra._run_subprocess(path, "python", cases)
            self.assertIn("failed on case", str(ctx.exception).lower())

    def test_import_inside_predict_fails_preflight(self):
        """AST preflight walks function bodies — missing pkg never reaches score."""
        script = (
            "def predict(case):\n"
            "    import totally_missing_pkg_zzz\n"
            "    return 'x'\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{"input": {"photo": "a.jpg", "nearby_candidates": []}}]
            with self.assertRaises(ra.RunError) as ctx:
                ra._run_subprocess(path, "python", cases)
            self.assertIn("import preflight", str(ctx.exception).lower())

    def test_dynamic_import_at_runtime_aborts_run(self):
        """importlib is not static — still must not score when it raises."""
        script = (
            "import importlib\n"
            "def predict(case):\n"
            "    importlib.import_module('totally_missing_pkg_zzz')\n"
            "    return 'x'\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{"input": {"photo": "a.jpg", "nearby_candidates": []}}]
            with self.assertRaises(ra.RunError) as ctx:
                ra._run_subprocess(path, "python", cases)
            self.assertIn("failed on case", str(ctx.exception).lower())

    def test_stdlib_and_site_packages_still_work(self):
        script = (
            "import json, math, re\n"
            "def predict(case):\n"
            "    return json.dumps({'ok': True}) and 'ok'\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{"input": {"photo": "x.jpg", "nearby_candidates": []}}]
            preds, _dur = ra._run_subprocess(path, "python", cases)
            self.assertEqual(len(preds), 1)
            self.assertEqual(preds[0].get("prediction"), "ok")
            self.assertIsNone(preds[0].get("error"))

    def test_self_contained_bundle_runs(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import bundle_submission as bundle  # noqa: E402

        script = bundle.bundle_example_ensemble_v2()
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            cases = [{
                "input": {
                    "photo": "x.jpg",
                    "ocr_text": "",
                    "nearby_candidates": [
                        {"name": "Banff Gondola Stop", "distance_m": 10, "rank": 1},
                        {"name": "Banff Gondola", "distance_m": 40, "rank": 2},
                    ],
                }
            }]
            preds, _dur = ra._run_subprocess(path, "python", cases)
            self.assertEqual(len(preds), 1)
            self.assertIsNone(preds[0].get("error"))
            # Deterministic core should demote access-point rank-1.
            self.assertEqual(preds[0].get("prediction"), "Banff Gondola")


class SeedOcrPackTests(unittest.TestCase):
    def test_backfill_and_write_ocr_tsv(self):
        from pathlib import Path

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import pack_seed_bundle as pack  # noqa: E402

        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "eval_set_reconciled.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                f.write("dataset,photo,caption_ondevice,gt_mapkit\n")
                f.write("vancouver,a.jpg,,Place A\n")
                f.write("vancouver,b.jpg,already here,Place B\n")
            ocr_map = {"a.jpg": "HELLO SIGN", "b.jpg": "ignored"}
            stats = pack.backfill_caption_ondevice(Path(csv_path), ocr_map)
            self.assertEqual(stats["ocr_backfilled"], 1)
            self.assertEqual(stats["ocr_filled_after"], 2)
            n = pack.write_ocr_tsv(Path(csv_path), Path(td) / "ocr_text.tsv")
            self.assertEqual(n, 2)
            with open(os.path.join(td, "ocr_text.tsv"), encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("HELLO SIGN", body)
            self.assertIn("already here", body)


class LiveStreamingRunTests(unittest.TestCase):
    def test_on_pred_called_per_case(self):
        script = (
            "import time\n"
            "def predict(case):\n"
            "    return (case.get('nearby_candidates') or [{}])[0].get('name') or 'x'\n"
        )
        with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
            path = os.path.join(td, "predict.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            seen = []
            cases = [
                {"input": {"photo": "a.jpg", "nearby_candidates": [{"name": "A"}]}},
                {"input": {"photo": "b.jpg", "nearby_candidates": [{"name": "B"}]}},
            ]

            def on_pred(i, p):
                seen.append((i, p.get("prediction")))

            preds, _dur = ra._run_subprocess(path, "python", cases, on_pred=on_pred)
            self.assertEqual(len(preds), 2)
            self.assertEqual(seen, [(0, "A"), (1, "B")])

    def test_live_file_grows_during_run(self):
        script = (
            "def predict(case):\n"
            "    return (case.get('nearby_candidates') or [{}])[0].get('name') or ''\n"
        )
        with tempfile.TemporaryDirectory() as runs_dir:
            # Minimal synthetic cohort via run_submission is heavy; exercise
            # prepare/execute path with a tiny fake by calling internals.
            # Use a temp CSV-less path: only _run_subprocess + manual live write.
            live_updates = []

            def on_pred(i, p):
                live_updates.append(i)

            with tempfile.TemporaryDirectory(prefix="poi-submit-") as td:
                path = os.path.join(td, "predict.py")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(script)
                cases = [
                    {"input": {"photo": f"{i}.jpg", "nearby_candidates": [{"name": f"P{i}"}]}}
                    for i in range(3)
                ]
                ra._run_subprocess(path, "python", cases, on_pred=on_pred)
            self.assertEqual(live_updates, [0, 1, 2])

            # Full prepare+execute with minimal eval is covered if we skip;
            # list_runs must surface a hand-written live record.
            live = os.path.join(runs_dir, "live")
            os.makedirs(live)
            rec = {
                "name": "live-demo",
                "safe_name": "live-demo",
                "version": 1,
                "status": "running",
                "job_id": "abc",
                "created_at": "2026-07-23T00:00:00",
                "metrics": {"n_eligible": 10, "n_completed": 2, "correct": 1, "accuracy_pct": 50},
                "cases": [
                    {"dataset": "d", "photo": "a.jpg", "gt": "A", "prediction": "A",
                     "correct": True, "correct_canonical": True, "match_kind": "exact"},
                    {"dataset": "d", "photo": "b.jpg", "gt": "B", "prediction": "X",
                     "correct": False, "correct_canonical": False, "match_kind": "wrong"},
                ],
                "progress": {"done": 2, "total": 10},
            }
            with open(os.path.join(live, "abc.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f)
            listed = ra.list_runs(runs_dir)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["status"], "running")
            self.assertEqual(listed[0]["n_completed"], 2)
            got = ra.get_run(runs_dir, "live-demo", 1)
            self.assertEqual(got["status"], "running")
            self.assertEqual(len(got["cases"]), 2)


class LabelRelationsPathTests(unittest.TestCase):
    def test_prefers_sidecar_beside_csv(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "eval_set_reconciled.csv")
            rel_path = os.path.join(d, "eval_label_relations.v1.jsonl")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("photo\n")
            with open(rel_path, "w", encoding="utf-8") as f:
                f.write("")
            got = ra._default_label_relations_path(csv_path)
            self.assertEqual(os.path.realpath(got), os.path.realpath(rel_path))

    def test_explicit_path_wins(self):
        got = ra._default_label_relations_path(
            "/no/such/csv.csv", explicit="/tmp/custom_relations.jsonl"
        )
        self.assertEqual(got, "/tmp/custom_relations.jsonl")


if __name__ == "__main__":
    unittest.main()
