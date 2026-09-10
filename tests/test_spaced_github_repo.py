#!/usr/bin/env python3

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "spaced_github_repo.py"
SPEC = importlib.util.spec_from_file_location("spaced_github_repo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
repo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repo)


def release_for(repository: str, patterns: list[str]) -> dict:
    assets = []
    for index, pattern in enumerate(patterns, start=1):
        name = pattern.replace("*", "9.9.9")
        assets.append(
            {
                "id": index,
                "name": name,
                "state": "uploaded",
                "size": index * 100,
                "digest": f"sha256:{index:064x}",
                "browser_download_url": (
                    f"https://github.com/{repository}/releases/download/v9.9.9/{name}"
                ),
            }
        )
    return {
        "id": 9000,
        "tag_name": "v9.9.9",
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/{repository}/releases/tag/v9.9.9",
        "created_at": "2026-01-01T00:00:00Z",
        "published_at": "2026-01-01T00:00:00Z",
        "assets": assets,
    }


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog_path = REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
        self.catalog = repo.load_catalog(self.catalog_path)

    def test_catalog_is_normalized_and_complete(self) -> None:
        self.assertEqual(self.catalog["remote"]["name"], "spaced-github")
        self.assertEqual(
            self.catalog["remote"]["descriptor_url"],
            "https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo",
        )
        self.assertEqual(
            self.catalog["remote"]["repository_url"],
            "https://crhy.github.io/spacedbazaar/flatpak-repo/",
        )
        apps = {app["id"]: app for app in self.catalog["apps"]}
        self.assertEqual(
            set(apps),
            {
                "io.github.crhy.BrutalChess",
                "io.github.crhy.CardsWithCats",
                "io.github.crhy.SpacedBazaar",
                "io.github.crhy.SpacedWelcome",
                "io.github.crhy.voice2textai",
                "io.github.crhy.rhYciv",
            },
        )
        self.assertTrue(all(app["publish"] for app in apps.values()))

    def test_schema_is_valid_json(self) -> None:
        schema_path = REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("app", schema["$defs"])

    def test_duplicate_app_id_is_rejected(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["apps"].append(copy.deepcopy(catalog["apps"][0]))
        with self.assertRaisesRegex(repo.CatalogError, "duplicate app ID"):
            repo.validate_catalog(catalog)

    def test_publish_false_requires_reason(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["apps"][-1]["publish"] = False
        with self.assertRaisesRegex(repo.CatalogError, "blocked_reason"):
            repo.validate_catalog(catalog)

    def test_policy_cannot_be_weakened(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["policy"]["require_github_sha256"] = False
        with self.assertRaisesRegex(repo.CatalogError, "fail-closed"):
            repo.validate_catalog(catalog)

    def test_icon_policy_cannot_be_weakened(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["policy"]["require_appstream_icon"] = False
        with self.assertRaisesRegex(repo.CatalogError, "fail-closed"):
            repo.validate_catalog(catalog)

    def test_pins_cannot_silently_change_the_latest_stable_policy(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["policy"]["channel"] = "latest-stable"
        with self.assertRaisesRegex(repo.CatalogError, "explicit catalog channel"):
            repo.validate_catalog(catalog)

    def test_published_apps_require_screenshots(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["apps"][0]["screenshots"] = []
        with self.assertRaisesRegex(repo.CatalogError, "at least one screenshot"):
            repo.validate_catalog(catalog)

    def test_pin_must_cover_each_architecture(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["apps"][0]["assets"].append({"arch": "aarch64", "pattern": "example-aarch64.flatpak"})
        with self.assertRaisesRegex(repo.CatalogError, "every published architecture"):
            repo.validate_catalog(catalog)

    def test_resolve_from_fixtures_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture_dir = pathlib.Path(temporary)
            for app in self.catalog["apps"]:
                app.pop("release_pin", None)
                release = release_for(
                    app["repository"], [asset["pattern"] for asset in app["assets"]]
                )
                fixture = fixture_dir / f"{app['repository'].replace('/', '__')}.json"
                fixture.write_text(json.dumps(release), encoding="utf-8")
            first = repo.resolve_catalog(self.catalog, fixture_dir)
            second = repo.resolve_catalog(self.catalog, fixture_dir)
            self.assertEqual(first, second)
            self.assertEqual(
                [app["id"] for app in first["apps"]],
                sorted(app["id"] for app in self.catalog["apps"]),
            )
            self.assertRegex(first["catalog_sha256"], r"^[0-9a-f]{64}$")


class ReleaseAssetTests(unittest.TestCase):
    repository = "crhy/example"

    def test_exact_asset_is_selected(self) -> None:
        release = release_for(self.repository, ["Example-*.flatpak"])
        selected = repo.select_release_asset(
            release, self.repository, "x86_64", "Example-*.flatpak"
        )
        self.assertEqual(selected["name"], "Example-9.9.9.flatpak")
        self.assertEqual(selected["sha256"], f"{1:064x}")

    def test_ambiguous_match_is_rejected(self) -> None:
        release = release_for(
            self.repository, ["Example-one.flatpak", "Example-two.flatpak"]
        )
        with self.assertRaisesRegex(repo.CatalogError, "exactly one"):
            repo.select_release_asset(
                release, self.repository, "x86_64", "Example-*.flatpak"
            )

    def test_prerelease_is_rejected(self) -> None:
        release = release_for(self.repository, ["Example.flatpak"])
        release["prerelease"] = True
        with self.assertRaisesRegex(repo.CatalogError, "not a stable"):
            repo.select_release_asset(
                release, self.repository, "x86_64", "Example.flatpak"
            )

    def test_reviewed_prerelease_requires_exact_tag_and_digest(self) -> None:
        release = release_for(self.repository, ["Example.flatpak"])
        release["prerelease"] = True
        pin = {"tag": "v9.9.9", "asset_sha256": {"x86_64": f"{1:064x}"}}
        repo.select_release_asset(release, self.repository, "x86_64", "Example.flatpak", pin)
        release["tag_name"] = "v9.9.8"
        with self.assertRaisesRegex(repo.CatalogError, "reviewed pin"):
            repo.select_release_asset(release, self.repository, "x86_64", "Example.flatpak", pin)
        release["tag_name"] = "v9.9.9"
        release["assets"][0]["digest"] = f"sha256:{2:064x}"
        with self.assertRaisesRegex(repo.CatalogError, "reviewed pin"):
            repo.select_release_asset(release, self.repository, "x86_64", "Example.flatpak", pin)
        release["assets"][0]["digest"] = f"sha256:{1:064x}"
        release["draft"] = True
        with self.assertRaisesRegex(repo.CatalogError, "not a stable"):
            repo.select_release_asset(release, self.repository, "x86_64", "Example.flatpak", pin)

    def test_missing_github_digest_is_rejected(self) -> None:
        release = release_for(self.repository, ["Example.flatpak"])
        release["assets"][0]["digest"] = None
        with self.assertRaisesRegex(repo.CatalogError, "digest"):
            repo.select_release_asset(
                release, self.repository, "x86_64", "Example.flatpak"
            )

    def test_asset_outside_repository_release_path_is_rejected(self) -> None:
        release = release_for(self.repository, ["Example.flatpak"])
        release["assets"][0]["browser_download_url"] = (
            "https://github.com/someone/else/releases/download/v1/Example.flatpak"
        )
        with self.assertRaisesRegex(repo.CatalogError, "outside"):
            repo.select_release_asset(
                release, self.repository, "x86_64", "Example.flatpak"
            )


class RepositoryOutputTests(unittest.TestCase):
    def test_screenshots_preserve_metadata_and_do_not_mutate_hardlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            original = root / "original.xml"
            original.write_text('<components><component><id>io.example.App</id><name>App</name>'
                                '<screenshots><screenshot><image>old</image></screenshot></screenshots>'
                                '</component></components>')
            (checkout / "appstream.xml").hardlink_to(original)
            shots = {"io.example.App": [{"url": "https://example.org/current.png", "caption": "Current view",
                                         "width": 1280, "height": 720}]}
            repo.apply_screenshots(checkout, shots)
            result = ET.parse(checkout / "appstream.xml").getroot()
            self.assertEqual(result.findtext("component/name"), "App")
            self.assertEqual(result.findtext("component/screenshots/screenshot/image"), "https://example.org/current.png")
            self.assertIn("<image>old</image>", original.read_text())
            self.assertEqual((checkout / "appstream.xml").read_bytes(), gzip.decompress((checkout / "appstream.xml.gz").read_bytes()))
            with self.assertRaisesRegex(repo.CatalogError, "missing or empty"):
                repo.apply_screenshots(checkout, {"io.example.Missing": shots["io.example.App"]})

    def test_generated_catalog_requires_every_imported_app_and_its_icon(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary)
            metadata = checkout / "appstream.xml"
            metadata.write_text('<components><component><id>io.example.App</id>'
                                '<icon type="cached" width="128" height="128">io.example.App.png</icon>'
                                '</component></components>')
            with self.assertRaisesRegex(repo.CatalogError, "missing io.example.Other"):
                repo.validate_appstream_checkout(checkout, ["io.example.Other"])
            with self.assertRaisesRegex(repo.CatalogError, "no cached icon"):
                repo.validate_appstream_checkout(checkout, ["io.example.App"])
            icon = checkout / "icons/128x128/io.example.App.png"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"test icon")
            repo.validate_appstream_checkout(checkout, ["io.example.App"])
            icon.write_bytes(b"")
            with self.assertRaisesRegex(repo.CatalogError, "no cached icon"):
                repo.validate_appstream_checkout(checkout, ["io.example.App"])

    def test_installed_icons_are_applied_after_base_deserialization(self):
        source = (REPOSITORY_ROOT / "src" / "bz-flatpak-entry.c").read_text(
            encoding="utf-8"
        )
        function = source.split("bz_flatpak_entry_real_deserialize", 1)[1].split(
            "static void\nserializable_iface_init", 1
        )[0]
        self.assertLess(
            function.index("bz_entry_deserialize"),
            function.index("apply_icon_theme"),
        )

    def test_sha256_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "payload"
            path.write_bytes(b"Spaced Linux\n")
            self.assertEqual(
                repo.sha256_file(path), hashlib.sha256(b"Spaced Linux\n").hexdigest()
            )

    def test_signed_descriptor_embeds_public_key(self) -> None:
        catalog = repo.load_catalog(
            REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
        )
        descriptor = repo.render_flatpakrepo(catalog["remote"], b"public-key")
        self.assertIn("GPGKey=cHVibGljLWtleQ==", descriptor)
        self.assertNotIn("X-Spaced-Publishable=false", descriptor)

    def test_unsigned_descriptor_is_marked_non_publishable(self) -> None:
        catalog = repo.load_catalog(
            REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
        )
        descriptor = repo.render_flatpakrepo(catalog["remote"], None)
        self.assertIn("X-Spaced-Publishable=false", descriptor)
        self.assertNotIn("GPGKey=", descriptor)

    def test_flatpakref_uses_updateable_spaced_remote(self) -> None:
        catalog = repo.load_catalog(
            REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
        )
        app = next(
            app
            for app in catalog["apps"]
            if app["id"] == "io.github.crhy.SpacedBazaar"
        )
        flatpakref = repo.render_flatpakref(
            catalog["remote"], app, b"public-key"
        )
        self.assertIn("Name=io.github.crhy.SpacedBazaar", flatpakref)
        self.assertIn("Branch=master", flatpakref)
        self.assertIn(
            "Url=https://crhy.github.io/spacedbazaar/flatpak-repo/", flatpakref
        )
        self.assertIn(
            "RuntimeRepo=https://flathub.org/repo/flathub.flatpakrepo", flatpakref
        )
        self.assertIn("SuggestRemoteName=spaced-github", flatpakref)
        self.assertIn("GPGKey=cHVibGljLWtleQ==", flatpakref)

    def test_release_bundle_has_application_and_runtime_origins(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "build-flatpak.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "--repo-url=https://crhy.github.io/spacedbazaar/flatpak-repo/",
            workflow,
        )
        self.assertIn(
            "--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo",
            workflow,
        )
        self.assertIn("upload-artifact@", workflow)

    def test_publish_build_requires_signing_before_writing(self) -> None:
        catalog = repo.load_catalog(
            REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            with self.assertRaisesRegex(repo.CatalogError, "requires --gpg-sign"):
                repo.build_repository(
                    catalog,
                    {"apps": []},
                    root / "output",
                    root / "cache",
                    None,
                    None,
                    True,
                    False,
                )
            self.assertFalse((root / "output").exists())

    def test_metainfo_component_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary)
            directory = checkout / "export" / "share" / "metainfo"
            directory.mkdir(parents=True)
            path = directory / "io.github.crhy.Example.metainfo.xml"
            path.write_text(
                '<component type="desktop-application">'
                "<id>io.github.crhy.Example</id>"
                "</component>",
                encoding="utf-8",
            )
            ids, paths = repo._metadata_component_ids(checkout)
            self.assertEqual(ids, ["io.github.crhy.Example"])
            self.assertEqual(
                paths,
                ["export/share/metainfo/io.github.crhy.Example.metainfo.xml"],
            )

    def test_exported_icon_paths_require_matching_nonempty_app_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary)
            directory = checkout / "export" / "share" / "icons" / "hicolor" / "128x128" / "apps"
            directory.mkdir(parents=True)
            icon = directory / "io.github.crhy.Example.png"
            icon.write_bytes(b"png")
            self.assertEqual(
                repo._exported_icon_paths(checkout, "io.github.crhy.Example"),
                ["export/share/icons/hicolor/128x128/apps/io.github.crhy.Example.png"],
            )
            icon.write_bytes(b"")
            self.assertEqual(repo._exported_icon_paths(checkout, "io.github.crhy.Example"), [])


if __name__ == "__main__":
    unittest.main()
