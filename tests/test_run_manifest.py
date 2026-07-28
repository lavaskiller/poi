#!/usr/bin/env python3
"""Unit tests for the full-lineage run manifest collector."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import run_manifest as rm  # noqa: E402


class Sha256FileTests(unittest.TestCase):
    def test_matches_hashlib(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"hello world\n")
            path = f.name
        try:
            self.assertEqual(
                rm.sha256_file(path),
                hashlib.sha256(b"hello world\n").hexdigest(),
            )
        finally:
            os.unlink(path)

    def test_missing_returns_none(self):
        self.assertIsNone(rm.sha256_file("/no/such/file/here"))
        self.assertIsNone(rm.sha256_file(""))

    def test_max_bytes_prefix_tagged(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"0123456789")
            path = f.name
        try:
            got = rm.sha256_file(path, max_bytes=4)
            self.assertTrue(got.startswith("prefix:"))
            self.assertEqual(
                got, "prefix:" + hashlib.sha256(b"0123").hexdigest()
            )
        finally:
            os.unlink(path)


class InputDigestsTests(unittest.TestCase):
    def test_missing_marked_not_dropped(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"x")
            present = f.name
        try:
            out = rm.input_digests({"a": present, "b": "/nope"})
            self.assertEqual(out["a"], hashlib.sha256(b"x").hexdigest())
            self.assertEqual(out["b"], "<missing>")
        finally:
            os.unlink(present)


class ModelProvenanceTests(unittest.TestCase):
    def test_reads_pin_file(self):
        with tempfile.TemporaryDirectory() as d:
            lock = os.path.join(d, "fastvlm.lock.json")
            with open(lock, "w", encoding="utf-8") as f:
                json.dump({
                    "fastvlm_commit": "abc123",
                    "torch": "2.2.0",
                    "checkpoint": "fastvlm-1.5b",
                    "checkpoint_sha256": "deadbeef",
                }, f)
            info = rm.model_provenance(lock)
            self.assertEqual(info["pinned"]["fastvlm_commit"], "abc123")
            self.assertEqual(info["pinned"]["torch"], "2.2.0")

    def test_missing_pin_is_none(self):
        info = rm.model_provenance("/no/such/lock.json")
        self.assertIsNone(info["pinned"])


class BuildTests(unittest.TestCase):
    def test_has_all_sections(self):
        m = rm.build(input_paths={})
        for key in ("schema", "code", "runtime", "model", "prompt", "cache",
                    "deps", "inputs"):
            self.assertIn(key, m)
        self.assertEqual(m["schema"], rm.SCHEMA_VERSION)

    def test_never_raises_on_bad_inputs(self):
        # Non-string path values must not crash the collector.
        m = rm.build(input_paths={"bad": None})  # type: ignore[dict-item]
        self.assertEqual(m["schema"], rm.SCHEMA_VERSION)

    def test_git_provenance_shape(self):
        prov = rm.git_provenance()
        self.assertIn("sha", prov)
        self.assertIn("dirty", prov)
        # Inside this repo the SHA resolves to a 40-char hex string.
        if prov["sha"] is not None:
            self.assertRegex(prov["sha"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
