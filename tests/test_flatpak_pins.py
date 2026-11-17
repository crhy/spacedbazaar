#!/usr/bin/env python3
"""Keep every Flatpak manifest pin matched to a reviewed tag and commit."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = REPOSITORY_ROOT / "scripts" / "check-flatpak-pins.py"
MANIFEST = REPOSITORY_ROOT / "build-aux/flatpak/io.github.crhy.SpacedBazaar.json"
PIN_RECORDS = REPOSITORY_ROOT / "catalog" / "flatpak-pins.json"

OSTREE_URL = "https://github.com/ostreedev/ostree"
POLKIT_URL = "https://github.com/polkit-org/polkit"
OSTREE_NEW_TAG = "v2026.7"
OSTREE_OLD_TAG = "v2026.4"
OSTREE_NEW_COMMIT = "882a60eade8ede3e2978b7e7bf914c6fb6869ddc"
OSTREE_OLD_COMMIT = "4f4445a8912f70c604fa84a057a8f4e904e35a24"


def load_json(path: pathlib.Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def iter_sources(manifest) -> list[dict]:
    """Every source dictionary of the manifest, nested modules included."""

    sources: list[dict] = []
    for module in manifest.get("modules", []):
        sources.extend(module.get("sources", []))
        sources.extend(iter_sources({"modules": module.get("modules", [])}))
    return sources


def edited_manifest(url: str, **changes) -> str:
    """Return the committed manifest with one pinned source edited."""

    manifest = load_json(MANIFEST)
    edited = 0
    for source in iter_sources(manifest):
        if source.get("url") != url:
            continue
        for key, value in changes.items():
            if value is None:
                source.pop(key, None)
            else:
                source[key] = value
        edited += 1
    assert edited == 1, f"{url} must be pinned exactly once, found {edited}"
    return json.dumps(manifest, indent=2) + "\n"


class FlatpakPinTests(unittest.TestCase):
    def run_checker(self, manifest: pathlib.Path, pins: pathlib.Path = PIN_RECORDS):
        return subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--manifest",
                str(manifest),
                "--pins",
                str(pins),
            ],
            capture_output=True,
            text=True,
        )

    def write_fixture(self, directory: str, text: str, name: str = "manifest.json") -> pathlib.Path:
        fixture = pathlib.Path(directory) / name
        fixture.write_text(text, encoding="utf-8")
        return fixture

    def test_committed_manifest_matches_the_reviewed_pins(self):
        result = self.run_checker(MANIFEST)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("flatpak pins ok", result.stdout)

    def test_new_tag_with_the_old_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.write_fixture(
                directory,
                edited_manifest(OSTREE_URL, tag=OSTREE_NEW_TAG, commit=OSTREE_OLD_COMMIT),
            )
            result = self.run_checker(fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("half-moved: tag moved, commit left behind", result.stdout)

    def test_new_commit_with_the_old_tag_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.write_fixture(
                directory,
                edited_manifest(OSTREE_URL, tag=OSTREE_OLD_TAG, commit=OSTREE_NEW_COMMIT),
            )
            result = self.run_checker(fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("half-moved: commit moved, tag left behind", result.stdout)

    def test_short_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.write_fixture(
                directory,
                edited_manifest(POLKIT_URL, commit=OSTREE_NEW_COMMIT[:12]),
            )
            result = self.run_checker(fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is 12 characters, not 40", result.stdout)

    def test_missing_tag_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.write_fixture(directory, edited_manifest(POLKIT_URL, tag=None))
            result = self.run_checker(fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no tag", result.stdout)

    def test_pin_without_a_reviewed_record_fails(self):
        records = load_json(PIN_RECORDS)
        records["pins"] = [row for row in records["pins"] if row["url"] != POLKIT_URL]
        with tempfile.TemporaryDirectory() as directory:
            pins = self.write_fixture(directory, json.dumps(records, indent=2) + "\n",
                                      name="flatpak-pins.json")
            result = self.run_checker(MANIFEST, pins)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no reviewed record", result.stdout)

    def test_reviewed_record_the_manifest_does_not_pin_fails(self):
        records = load_json(PIN_RECORDS)
        records["pins"].append(
            {
                "name": "libdex",
                "url": "https://gitlab.gnome.org/GNOME/libdex.git",
                "tag": "1.2.beta",
                "commit": "26d094f2d7a4561862cce3efa00bb5aa1e4b0720",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            pins = self.write_fixture(directory, json.dumps(records, indent=2) + "\n",
                                      name="flatpak-pins.json")
            result = self.run_checker(MANIFEST, pins)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reviewed record is not pinned by the manifest", result.stdout)

    def test_reviewed_records_cover_exactly_the_pinned_sources(self):
        pinned = {
            source["url"]
            for source in iter_sources(load_json(MANIFEST))
            if "x-checker-data" in source and source.get("type") == "git"
        }
        reviewed = {row["url"] for row in load_json(PIN_RECORDS)["pins"]}
        self.assertEqual(pinned, reviewed)
        self.assertEqual(len(reviewed), 6)
        for row in load_json(PIN_RECORDS)["pins"]:
            self.assertTrue(row["name"], "reviewed records name their module")
            self.assertTrue(row["tag"], "reviewed records carry a tag")
            self.assertEqual(len(row["commit"]), 40)
            self.assertTrue(all(character in "0123456789abcdef" for character in row["commit"]))


if __name__ == "__main__":
    unittest.main()
