#!/usr/bin/env python3
"""Unit tests for tools/file_ops atomic writes and locks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from file_ops import atomic_write_json, atomic_write_text, file_lock  # noqa: E402


class FileOpsTests(unittest.TestCase):
    def test_atomic_write_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            atomic_write_json(path, {"a": 1, "b": "x"})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"a": 1, "b": "x"})

    def test_atomic_write_text_creates_parent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "f.txt")
            atomic_write_text(path, "hello\n")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello\n")

    def test_file_lock_serializes_writers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "counter.txt")
            lock_key = os.path.join(d, "shared")
            atomic_write_text(path, "0")
            errors: list = []

            def bump():
                try:
                    with file_lock(lock_key):
                        with open(path, encoding="utf-8") as f:
                            n = int(f.read().strip() or "0")
                        atomic_write_text(path, str(n + 1))
                except Exception as e:  # pragma: no cover
                    errors.append(e)

            threads = [threading.Thread(target=bump) for _ in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(int(f.read().strip()), 12)


if __name__ == "__main__":
    unittest.main()
