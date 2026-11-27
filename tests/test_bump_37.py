#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "check-bump-37.py"
SPEC = importlib.util.spec_from_file_location("check_bump_37", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

MANIFEST_PATH = (
    REPOSITORY_ROOT / "build-aux" / "flatpak" / "io.github.crhy.SpacedBazaar.json"
)

OLD_BABEL_URL = (
    "https://files.pythonhosted.org/packages/7d/b2/51899539b6ceeeb420d40ed3cd4"
    "b7a40519404f9baf3d4ac99dc413a834b/babel-2.18.0.tar.gz"
)
OLD_BABEL_SHA256 = "b80b99a14bd085fcacfa15c9165f651fbb3406e66cc603abf11c5750937c992d"


def babel_source(manifest: dict) -> dict:
    for source in checker.file_sources(checker.module_by_name(manifest, "python3-babel")):
        return source
    raise AssertionError("no python3-babel file source in the manifest")


def flatpak_source(manifest: dict) -> dict:
    source = checker.git_source(checker.module_by_name(manifest, "flatpak"))
    assert source is not None
    return source


class CheckBump37(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_committed_manifest_satisfies_the_checker(self):
        self.assertEqual([], checker.check_manifest(self.manifest))

    def test_babel_left_at_2_18_0_fails_the_checker(self):
        manifest = copy.deepcopy(self.manifest)
        source = babel_source(manifest)
        source["url"] = OLD_BABEL_URL
        source["sha256"] = OLD_BABEL_SHA256
        failures = checker.check_manifest(manifest)
        self.assertTrue(any("python3-babel" in failure for failure in failures))

    def test_short_flatpak_commit_fails_the_checker(self):
        manifest = copy.deepcopy(self.manifest)
        flatpak_source(manifest)["commit"] = checker.FLATPAK_COMMIT[:12]
        failures = checker.check_manifest(manifest)
        self.assertTrue(any("flatpak" in failure for failure in failures))

    def test_bumped_ostree_tag_fails_the_f098_guard(self):
        manifest = copy.deepcopy(self.manifest)
        ostree = checker.git_source(checker.module_by_name(manifest, "ostree"))
        assert ostree is not None
        ostree["tag"] = "v2026.7"
        failures = checker.check_manifest(manifest)
        self.assertTrue(any("ostree" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
