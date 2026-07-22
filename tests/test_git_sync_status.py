#!/usr/bin/env python3
"""Unit tests for server.git_sync_status (mocked git, no network)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from unittest import mock


def _load_server_module():
    root = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(root, "server.py")
    tools = os.path.join(root, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("poi_server_git", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"POI_PORT": "18421"}, clear=False):
        spec.loader.exec_module(mod)
    return mod


def _cp(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class GitSyncStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server_module()

    def setUp(self):
        # Isolate cache between tests.
        self.srv._GIT_STATUS_CACHE["ts"] = 0.0
        self.srv._GIT_STATUS_CACHE["payload"] = None

    def test_skipped_via_env(self):
        with mock.patch.dict(os.environ, {"POI_SKIP_GIT_SYNC_CHECK": "1"}, clear=False):
            out = self.srv.git_sync_status(force_fetch=True)
        self.assertEqual(out["status"], "skipped")
        self.assertFalse(out["update_required"])
        self.assertTrue(out["ok"])

    def test_not_a_repo(self):
        with mock.patch.dict(os.environ, {"POI_SKIP_GIT_SYNC_CHECK": ""}, clear=False):
            with mock.patch.object(self.srv.os.path, "isdir", return_value=False), mock.patch.object(
                self.srv.os.path, "isfile", return_value=False
            ):
                out = self.srv.git_sync_status(force_fetch=True, now=1000.0)
        self.assertEqual(out["status"], "not_a_repo")
        self.assertFalse(out["update_required"])

    def test_behind_blocks(self):
        def fake_git(*args, timeout=10):
            cmd = list(args)
            if cmd[:2] == ["rev-parse", "HEAD"]:
                return _cp("aaa111\n")
            if cmd[:2] == ["rev-parse", "--short"]:
                return _cp("aaa111\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "HEAD":
                return _cp("main\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "@{u}":
                return _cp("origin/main\n")
            if cmd[:1] == ["fetch"]:
                return _cp()
            if cmd[:2] == ["rev-parse", "origin/main"]:
                return _cp("bbb222\n")
            if cmd[:2] == ["rev-list", "--count"] and cmd[2].startswith("HEAD.."):
                return _cp("3\n")
            if cmd[:2] == ["rev-list", "--count"] and cmd[2].startswith("origin/"):
                return _cp("0\n")
            return _cp(returncode=1, stderr="unexpected " + " ".join(cmd))

        with mock.patch.dict(os.environ, {"POI_SKIP_GIT_SYNC_CHECK": ""}, clear=False):
            with mock.patch.object(self.srv, "_git_run", side_effect=fake_git):
                with mock.patch.object(self.srv.os.path, "isdir", return_value=True):
                    out = self.srv.git_sync_status(force_fetch=True, now=2000.0)

        self.assertEqual(out["status"], "behind")
        self.assertTrue(out["update_required"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["behind"], 3)
        self.assertEqual(out["local_sha"], "aaa111")
        self.assertEqual(out["remote_sha"], "bbb222")
        self.assertTrue(out.get("commands"))

    def test_current_allows(self):
        def fake_git(*args, timeout=10):
            cmd = list(args)
            if cmd[:2] == ["rev-parse", "HEAD"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-parse", "--short"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "HEAD":
                return _cp("main\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "@{u}":
                return _cp("origin/main\n")
            if cmd[:1] == ["fetch"]:
                return _cp()
            if cmd[:2] == ["rev-parse", "origin/main"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-list", "--count"]:
                return _cp("0\n")
            return _cp(returncode=1, stderr="unexpected")

        with mock.patch.dict(os.environ, {"POI_SKIP_GIT_SYNC_CHECK": ""}, clear=False):
            with mock.patch.object(self.srv, "_git_run", side_effect=fake_git):
                with mock.patch.object(self.srv.os.path, "isdir", return_value=True):
                    out = self.srv.git_sync_status(force_fetch=True, now=3000.0)

        self.assertEqual(out["status"], "current")
        self.assertFalse(out["update_required"])
        self.assertTrue(out["ok"])

    def test_cache_hit_skips_refetch(self):
        calls = {"n": 0}

        def fake_git(*args, timeout=10):
            calls["n"] += 1
            cmd = list(args)
            if cmd[:2] == ["rev-parse", "HEAD"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-parse", "--short"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "HEAD":
                return _cp("main\n")
            if cmd[:2] == ["rev-parse", "--abbrev-ref"] and cmd[2] == "@{u}":
                return _cp("origin/main\n")
            if cmd[:1] == ["fetch"]:
                return _cp()
            if cmd[:2] == ["rev-parse", "origin/main"]:
                return _cp("abc\n")
            if cmd[:2] == ["rev-list", "--count"]:
                return _cp("0\n")
            return _cp(returncode=1)

        with mock.patch.dict(os.environ, {"POI_SKIP_GIT_SYNC_CHECK": ""}, clear=False):
            with mock.patch.object(self.srv, "_git_run", side_effect=fake_git):
                with mock.patch.object(self.srv.os.path, "isdir", return_value=True):
                    a = self.srv.git_sync_status(force_fetch=False, now=4000.0)
                    n1 = calls["n"]
                    b = self.srv.git_sync_status(force_fetch=False, now=4005.0)
                    n2 = calls["n"]

        self.assertEqual(a["status"], "current")
        self.assertEqual(b["status"], "current")
        self.assertEqual(n1, n2)  # second call served from cache


if __name__ == "__main__":
    unittest.main()
