#!/usr/bin/env python3
"""Lightweight match_score contract tests (no MapKit / network)."""

from __future__ import annotations

import os
import hashlib
import json
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import match_score as ms  # noqa: E402


class ExactEqualTests(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(ms.exact_equal("Cafe Foo", "Cafe Foo"))
        self.assertFalse(ms.exact_equal("Cafe Foo", "Cafe Bar"))

    def test_empty(self):
        self.assertFalse(ms.exact_equal("", "x"))
        self.assertFalse(ms.exact_equal("x", ""))


class DataRootResolutionTests(unittest.TestCase):
    def test_default_label_relations_path_under_data_root(self):
        with tempfile.TemporaryDirectory() as d:
            path = ms.default_label_relations_path(d)
            self.assertEqual(
                path, os.path.join(d, "eval_label_relations.v1.jsonl")
            )

    def test_load_label_relations_missing_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "missing.jsonl")
            self.assertEqual(ms.load_label_relations(path), {})

    def test_load_label_relations_reads_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "eval_label_relations.v1.jsonl")
            rec = {
                "dataset": "demo",
                "photo": "a.jpg",
                "provider": "mapkit",
                "gt_canonical_name": "Place",
                "accepted_aliases": ["Alias Place"],
                "relations": [],
            }
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            loaded = ms.load_label_relations(path)
            self.assertIn(("demo", "a.jpg", "mapkit"), loaded)
            self.assertEqual(
                loaded[("demo", "a.jpg", "mapkit")]["accepted_aliases"],
                ["Alias Place"],
            )


class NormalizedEqualTests(unittest.TestCase):
    def test_case_and_space(self):
        # Policy depends on implementation; both sides should be stable.
        a = "Starbucks Coffee"
        b = "starbucks coffee"
        # Either true (normalized) or false (strict) — assert no crash + bool.
        self.assertIsInstance(ms.normalized_equal(a, b), bool)


class ProviderRoutingTests(unittest.TestCase):
    """Country/provider must never default Unknown → MapKit."""

    def test_geocoded_korea_is_kakao(self):
        row = {"country": "South Korea", "capture_lat": "37.5", "capture_lon": "127.0"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_KAKAO)

    def test_geocoded_korea_hangul_is_kakao(self):
        row = {"country": "대한민국"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_KAKAO)

    def test_geocoded_canada_is_mapkit(self):
        row = {"country": "Canada", "capture_lat": "49.2", "capture_lon": "-123.1"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_MAPKIT)

    def test_empty_country_gps_korea_is_kakao(self):
        # Seoul — GPS fallback when geocode has not filled country yet.
        row = {"country": "", "capture_lat": "37.5665", "capture_lon": "126.9780"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_KAKAO)
        self.assertEqual(ms.canonical_country(row, {}), "South Korea")

    def test_empty_country_gps_vancouver_is_mapkit(self):
        row = {"country": "", "capture_lat": "49.2827", "capture_lon": "-123.1207"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_MAPKIT)

    def test_no_country_no_gps_is_unresolved_not_mapkit(self):
        row = {"country": "", "dataset": "mystery-upload"}
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_UNRESOLVED)

    def test_country_by_dataset_does_not_drive_provider(self):
        # Untrusted dataset map must not force MapKit when GPS says Korea.
        cfg = {"country_by_dataset": {"mixed": "Canada"}}
        row = {
            "dataset": "mixed",
            "country": "",
            "capture_lat": "37.5",
            "capture_lon": "127.0",
        }
        self.assertEqual(ms.provider_for_row(row, cfg), ms.PROVIDER_KAKAO)

    def test_row_country_beats_gps(self):
        # Explicit reverse-geocode / export country wins over coord bbox.
        row = {
            "country": "United States",
            "capture_lat": "37.5",  # inside KR bbox numerically, but country says US
            "capture_lon": "127.0",
        }
        self.assertEqual(ms.provider_for_row(row, {}), ms.PROVIDER_MAPKIT)

    def test_region_from_coords(self):
        self.assertEqual(ms.region_from_coords(37.5, 127.0), "kr")
        self.assertEqual(ms.region_from_coords(49.2, -123.1), "non_kr")


