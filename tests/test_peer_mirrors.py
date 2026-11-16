#!/usr/bin/env python3
"""Peer mirrors may supply bytes but never authority.

Every candidate URL is verified against the origin-published size and SHA-256;
a peer's own digest is never read, and the signed origin is always the last
resort. No network and no application are involved: the module's functions are
called directly with fixture payloads, the way tests/test_spaced_github_repo.py
drives them.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import pathlib
import re
import tempfile
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "spaced_github_repo.py"
SPEC = importlib.util.spec_from_file_location("spaced_github_repo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
repo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repo)


PAYLOAD = b"Spaced Linux flatpak bundle bytes\n" * 8
ORIGIN_URL = "https://github.com/crhy/example/releases/download/v9.9.9/Example-9.9.9.flatpak"
PEER_URL = "https://lab.example/spacedbazaar/Example-9.9.9.flatpak"


def asset() -> dict:
    return {
        "arch": "x86_64",
        "pattern": "Example-*.flatpak",
        "asset_id": 4242,
        "name": "Example-9.9.9.flatpak",
        "size": len(PAYLOAD),
        "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        "download_url": ORIGIN_URL,
    }


def peer(
    name: str = "lab-mirror",
    base_url: str = "https://lab.example/spacedbazaar/{filename}",
    arches: tuple[str, ...] = ("x86_64",),
) -> dict:
    return {"name": name, "base_url": base_url, "allow_for_arches": list(arches)}


class RecordingFetcher:
    """Stands in for urllib: serves fixture bytes per URL, or fails that URL."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.responses: dict[str, bytes] = {}
        self.broken: set[str] = set()

    def add(self, url: str, payload: bytes) -> None:
        self.responses[url] = payload

    def break_url(self, url: str) -> None:
        self.broken.add(url)

    def __call__(self, url: str, destination: pathlib.Path, limit: int) -> None:
        self.calls.append((url, limit))
        if url in self.broken:
            raise repo.CatalogError(f"cannot download {url}: connection reset")
        destination.write_bytes(self.responses[url][:limit])


def provenance(cache_dir: pathlib.Path) -> dict:
    path = cache_dir / repo.PROVENANCE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


