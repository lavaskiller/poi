#!/usr/bin/env python3
"""Guard the reproducible-runtime pins so they can't silently drift.

These are cheap static contracts, but they are exactly the ones that rot without
a test: the lock falling behind requirements.txt, the FastVLM pin losing its
schema, or the Dockerfile quietly installing the loose requirements instead of
the lock. See docs/reproducible-runtime.md.
"""

from __future__ import annotations

import json
import os
import re
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REQ_TXT = os.path.join(_REPO_ROOT, "requirements.txt")
_REQ_LOCK = os.path.join(_REPO_ROOT, "requirements.lock")
_FASTVLM_LOCK = os.path.join(_REPO_ROOT, "tools", "fastvlm.lock.json")
_DOCKERFILE = os.path.join(_REPO_ROOT, "Dockerfile")

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _canon(name: str) -> str:
    # PEP 503 normalization so Pillow / pillow / PIL-LOW compare equal.
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(path: str):
    names = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = _NAME_RE.match(line)
            if m:
                names.append(m.group(1))
    return names


def _locked_pins(path: str):
    """Map canonical name -> pinned version for every `name==version` line."""
    pins = {}
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", line)
            if m:
                pins[_canon(m.group(1))] = m.group(2)
    return pins


class RequirementsLockTests(unittest.TestCase):
    def test_lock_exists(self):
        self.assertTrue(os.path.isfile(_REQ_LOCK), "requirements.lock is missing")

    def test_every_top_level_dep_is_pinned(self):
        wanted = _requirement_names(_REQ_TXT)
        self.assertTrue(wanted, "requirements.txt declared no packages")
        pins = _locked_pins(_REQ_LOCK)
        for name in wanted:
            self.assertIn(
                _canon(name),
                pins,
                f"{name} is in requirements.txt but not pinned (==) in requirements.lock",
            )


class FastvlmPinTests(unittest.TestCase):
    def test_valid_schema_and_keys(self):
        with open(_FASTVLM_LOCK, "r", encoding="utf-8") as fh:
            pin = json.load(fh)
        self.assertEqual(pin.get("_schema"), "fastvlm-pin/v1")
        for key in ("fastvlm_commit", "torch", "checkpoint", "checkpoint_sha256"):
            self.assertIn(key, pin, f"fastvlm.lock.json missing key: {key}")


class DockerfileTests(unittest.TestCase):
    def test_installs_from_lock_not_loose_requirements(self):
        with open(_DOCKERFILE, "r", encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("requirements.lock", body)
        self.assertNotIn(
            "-r requirements.txt",
            body,
            "Dockerfile must install the pinned lock, not the loose requirements.txt",
        )


if __name__ == "__main__":
    unittest.main()