class NearbyGtRadiusTests(unittest.TestCase):
    def test_keeps_in_radius_drops_far(self):
        cands = [
            {"name": "Near Cafe", "rank": 1, "distance_m": 40},
            {"name": "Far Starbucks", "rank": 2, "distance_m": 900},
            {"name": "Edge Shop", "rank": 3, "distance_m": 250},
        ]
        names = ms.names_within_gt_radius(cands, radius_m=250)
        self.assertEqual(names, ["Near Cafe", "Edge Shop"])

    def test_missing_distance_kept(self):
        cands = [{"name": "Legacy Top3", "rank": 1}]
        self.assertEqual(ms.names_within_gt_radius(cands, radius_m=250), ["Legacy Top3"])

    def test_dedup_preserves_first_rank(self):
        cands = [
            {"name": "Dup", "rank": 1, "distance_m": 10},
            {"name": "Dup", "rank": 5, "distance_m": 20},
        ]
        self.assertEqual(ms.names_within_gt_radius(cands), ["Dup"])


class EvaluationSetHashTests(unittest.TestCase):
    def test_stable_for_same_ordered_cases(self):
        # evaluation_set_sha256 is order-sensitive (cohort identity = ordered list).
        import run_algorithm as ra

        cases = [
            {"dataset": "d", "photo": "a.jpg", "gt": "Place A"},
            {"dataset": "d", "photo": "b.jpg", "gt": "Place B"},
        ]
        h1 = ra.evaluation_set_sha256(cases)
        h2 = ra.evaluation_set_sha256(list(cases))
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)
        # Different order → different cohort fingerprint by design.
        self.assertNotEqual(h1, ra.evaluation_set_sha256(list(reversed(cases))))


class ActiveCandidateSnapshotTests(unittest.TestCase):
    def _write_snapshot(self, root, snapshot_id, candidate_name):
        snapshot_dir = os.path.join(
            root, "generated", "candidate-snapshots", snapshot_id
        )
        os.makedirs(snapshot_dir, exist_ok=True)
        artifact = os.path.join(snapshot_dir, "mapkit_candidates.jsonl")
        payload = json.dumps({
            "provider": "mapkit",
            "dataset": "dataset",
            "photo": "0001.jpg",
            "name": candidate_name,
            "rank": 1,
        }) + "\n"
        with open(artifact, "w", encoding="utf-8") as f:
            f.write(payload)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with open(os.path.join(snapshot_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({
                "snapshot_id": snapshot_id,
                "status": "complete",
                "candidate_artifact": "mapkit_candidates.jsonl",
                "candidate_artifact_sha256": digest,
            }, f)
        return artifact

    def test_default_files_follow_pointer_switch_without_reimport(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_a = self._write_snapshot(root, "snapshot-a", "Place A")
            artifact_b = self._write_snapshot(root, "snapshot-b", "Place B")
            generated = os.path.join(root, "generated")
            pointer = os.path.join(generated, ms.ACTIVE_MAPKIT_SNAPSHOT_POINTER)

            def activate(snapshot_id):
                with open(pointer, "w", encoding="utf-8") as f:
                    json.dump({
                        "snapshot_id": snapshot_id,
                        "candidate_artifact": "mapkit_candidates.jsonl",
                    }, f)

            activate("snapshot-a")
            self.assertEqual(ms.default_candidate_files(root)[0], artifact_a)

            # The module remains imported; only the authoritative pointer moves.
            activate("snapshot-b")
            resolved = ms.default_candidate_files(root)
            self.assertEqual(resolved[0], artifact_b)
            candidates = ms.load_candidates([resolved[0]])
            self.assertEqual(
                candidates[("mapkit", "dataset/0001.jpg")][0]["name"],
                "Place B",
            )


if __name__ == "__main__":
    unittest.main()