class PeerBlockValidationTests(unittest.TestCase):
    def test_shipped_catalog_ships_no_peers_and_an_off_policy(self) -> None:
        catalog = repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json")
        self.assertEqual(catalog["peers"], [])
        self.assertEqual(catalog["policy"]["peer_fetch"], "off")

    def test_peer_fetch_policy_cannot_be_weakened(self) -> None:
        catalog = repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json")
        catalog = copy.deepcopy(catalog)
        catalog["policy"]["peer_fetch"] = "opt-in"
        with self.assertRaisesRegex(repo.CatalogError, "fail-closed"):
            repo.validate_catalog(catalog)

    def test_peer_block_requires_https(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "HTTPS"):
            repo.validate_peers([peer(base_url="http://lab.example/{filename}")])

    def test_peer_template_requires_the_asset_filename_placeholder(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "placeholder"):
            repo.validate_peers([peer(base_url="https://lab.example/spacedbazaar/")])
        with self.assertRaisesRegex(repo.CatalogError, "placeholder"):
            repo.validate_peers([peer(base_url="https://lab.example/{name}/flatpak")])

    def test_duplicate_peer_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "duplicate peer name"):
            repo.validate_peers([peer(), peer(name="lab-mirror")])

    def test_peer_cannot_claim_the_reserved_origin_name(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "reserved"):
            repo.validate_peers([peer(name="origin")])

    def test_a_peer_url_may_not_traverse_or_carry_a_query(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "traverse"):
            repo.validate_peers([peer(base_url="https://lab.example/../{filename}")])
        with self.assertRaisesRegex(repo.CatalogError, "queries"):
            repo.validate_peers([peer(base_url="https://lab.example/{filename}?a=b")])

    def test_peer_arches_must_be_supported_and_listed(self) -> None:
        with self.assertRaisesRegex(repo.CatalogError, "unsupported"):
            repo.validate_peers([peer(arches=("win32",))])
        with self.assertRaisesRegex(repo.CatalogError, "must not be empty"):
            repo.validate_peers([peer(arches=())])

    def test_a_peer_cannot_arrive_with_unknown_keys_or_its_own_digest(self) -> None:
        hostile = peer()
        hostile["digest"] = hashlib.sha256(b"peer-authored bytes").hexdigest()
        with self.assertRaisesRegex(repo.CatalogError, "unknown keys"):
            repo.validate_peers([hostile])
        incomplete = peer()
        del incomplete["base_url"]
        with self.assertRaisesRegex(repo.CatalogError, "missing: base_url"):
            repo.validate_peers([incomplete])

    def test_cli_peer_mirror_uses_the_same_rules(self) -> None:
        parsed = repo.parse_peer_spec("lab-mirror=https://lab.example/{filename}")
        self.assertEqual(parsed["name"], "lab-mirror")
        self.assertEqual(sorted(parsed["allow_for_arches"]), ["aarch64", "x86_64"])
        with self.assertRaisesRegex(repo.CatalogError, "NAME=URL"):
            repo.parse_peer_spec("lab-mirror")
        with self.assertRaisesRegex(repo.CatalogError, "HTTPS"):
            repo.parse_peer_spec("lab-mirror=http://lab.example/{filename}")

    def test_declared_catalog_peers_are_not_consulted_while_the_policy_is_off(self) -> None:
        catalog = copy.deepcopy(
            repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json")
        )
        catalog["peers"] = [peer()]
        repo.validate_catalog(catalog)
        with self.assertRaisesRegex(repo.CatalogError, "peer_fetch is off"):
            repo.resolve_peer_sources(catalog)

    def test_duplicate_cli_peer_names_are_rejected(self) -> None:
        catalog = repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json")
        with self.assertRaisesRegex(repo.CatalogError, "duplicate --peer-mirror name"):
            repo.resolve_peer_sources(
                catalog,
                [
                    "lab=https://one.example/{filename}",
                    "lab=https://two.example/{filename}",
                ],
            )


class CandidateOrderTests(unittest.TestCase):
    def test_peers_are_tried_before_the_signed_origin(self) -> None:
        candidates = repo.peer_candidates([peer()], asset())
        self.assertEqual(
            candidates,
            [("lab-mirror", PEER_URL), ("origin", ORIGIN_URL)],
        )

    def test_the_peer_url_is_built_from_the_asset_filename(self) -> None:
        candidates = repo.peer_candidates([peer()], asset())
        self.assertTrue(candidates[0][1].endswith("/Example-9.9.9.flatpak"))

    def test_a_peer_unlisted_for_the_arch_is_never_consulted(self) -> None:
        candidates = repo.peer_candidates([peer(arches=("aarch64",))], asset())
        self.assertEqual(candidates, [("origin", ORIGIN_URL)])

    def test_a_peer_pointing_at_the_origin_is_not_double_counted(self) -> None:
        candidates = repo.peer_candidates(
            [peer(base_url="https://github.com/crhy/example/releases/download/v9.9.9/{filename}")],
            asset(),
        )
        self.assertEqual(candidates, [("origin", ORIGIN_URL)])

    def test_the_origin_is_always_the_last_candidate(self) -> None:
        candidates = repo.peer_candidates([peer(), peer(name="second")], asset())
        self.assertEqual(candidates[-1], ("origin", ORIGIN_URL))
        self.assertEqual(len(candidates), 3)


class DownloadVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetcher = RecordingFetcher()
        self.fetcher.add(ORIGIN_URL, PAYLOAD)

    def download(self, peers: list[dict]) -> tuple[pathlib.Path, str]:
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            bundle, source = repo.download_asset(
                asset(), cache_dir, peers, self.fetcher
            )
            self.assertEqual(bundle.read_bytes(), PAYLOAD)
            self.assertEqual(
                repo.sha256_file(bundle), asset()["sha256"]
            )
            self.assertEqual(
                sorted(path.name for path in cache_dir.iterdir()),
                [f"{4242}-Example-9.9.9.flatpak", repo.PROVENANCE_FILENAME],
            )
            return bundle, source

    def test_verified_peer_bytes_are_accepted_and_the_peer_is_named(self) -> None:
        self.fetcher.add(PEER_URL, PAYLOAD)
        _, source = self.download([peer()])
        self.assertEqual(source, "lab-mirror")
        self.assertEqual([url for url, _ in self.fetcher.calls], [PEER_URL])

    def test_a_hostile_peer_is_rejected_and_the_origin_still_serves(self) -> None:
        self.fetcher.add(PEER_URL, b"attacker bytes\n" * 8)
        _, source = self.download([peer()])
        self.assertEqual(source, "origin")
        self.assertEqual(
            [url for url, _ in self.fetcher.calls], [PEER_URL, ORIGIN_URL]
        )

    def test_the_rejection_is_recorded_in_the_cache_provenance(self) -> None:
        self.fetcher.add(PEER_URL, b"attacker bytes\n" * 8)
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            repo.download_asset(asset(), cache_dir, [peer()], self.fetcher)
            entry = provenance(cache_dir)[f"{4242}-Example-9.9.9.flatpak"]
        self.assertEqual(entry["source"], "origin")
        self.assertEqual(len(entry["rejections"]), 1)
        self.assertRegex(
            entry["rejections"][0],
            r"^rejected peer lab-mirror: SHA-256 [0-9a-f]{64}/[0-9a-f]{64}",
        )

    def test_a_truncated_peer_stream_is_rejected(self) -> None:
        self.fetcher.add(PEER_URL, PAYLOAD[: len(PAYLOAD) // 2])
        _, source = self.download([peer()])
        self.assertEqual(source, "origin")

    def test_an_over_long_peer_stream_is_capped(self) -> None:
        self.fetcher.add(PEER_URL, PAYLOAD + b"x" * 4 * 1024 * 1024)
        _, source = self.download([peer()])
        self.assertEqual(source, "origin")
        limit = self.fetcher.calls[0][1]
        self.assertEqual(limit, asset()["size"] + repo.PEER_SLACK_BYTES)

    def test_a_peer_digest_never_overrides_the_catalog(self) -> None:
        peer_bytes = b"peer-authored bundle\n" * 8
        self.fetcher.add(PEER_URL, peer_bytes)
        _, source = self.download([peer()])
        self.assertEqual(source, "origin")
        self.assertNotEqual(
            hashlib.sha256(peer_bytes).hexdigest(), asset()["sha256"]
        )

    def test_no_partial_file_survives_a_rejected_peer(self) -> None:
        self.fetcher.add(PEER_URL, b"attacker bytes\n" * 8)
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            repo.download_asset(asset(), cache_dir, [peer()], self.fetcher)
            self.assertEqual(
                sorted(path.name for path in cache_dir.iterdir()),
                [f"{4242}-Example-9.9.9.flatpak", repo.PROVENANCE_FILENAME],
            )

    def test_an_unreachable_origin_with_only_a_hostile_peer_still_fails(self) -> None:
        self.fetcher.add(PEER_URL, b"attacker bytes\n" * 8)
        self.fetcher.break_url(ORIGIN_URL)
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            with self.assertRaisesRegex(
                repo.CatalogError, "rejected peer lab-mirror"
            ):
                repo.download_asset(asset(), cache_dir, [peer()], self.fetcher)
            self.assertEqual(list(cache_dir.iterdir()), [])

    def test_the_origin_failing_verification_raises_the_existing_error(self) -> None:
        self.fetcher.add(ORIGIN_URL, b"attacker bytes\n" * 8)
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            with self.assertRaisesRegex(
                repo.CatalogError, "download verification failed"
            ):
                repo.download_asset(asset(), cache_dir, [], self.fetcher)

    def test_verified_cached_bytes_are_reused_and_recorded_as_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            cache_dir.mkdir()
            (cache_dir / f"{4242}-Example-9.9.9.flatpak").write_bytes(PAYLOAD)
            bundle, source = repo.download_asset(
                asset(), cache_dir, [peer()], self.fetcher
            )
            self.assertEqual(source, "cache")
            self.assertEqual(self.fetcher.calls, [])
            self.assertEqual(
                provenance(cache_dir)[f"{4242}-Example-9.9.9.flatpak"],
                {"source": "cache"},
            )

    def test_a_stale_cached_file_is_refetched_through_the_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = pathlib.Path(temporary) / "cache"
            cache_dir.mkdir()
            (cache_dir / f"{4242}-Example-9.9.9.flatpak").write_bytes(
                b"stale bytes\n" * 8
            )
            self.fetcher.add(PEER_URL, PAYLOAD)
            bundle, source = repo.download_asset(
                asset(), cache_dir, [peer()], self.fetcher
            )
            self.assertEqual(source, "lab-mirror")
            self.assertEqual(bundle.read_bytes(), PAYLOAD)


class CommandWiringTests(unittest.TestCase):
    def test_build_command_accepts_repeatable_peer_mirrors(self) -> None:
        parser = repo.build_parser()
        args = parser.parse_args(
            [
                "build",
                "--output-dir",
                "build/out",
                "--cache-dir",
                "build/cache",
                "--peer-mirror",
                "lab=https://one.example/{filename}",
                "--peer-mirror",
                " neighbour=https://two.example/{filename} ",
            ]
        )
        self.assertEqual(len(args.peer_mirror), 2)
        peers = repo.resolve_peer_sources(
            repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"),
            args.peer_mirror,
        )
        self.assertEqual([p["name"] for p in peers], ["lab", "neighbour"])

    def test_the_build_command_defaults_to_no_peers(self) -> None:
        parser = repo.build_parser()
        args = parser.parse_args(
            ["build", "--output-dir", "build/out", "--cache-dir", "build/cache"]
        )
        self.assertIsNone(args.peer_mirror)
        self.assertEqual(
            repo.resolve_peer_sources(
                repo.load_catalog(REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.json"),
                args.peer_mirror or [],
            ),
            [],
        )

    def test_build_repository_accepts_peers_and_records_the_source(self) -> None:
        signature = inspect.signature(repo.build_repository)
        self.assertIn("peers", signature.parameters)
        self.assertEqual(signature.parameters["peers"].default, ())
        source = (
            REPOSITORY_ROOT / "scripts" / "spaced_github_repo.py"
        ).read_text(encoding="utf-8")
        self.assertIn("bundle, source = download_asset(asset, cache_dir, peers)", source)
        self.assertIn('"source": source,', source)


class SchemaPeerTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = REPOSITORY_ROOT / "catalog" / "crhy-flatpaks.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def test_the_peers_block_is_optional_and_typed(self) -> None:
        self.assertEqual(
            self.schema["properties"]["peers"]["items"],
            {"$ref": "#/$defs/peer"},
        )
        self.assertNotIn("peers", self.schema["required"])

    def test_a_peer_must_declare_base_url_and_may_not_add_keys(self) -> None:
        definition = self.schema["$defs"]["peer"]
        self.assertEqual(
            definition["required"], ["name", "base_url", "allow_for_arches"]
        )
        self.assertIs(definition["additionalProperties"], False)

    def test_the_peer_url_pattern_is_https_only_with_one_placeholder(self) -> None:
        pattern = self.schema["$defs"]["peer"]["properties"]["base_url"]["pattern"]
        compiled = re.compile(pattern)
        self.assertIsNotNone(compiled.match("https://lab.example/{filename}"))
        for rejected in (
            "http://lab.example/{filename}",
            "https://lab.example/spacedbazaar/",
            "https://lab.example/{name}/{filename}",
        ):
            self.assertIsNone(compiled.match(rejected), rejected)

    def test_the_schema_keeps_peer_fetch_off(self) -> None:
        policy = self.schema["properties"]["policy"]
        self.assertIn("peer_fetch", policy["required"])
        self.assertEqual(policy["properties"]["peer_fetch"]["const"], "off")

    def test_the_schema_still_refuses_unknown_top_level_keys(self) -> None:
        self.assertIs(self.schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
