#!/usr/bin/env python3
"""The signed catalog must only pin screenshots this repository can serve."""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import tempfile
import unittest
import urllib.parse


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "spaced_github_repo.py"
SPEC = importlib.util.spec_from_file_location("spaced_github_repo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
repo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repo)

CATALOG_PATH = REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
SELF_RAW_PREFIX = "https://raw.githubusercontent.com/crhy/spacedbazaar/"
PINNED_COMMIT = "d8d1fdf2a24944d2b7063a17911336254129f687"
MISSING_COMMIT = "0" * 40


def raw_path(url: str) -> str:
    """Return the repository path a self-hosted raw URL points at."""
    segments = urllib.parse.urlsplit(url).path.strip("/").split("/")
    return "/".join(segments[3:])


def app_by_id(catalog: dict, app_id: str) -> dict:
    return next(app for app in catalog["apps"] if app["id"] == app_id)


class PinnedScreenshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = repo.load_catalog(CATALOG_PATH)

    def test_real_catalog_pins_verify_against_this_checkout(self) -> None:
        repo.verify_pinned_screenshots(self.catalog, REPOSITORY_ROOT)

    def test_wrong_pinned_digest_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        app_by_id(catalog, "io.github.crhy.rhYciv")["screenshots"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(repo.CatalogError, "hashes to"):
            repo.verify_pinned_screenshots(catalog, REPOSITORY_ROOT)

    def test_path_missing_from_the_pinned_commit_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        shot = app_by_id(catalog, "io.github.crhy.rhYciv")["screenshots"][0]
        shot["url"] = f"{SELF_RAW_PREFIX}{PINNED_COMMIT}/screenshots/rhyciv-not-committed.png"
        with self.assertRaisesRegex(repo.CatalogError, "not in commit"):
            repo.verify_pinned_screenshots(catalog, REPOSITORY_ROOT)

    def test_unknown_pinned_commit_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        shot = app_by_id(catalog, "io.github.crhy.rhYciv")["screenshots"][0]
        shot["url"] = f"{SELF_RAW_PREFIX}{MISSING_COMMIT}/screenshots/rhyciv-main-menu-1600.png"
        with self.assertRaisesRegex(repo.CatalogError, "not in this repository"):
            repo.verify_pinned_screenshots(catalog, REPOSITORY_ROOT)

    def test_self_hosted_path_outside_screenshots_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        shot = app_by_id(catalog, "io.github.crhy.rhYciv")["screenshots"][0]
        shot["url"] = f"{SELF_RAW_PREFIX}{PINNED_COMMIT}/catalog/crhy-flatpaks.json"
        with self.assertRaisesRegex(repo.CatalogError, "outside screenshots/"):
            repo.verify_pinned_screenshots(catalog, REPOSITORY_ROOT)

    def test_broken_pin_stops_the_build_before_anything_is_published(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        app_by_id(catalog, "io.github.crhy.SpacedBazaar")["screenshots"][0]["sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            with self.assertRaisesRegex(repo.CatalogError, "hashes to"):
                repo.build_repository(
                    catalog,
                    {"apps": []},
                    root / "output",
                    root / "cache",
                    None,
                    None,
                    False,
                    False,
                )
            self.assertFalse((root / "output").exists())

    def test_rhyciv_lists_both_committed_captures(self) -> None:
        shots = app_by_id(self.catalog, "io.github.crhy.rhYciv")["screenshots"]
        self.assertEqual(len(shots), 2)
        self.assertEqual(
            {raw_path(shot["url"]) for shot in shots},
            {
                "screenshots/rhyciv-main-menu-1600.png",
                "screenshots/rhyciv-main-menu-2026-09.png",
            },
        )
        captions = [shot["caption"] for shot in shots]
        self.assertEqual(len(set(captions)), 2)
        self.assertTrue(all(caption.strip() for caption in captions))
        self.assertIn("2026-09", captions[1])

    def test_every_self_hosted_screenshot_exists_under_screenshots(self) -> None:
        checked = 0
        for app in self.catalog["apps"]:
            for shot in app["screenshots"]:
                if not shot["url"].startswith(SELF_RAW_PREFIX):
                    continue
                path = raw_path(shot["url"])
                self.assertTrue(path.startswith("screenshots/"), path)
                self.assertTrue((REPOSITORY_ROOT / path).is_file(), path)
                checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_screenshots_hosted_by_other_repositories_are_left_to_them(self) -> None:
        foreign = [
            shot["url"]
            for app in self.catalog["apps"]
            for shot in app["screenshots"]
            if not shot["url"].startswith(SELF_RAW_PREFIX)
        ]
        self.assertTrue(foreign)
        repo.verify_pinned_screenshots(self.catalog, REPOSITORY_ROOT)

    def test_self_hosted_pin_on_a_moving_ref_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        shot = app_by_id(catalog, "io.github.crhy.rhYciv")["screenshots"][0]
        shot["url"] = f"{SELF_RAW_PREFIX}main/screenshots/rhyciv-main-menu-1600.png"
        with self.assertRaisesRegex(repo.CatalogError, "exact 40-character commit SHA"):
            repo.verify_pinned_screenshots(catalog, REPOSITORY_ROOT)


if __name__ == "__main__":
    unittest.main()
