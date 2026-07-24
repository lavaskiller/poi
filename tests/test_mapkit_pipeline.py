#!/usr/bin/env python3
"""Regression tests for probe TSV → algorithm candidate artifacts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import match_score as ms  # noqa: E402


class MapKitCandidatePipelineTests(unittest.TestCase):
    def _write_tsv(self, root: str, rows: list[tuple[str, str, str]]) -> str:
        path = os.path.join(root, "rerun_mapkit_output.tsv")
        with open(path, "w", encoding="utf-8") as out:
            out.write("photo\twide_n\ttop3_wide\twide_candidates_json\n")
            for photo, top3, candidates_json in rows:
                count = len(json.loads(candidates_json))
                out.write(f"{photo}\t{count}\t{top3}\t{candidates_json}\n")
        return path

    def _read_jsonl(self, path: str) -> list[dict]:
        with open(path, encoding="utf-8") as src:
            return [json.loads(line) for line in src if line.strip()]

    def test_parses_full_candidates_and_empty_success_sentinel(self):
        with tempfile.TemporaryDirectory() as root:
            candidates = json.dumps([
                {"name": "Cafe A", "rank": 1, "distance_m": 12.5},
                {"name": "Cafe B", "rank": 2, "distance_m": 20},
            ], separators=(",", ":"))
            tsv = self._write_tsv(root, [
                ("alpha/1.jpg", "Cafe A@12.5m | Cafe B@20m", candidates),
                ("alpha/2.jpg", "", "[]"),
            ])

            records = ms.parse_mapkit_tsv_records(tsv)

            self.assertEqual([r.get("name") for r in records[:2]], ["Cafe A", "Cafe B"])
            self.assertEqual(records[2]["photo"], "alpha/2.jpg")
            self.assertEqual(records[2]["candidate_artifact_status"], "empty")
            loaded_path = os.path.join(root, "mapkit_candidates.jsonl")
            ms.convert_mapkit_tsv(tsv, loaded_path)
            loaded = ms.load_candidates([loaded_path])
            self.assertIn(("mapkit", "alpha/2.jpg"), loaded)
            self.assertEqual(loaded[("mapkit", "alpha/2.jpg")], [])

    def test_upsert_replaces_touched_photo_and_preserves_other_datasets(self):
        with tempfile.TemporaryDirectory() as root:
            artifact = os.path.join(root, "generated", "mapkit_candidates.jsonl")
            os.makedirs(os.path.dirname(artifact))
            with open(artifact, "w", encoding="utf-8") as out:
                out.write(json.dumps({"photo": "alpha/1.jpg", "provider": "mapkit", "name": "Old"}) + "\n")
                out.write(json.dumps({"photo": "beta/1.jpg", "provider": "mapkit", "name": "Keep"}) + "\n")
            updated = json.dumps([{"name": "New", "rank": 1}], separators=(",", ":"))
            tsv = self._write_tsv(root, [("alpha/1.jpg", "New@1m", updated)])

            written = ms.upsert_mapkit_candidates_from_tsv(tsv, artifact)
            records = self._read_jsonl(artifact)

            self.assertEqual(written, 1)
            self.assertEqual({r["photo"] for r in records}, {"alpha/1.jpg", "beta/1.jpg"})
            self.assertEqual(next(r for r in records if r["photo"] == "alpha/1.jpg")["name"], "New")
            self.assertEqual(next(r for r in records if r["photo"] == "beta/1.jpg")["name"], "Keep")

    def test_legacy_top3_requires_explicit_lossy_opt_in(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "legacy.tsv")
            with open(path, "w", encoding="utf-8") as out:
                out.write("photo\ttop3_wide\nalpha/1.jpg\tCafe A@10m | Cafe B@20m\n")

            with self.assertRaisesRegex(ValueError, "legacy top3-only"):
                ms.parse_mapkit_tsv_records(path)
            records = ms.parse_mapkit_tsv_records(path, allow_lossy_top3=True)
            self.assertEqual([r["name"] for r in records], ["Cafe A", "Cafe B"])
            self.assertTrue(all(r["lossy_top3_summary"] for r in records))

    def test_malformed_full_candidate_json_is_not_treated_as_empty_success(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "bad.tsv")
            with open(path, "w", encoding="utf-8") as out:
                out.write("photo\twide_candidates_json\nalpha/1.jpg\t\n")

            with self.assertRaisesRegex(ValueError, "invalid candidate JSON"):
                ms.parse_mapkit_tsv_records(path)


if __name__ == "__main__":
    unittest.main()

class ActiveSnapshotPromoteTests(unittest.TestCase):
    def test_publish_probe_merges_and_activates(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            gen = Path(td) / "generated"
            snap = gen / "candidate-snapshots" / "old-snap"
            snap.mkdir(parents=True)
            art = snap / "mapkit_candidates.jsonl"
            art.write_text(
                json.dumps(
                    {
                        "dataset": "vancouver",
                        "photo": "a.jpg",
                        "provider": "mapkit",
                        "name": "Old Place",
                        "rank": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(art.read_bytes()).hexdigest()
            (snap / "metadata.json").write_text(
                json.dumps(
                    {
                        "snapshot_id": "old-snap",
                        "status": "complete",
                        "candidate_artifact": "mapkit_candidates.jsonl",
                        "candidate_artifact_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (gen / "active-mapkit-candidate-snapshot.json").write_text(
                json.dumps(
                    {
                        "snapshot_id": "old-snap",
                        "candidate_artifact": "mapkit_candidates.jsonl",
                    }
                ),
                encoding="utf-8",
            )
            tsv = Path(td) / "probe.tsv"
            cands = json.dumps([{"name": "New Cafe", "rank": 1, "distance_m": 10}])
            tsv.write_text(
                "photo\twide_n\ttop3_wide\twide_candidates_json\n"
                f"union-city/new.jpg\t1\tNew Cafe@10m\t{cands}\n",
                encoding="utf-8",
            )
            res = ms.publish_probe_tsv_as_active_snapshot(
                str(tsv), data_root=td, snapshot_id="merge-test"
            )
            self.assertTrue(res["ok"])
            active = ms.active_mapkit_candidate_file(td)
            loaded = ms.load_candidates([active])
            self.assertIn(("mapkit", "vancouver/a.jpg"), loaded)
            self.assertIn(("mapkit", "union-city/new.jpg"), loaded)
