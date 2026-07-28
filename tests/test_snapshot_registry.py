#!/usr/bin/env python3
"""Unit tests for the candidate-snapshot registry + audited promotion."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import snapshot_registry as sr  # noqa: E402


def _make_snapshot(gen: str, sid: str, body: bytes = b'{"x":1}\n',
                   status: str = "complete", tamper: bool = False) -> None:
    sdir = os.path.join(gen, sr.SNAPSHOT_SUBDIR, sid)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, sr.ARTIFACT_NAME), "wb") as f:
        f.write(body)
    sha = hashlib.sha256(body).hexdigest()
    if tamper:
        sha = "0" * 64
    with open(os.path.join(sdir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({
            "snapshot_id": sid,
            "kind": "test_snapshot",
            "status": status,
            "candidate_artifact": sr.ARTIFACT_NAME,
            "candidate_artifact_sha256": sha,
            "candidate_records": 1,
        }, f)


class InspectTests(unittest.TestCase):
    def test_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-1")
            info = sr.inspect(d, "snap-1")
            self.assertTrue(info["valid"], info["reason"])

    def test_hash_mismatch_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-bad", tamper=True)
            info = sr.inspect(d, "snap-bad")
            self.assertFalse(info["valid"])
            self.assertIn("SHA-256", info["reason"])

    def test_incomplete_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-part", status="partial")
            info = sr.inspect(d, "snap-part")
            self.assertFalse(info["valid"])

    def test_missing_metadata_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            info = sr.inspect(d, "nope")
            self.assertFalse(info["valid"])


class RegisterTests(unittest.TestCase):
    def test_register_scans_and_skips_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "ok-1")
            _make_snapshot(d, "bad-1", tamper=True)
            res = sr.register(d)
            self.assertIn("ok-1", res["registered"])
            self.assertTrue(any(s["snapshot_id"] == "bad-1" for s in res["skipped"]))
            idx = sr.load_index(d)
            self.assertIn("ok-1", idx["snapshots"])
            self.assertNotIn("bad-1", idx["snapshots"])

    def test_register_idempotent_keeps_first_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "ok-1")
            sr.register(d, "ok-1")
            first = sr.load_index(d)["snapshots"]["ok-1"]["registered_at"]
            sr.register(d, "ok-1")
            second = sr.load_index(d)["snapshots"]["ok-1"]["registered_at"]
            self.assertEqual(first, second)


class PromoteTests(unittest.TestCase):
    def test_promote_writes_pointer_and_audit(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-1")
            res = sr.promote(d, "snap-1", "first activation", actor="tester")
            self.assertEqual(res["active"], "snap-1")
            self.assertIsNone(res["previous"])
            cur = sr.current(d)
            self.assertEqual(cur["active"], "snap-1")
            self.assertEqual(cur["candidate_artifact"], sr.ARTIFACT_NAME)
            hist = sr.history(d)
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["actor"], "tester")

    def test_promote_refuses_invalid_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "bad", tamper=True)
            with self.assertRaises(ValueError):
                sr.promote(d, "bad", "should fail")

    def test_promote_records_previous(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-1")
            _make_snapshot(d, "snap-2", body=b'{"y":2}\n')
            sr.promote(d, "snap-1", "v1")
            res = sr.promote(d, "snap-2", "v2")
            self.assertEqual(res["previous"], "snap-1")

    def test_rollback_restores_previous(self):
        with tempfile.TemporaryDirectory() as d:
            _make_snapshot(d, "snap-1")
            _make_snapshot(d, "snap-2", body=b'{"y":2}\n')
            sr.promote(d, "snap-1", "v1")
            sr.promote(d, "snap-2", "v2")
            sr.rollback(d, "bad candidates in v2")
            self.assertEqual(sr.current(d)["active"], "snap-1")
            # audit log has all three promotions
            self.assertEqual(len([h for h in sr.history(d)
                                  if h["action"] == "promote"]), 3)


if __name__ == "__main__":
    unittest.main()
