#!/usr/bin/env python3
"""Resolve verified GitHub Flatpak releases into a Flatpak repository.

The catalog is intentionally curated. GitHub has no global release-asset
search endpoint, and a filename ending in ``.flatpak`` is not a trust signal.
This tool accepts only catalogued repositories, exact-one asset matches,
GitHub-published SHA-256 digests, and bundles whose embedded identity matches
the catalog before importing them into the repository.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import fnmatch
import gzip
import hashlib
import html
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Iterable


GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "SpacedBazaar-flatpak-repository/1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
APP_ID_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")
REPOSITORY_RE = re.compile(r"^crhy/[A-Za-z0-9_.-]+$")
SUPPORTED_ARCHES = {"aarch64", "x86_64"}


class CatalogError(RuntimeError):
    """A catalog, release, bundle, or repository invariant was violated."""


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{context} must be an object")
    return value


def _require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise CatalogError(f"{context} must be an array")
    return value


def _require_nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{context} must be a non-empty string")
    return value


def _require_keys(
    value: dict[str, Any],
    required: Iterable[str],
    allowed: Iterable[str],
    context: str,
) -> None:
    required_set = set(required)
    allowed_set = set(allowed)
    missing = sorted(required_set - value.keys())
    unknown = sorted(value.keys() - allowed_set)
    if missing:
        raise CatalogError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise CatalogError(f"{context} has unknown keys: {', '.join(unknown)}")


def _require_https_url(value: Any, context: str) -> str:
    value = _require_nonempty_string(value, context)
    if not value.startswith("https://"):
        raise CatalogError(f"{context} must be an HTTPS URL")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_catalog(path: pathlib.Path) -> dict[str, Any]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read catalog {path}: {error}") from error
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog_value: Any) -> None:
    catalog = _require_mapping(catalog_value, "catalog")
    _require_keys(
        catalog,
        ["schema_version", "publisher", "remote", "policy", "apps"],
        ["$schema", "schema_version", "publisher", "remote", "policy", "apps"],
        "catalog",
    )
    if catalog["schema_version"] != 1:
        raise CatalogError("catalog.schema_version must be 1")

    publisher = _require_mapping(catalog["publisher"], "catalog.publisher")
    _require_keys(
        publisher,
        ["github_owner", "name", "homepage"],
        ["github_owner", "name", "homepage"],
        "catalog.publisher",
    )
    owner = _require_nonempty_string(
        publisher["github_owner"], "catalog.publisher.github_owner"
    )
    _require_nonempty_string(publisher["name"], "catalog.publisher.name")
    _require_https_url(publisher["homepage"], "catalog.publisher.homepage")

    remote = _require_mapping(catalog["remote"], "catalog.remote")
    remote_keys = [
        "name",
        "title",
        "comment",
        "description",
        "descriptor_url",
        "repository_url",
        "icon",
        "default_branch",
    ]
    _require_keys(remote, remote_keys, remote_keys, "catalog.remote")
    if remote["name"] != "spaced-github":
        raise CatalogError("catalog.remote.name must be spaced-github")
    if (
        remote["descriptor_url"]
        != "https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo"
    ):
        raise CatalogError("catalog.remote.descriptor_url does not match the public contract")
    if remote["repository_url"] != "https://crhy.github.io/spacedbazaar/flatpak-repo/":
        raise CatalogError("catalog.remote.repository_url does not match the public contract")
    for key in ("title", "comment", "description", "default_branch"):
        _require_nonempty_string(remote[key], f"catalog.remote.{key}")
    for key in ("descriptor_url", "repository_url", "icon"):
        _require_https_url(remote[key], f"catalog.remote.{key}")

    policy = _require_mapping(catalog["policy"], "catalog.policy")
    policy_keys = [
        "channel",
        "require_exactly_one_asset",
        "require_github_sha256",
        "require_appstream_metadata",
        "require_appstream_icon",
        "unverified_github_assets",
    ]
    _require_keys(policy, policy_keys, policy_keys, "catalog.policy")
    expected_policy = {
        "channel": policy.get("channel"),
        "require_exactly_one_asset": True,
        "require_github_sha256": True,
        "require_appstream_metadata": True,
        "require_appstream_icon": True,
        "unverified_github_assets": "never-install-automatically",
    }
    if policy != expected_policy or policy["channel"] not in {
        "latest-stable", "latest-stable-with-reviewed-pins"
    }:
        raise CatalogError("catalog.policy must retain the fail-closed verification policy")

    apps = _require_list(catalog["apps"], "catalog.apps")
    if not apps:
        raise CatalogError("catalog.apps must not be empty")
    seen_ids: set[str] = set()
    seen_repositories: set[str] = set()
    for index, raw_app in enumerate(apps):
        context = f"catalog.apps[{index}]"
        app = _require_mapping(raw_app, context)
        required = [
            "id",
            "name",
            "summary",
            "repository",
            "homepage",
            "branch",
            "runtime",
            "publish",
            "assets",
        ]
        allowed = required + ["blocked_reason", "release_pin", "screenshots"]
        _require_keys(app, required, allowed, context)
        app_id = _require_nonempty_string(app["id"], f"{context}.id")
        if not APP_ID_RE.fullmatch(app_id):
            raise CatalogError(f"{context}.id is not a valid reverse-DNS Flatpak ID")
        if app_id in seen_ids:
            raise CatalogError(f"duplicate app ID: {app_id}")
        seen_ids.add(app_id)
        for key in ("name", "summary", "branch"):
            _require_nonempty_string(app[key], f"{context}.{key}")
        repository = _require_nonempty_string(
            app["repository"], f"{context}.repository"
        )
        if not REPOSITORY_RE.fullmatch(repository) or not repository.startswith(f"{owner}/"):
            raise CatalogError(f"{context}.repository must belong to {owner}")
        if repository.casefold() in seen_repositories:
            raise CatalogError(f"duplicate repository: {repository}")
        seen_repositories.add(repository.casefold())
        _require_https_url(app["homepage"], f"{context}.homepage")

        if "release_pin" in app:
            if policy["channel"] != "latest-stable-with-reviewed-pins":
                raise CatalogError("reviewed release pins require an explicit catalog channel")
            pin = _require_mapping(app["release_pin"], f"{context}.release_pin")
            _require_keys(pin, ["tag", "asset_sha256"], ["tag", "asset_sha256"], f"{context}.release_pin")
            _require_nonempty_string(pin["tag"], f"{context}.release_pin.tag")
            digests = _require_mapping(pin["asset_sha256"], f"{context}.release_pin.asset_sha256")
            if not digests or any(arch not in SUPPORTED_ARCHES or not isinstance(digest, str)
                                  or not SHA256_RE.fullmatch(digest) for arch, digest in digests.items()):
                raise CatalogError(f"{context}.release_pin requires architecture-specific SHA-256 digests")
        screenshots = _require_list(app.get("screenshots", []), f"{context}.screenshots")
        if app["publish"] and not screenshots:
            raise CatalogError(f"{context} requires at least one screenshot for publication")
        for shot in screenshots:
            shot = _require_mapping(shot, f"{context}.screenshot")
            _require_keys(shot, ["url", "caption", "sha256"], ["url", "caption", "sha256"], f"{context}.screenshot")
            _require_https_url(shot["url"], f"{context}.screenshot.url")
            _require_nonempty_string(shot["caption"], f"{context}.screenshot.caption")
            if not isinstance(shot["sha256"], str) or not SHA256_RE.fullmatch(shot["sha256"]):
                raise CatalogError(f"{context}.screenshot requires SHA-256")

        runtime = _require_mapping(app["runtime"], f"{context}.runtime")
        runtime_keys = ["id", "branch", "repository"]
        _require_keys(runtime, runtime_keys, runtime_keys, f"{context}.runtime")
        _require_nonempty_string(runtime["id"], f"{context}.runtime.id")
        _require_nonempty_string(runtime["branch"], f"{context}.runtime.branch")
        _require_https_url(runtime["repository"], f"{context}.runtime.repository")

        if not isinstance(app["publish"], bool):
            raise CatalogError(f"{context}.publish must be a boolean")
        if app["publish"] is False:
            _require_nonempty_string(app.get("blocked_reason"), f"{context}.blocked_reason")
        elif "blocked_reason" in app:
            raise CatalogError(f"{context}.blocked_reason is only valid when publish is false")

        assets = _require_list(app["assets"], f"{context}.assets")
        if not assets:
            raise CatalogError(f"{context}.assets must not be empty")
        seen_arches: set[str] = set()
        for asset_index, raw_asset in enumerate(assets):
            asset_context = f"{context}.assets[{asset_index}]"
            asset = _require_mapping(raw_asset, asset_context)
            _require_keys(asset, ["arch", "pattern"], ["arch", "pattern"], asset_context)
            arch = _require_nonempty_string(asset["arch"], f"{asset_context}.arch")
            if arch not in SUPPORTED_ARCHES:
                raise CatalogError(f"{asset_context}.arch is unsupported: {arch}")
            if arch in seen_arches:
                raise CatalogError(f"{context} has duplicate architecture {arch}")
            seen_arches.add(arch)
            pattern = _require_nonempty_string(
                asset["pattern"], f"{asset_context}.pattern"
            )
            if not pattern.endswith(".flatpak") or "/" in pattern or "\\" in pattern:
                raise CatalogError(
                    f"{asset_context}.pattern must be a basename ending in .flatpak"
                )
        if "release_pin" in app and set(app["release_pin"]["asset_sha256"]) != seen_arches:
            raise CatalogError(f"{context}.release_pin must pin every published architecture")


def _load_release_fixture(metadata_dir: pathlib.Path, repository: str) -> dict[str, Any]:
    fixture = metadata_dir / f"{repository.replace('/', '__')}.json"
    try:
        return _require_mapping(
            json.loads(fixture.read_text(encoding="utf-8")), str(fixture)
        )
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read release fixture {fixture}: {error}") from error


def _fetch_latest_release(repository: str, token: str | None, tag: str | None = None) -> dict[str, Any]:
    endpoint = "latest" if tag is None else "tags/" + urllib.parse.quote(tag, safe="")
    url = f"https://api.github.com/repos/{repository}/releases/{endpoint}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return _require_mapping(json.load(response), url)
    except urllib.error.HTTPError as error:
        retry_after = error.headers.get("Retry-After")
        rate_reset = error.headers.get("X-RateLimit-Reset")
        detail = f"HTTP {error.code}"
        if retry_after:
            detail += f", Retry-After={retry_after}"
        if rate_reset:
            detail += f", X-RateLimit-Reset={rate_reset}"
        raise CatalogError(f"GitHub latest-release request failed for {repository}: {detail}") from error
    except (OSError, ValueError) as error:
        raise CatalogError(
            f"GitHub latest-release request failed for {repository}: {error}"
        ) from error


def select_release_asset(
    release_value: Any,
    repository: str,
    arch: str,
    pattern: str,
    release_pin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    release = _require_mapping(release_value, f"latest release for {repository}")
    if release.get("draft") is not False or (release.get("prerelease") is not False
            and not (release_pin is not None and release.get("prerelease") is True)):
        raise CatalogError(f"latest release for {repository} is not a stable published release")
    tag = _require_nonempty_string(release.get("tag_name"), f"{repository} release tag")
    if release_pin is not None and tag != release_pin["tag"]:
        raise CatalogError(f"{repository} release tag does not match the reviewed pin")
    assets = _require_list(release.get("assets"), f"{repository} release assets")
    matches = [
        _require_mapping(asset, f"{repository} release asset")
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and fnmatch.fnmatchcase(asset["name"], pattern)
    ]
    if len(matches) != 1:
        names = ", ".join(sorted(str(asset.get("name")) for asset in matches)) or "none"
        raise CatalogError(
            f"{repository} {tag} must match exactly one {arch} asset with {pattern!r}; "
            f"matched {len(matches)} ({names})"
        )
    asset = matches[0]
    if asset.get("state") != "uploaded":
        raise CatalogError(f"{repository} asset {asset.get('name')} is not fully uploaded")
    digest_value = _require_nonempty_string(
        asset.get("digest"), f"{repository} asset digest"
    )
    algorithm, separator, digest = digest_value.partition(":")
    if algorithm != "sha256" or not separator or not SHA256_RE.fullmatch(digest):
        raise CatalogError(f"{repository} asset has no valid GitHub SHA-256 digest")
    if release_pin is not None and digest != release_pin["asset_sha256"].get(arch):
        raise CatalogError(f"{repository} asset SHA-256 does not match the reviewed pin")
    size = asset.get("size")
    if not isinstance(size, int) or size <= 0:
        raise CatalogError(f"{repository} asset has invalid size: {size!r}")
    asset_id = asset.get("id")
    if not isinstance(asset_id, int) or asset_id <= 0:
        raise CatalogError(f"{repository} asset has invalid ID: {asset_id!r}")
    download_url = _require_https_url(
        asset.get("browser_download_url"), f"{repository} asset download URL"
    )
    expected_prefix = f"https://github.com/{repository}/releases/download/"
    if not download_url.startswith(expected_prefix):
        raise CatalogError(f"{repository} asset URL is outside its GitHub release path")
    return {
        "arch": arch,
        "pattern": pattern,
        "asset_id": asset_id,
        "name": asset["name"],
        "size": size,
        "sha256": digest,
        "download_url": download_url,
    }


def resolve_catalog(
    catalog: dict[str, Any],
    metadata_dir: pathlib.Path | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    validate_catalog(catalog)
    resolved_apps: list[dict[str, Any]] = []
    for app in sorted(catalog["apps"], key=lambda item: item["id"]):
        repository = app["repository"]
        if metadata_dir is None:
            release = _fetch_latest_release(repository, token, app.get("release_pin", {}).get("tag"))
        else:
            release = _load_release_fixture(metadata_dir, repository)
        resolved_assets = [
            select_release_asset(
                release,
                repository,
                asset_spec["arch"],
                asset_spec["pattern"],
                app.get("release_pin"),
            )
            for asset_spec in sorted(app["assets"], key=lambda item: item["arch"])
        ]
        resolved_app = {
            key: app[key]
            for key in (
                "id",
                "name",
                "summary",
                "repository",
                "homepage",
                "branch",
                "runtime",
                "publish",
            )
        }
        if "blocked_reason" in app:
            resolved_app["blocked_reason"] = app["blocked_reason"]
        resolved_app["screenshots"] = app.get("screenshots", [])
        if "release_pin" in app:
            resolved_app["release_pin"] = app["release_pin"]
        resolved_app["release"] = {
            "tag": release["tag_name"],
            "release_id": release.get("id"),
            "html_url": release.get("html_url"),
            "created_at": release.get("created_at"),
            "published_at": release.get("published_at"),
            "prerelease": release.get("prerelease"),
        }
        resolved_app["assets"] = resolved_assets
        resolved_apps.append(resolved_app)
    return {
        "schema_version": 1,
        "catalog_sha256": hashlib.sha256(canonical_json_bytes(catalog)).hexdigest(),
        "remote": catalog["remote"],
        "policy": catalog["policy"],
        "apps": resolved_apps,
    }


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_asset(
    asset: dict[str, Any],
    cache_dir: pathlib.Path,
) -> pathlib.Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{asset['asset_id']}-{asset['name']}"
    if target.exists():
        if target.stat().st_size == asset["size"] and sha256_file(target) == asset["sha256"]:
            return target
        target.unlink()
    partial = target.with_name(f".{target.name}.partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(
        asset["download_url"],
        headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as sink:
            shutil.copyfileobj(response, sink, length=1024 * 1024)
    except (OSError, urllib.error.URLError) as error:
        partial.unlink(missing_ok=True)
        raise CatalogError(f"cannot download {asset['download_url']}: {error}") from error
    actual_size = partial.stat().st_size
    actual_digest = sha256_file(partial)
    if actual_size != asset["size"] or actual_digest != asset["sha256"]:
        partial.unlink(missing_ok=True)
        raise CatalogError(
            f"download verification failed for {asset['name']}: "
            f"size {actual_size}/{asset['size']}, SHA-256 {actual_digest}/{asset['sha256']}"
        )
    os.replace(partial, target)
    return target


def run_command(command: list[str], cwd: pathlib.Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise CatalogError(f"cannot execute {command[0]}: {error}") from error
    if result.returncode:
        output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise CatalogError(
            f"command failed ({result.returncode}): {' '.join(command)}"
            + (f"\n{output}" if output else "")
        )
    return result.stdout


def _metadata_component_ids(checkout: pathlib.Path) -> tuple[list[str], list[str]]:
    patterns = (
        "export/share/metainfo/*.xml",
        "export/share/appdata/*.xml",
    )
    paths = sorted({path for pattern in patterns for path in checkout.glob(pattern)})
    ids: list[str] = []
    relative_paths: list[str] = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as error:
            raise CatalogError(f"cannot parse AppStream metadata {path}: {error}") from error
        component_id = root.findtext("id")
        if component_id:
            ids.append(component_id.strip())
            relative_paths.append(path.relative_to(checkout).as_posix())
    return ids, relative_paths


def _exported_icon_paths(checkout: pathlib.Path, app_id: str) -> list[str]:
    icon_root = checkout / "export" / "share" / "icons" / "hicolor"
    paths = sorted(
        path
        for pattern in (f"*/apps/{app_id}.png", f"*/apps/{app_id}.svg")
        for path in icon_root.glob(pattern)
        if path.is_file() and path.stat().st_size > 0
    )
    return [path.relative_to(checkout).as_posix() for path in paths]


def inspect_bundle(
    bundle: pathlib.Path,
    app: dict[str, Any],
    asset: dict[str, Any],
    work_dir: pathlib.Path,
) -> dict[str, Any]:
    inspect_repo = work_dir / "inspect-repo"
    checkout = work_dir / "checkout"
    run_command(["ostree", "init", f"--repo={inspect_repo}", "--mode=archive-z2"])
    try:
        run_command(
            [
                "flatpak",
                "build-import-bundle",
                "--no-update-summary",
                str(inspect_repo),
                str(bundle),
            ]
        )
    except CatalogError as error:
        raise CatalogError(
            f"bundle import validation failed for {app['id']} {asset['arch']}: {error}"
        ) from error
    refs = sorted(
        line.strip()
        for line in run_command(["ostree", "refs", f"--repo={inspect_repo}"]).splitlines()
        if line.strip()
    )
    expected_ref = f"app/{app['id']}/{asset['arch']}/{app['branch']}"
    if refs != [expected_ref]:
        raise CatalogError(
            f"{asset['name']} embedded refs {refs!r}; expected exactly {expected_ref!r}"
        )
    run_command(
        [
            "ostree",
            "checkout",
            "--user-mode",
            f"--repo={inspect_repo}",
            expected_ref,
            str(checkout),
        ]
    )
    metadata_path = checkout / "metadata"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with metadata_path.open(encoding="utf-8") as source:
            parser.read_file(source)
    except (OSError, configparser.Error) as error:
        raise CatalogError(f"cannot parse bundle metadata for {app['id']}: {error}") from error
    embedded_id = parser.get("Application", "name", fallback=None)
    embedded_runtime = parser.get("Application", "runtime", fallback=None)
    expected_runtime = (
        f"{app['runtime']['id']}/{asset['arch']}/{app['runtime']['branch']}"
    )
    if embedded_id != app["id"]:
        raise CatalogError(
            f"{asset['name']} metadata ID {embedded_id!r}; expected {app['id']!r}"
        )
    if embedded_runtime != expected_runtime:
        raise CatalogError(
            f"{asset['name']} runtime {embedded_runtime!r}; expected {expected_runtime!r}"
        )
    component_ids, metainfo_paths = _metadata_component_ids(checkout)
    if component_ids.count(app["id"]) != 1:
        raise CatalogError(
            f"{asset['name']} must export exactly one AppStream component for {app['id']}; "
            f"found {component_ids!r}"
        )
    icon_paths = _exported_icon_paths(checkout, app["id"])
    if not icon_paths:
        raise CatalogError(
            f"{asset['name']} must export a non-empty AppStream icon for {app['id']}"
        )
    commit = run_command(
        ["ostree", "rev-parse", f"--repo={inspect_repo}", expected_ref]
    ).strip()
    if not SHA256_RE.fullmatch(commit):
        raise CatalogError(f"could not resolve imported commit for {expected_ref}")
    return {
        "ref": expected_ref,
        "commit": commit,
        "runtime": embedded_runtime,
        "metainfo": metainfo_paths,
        "icons": icon_paths,
    }


def validate_appstream_checkout(checkout: pathlib.Path, app_ids: Iterable[str],
                               screenshots: dict[str, list[dict[str, Any]]] | None = None) -> None:
    """Reject repositories whose installable refs are absent from the store catalog."""
    metadata = checkout / "appstream.xml"
    try:
        if metadata.is_file():
            root = ET.parse(metadata).getroot()
        else:
            with gzip.open(checkout / "appstream.xml.gz", "rb") as source:
                root = ET.parse(source).getroot()
    except (OSError, ET.ParseError) as error:
        raise CatalogError(f"cannot read generated AppStream catalog: {error}") from error
    components = {item.findtext("id"): item for item in root.findall("component")}
    for app_id in app_ids:
        component = components.get(app_id)
        if component is None:
            raise CatalogError(f"generated AppStream catalog is missing {app_id}")
        icons = []
        for icon in component.findall("icon"):
            if icon.get("type") != "cached" or not icon.text:
                continue
            filename = icon.text.strip()
            width, height = icon.get("width", ""), icon.get("height", "")
            if not width.isdigit() or not height.isdigit() or pathlib.PurePosixPath(filename).name != filename:
                continue
            path = checkout / "icons" / f"{width}x{height}" / filename
            try:
                path.resolve().relative_to(checkout.resolve())
            except ValueError:
                continue
            if path.is_file() and path.stat().st_size > 0:
                icons.append(path)
        if not icons:
            raise CatalogError(f"generated AppStream catalog has no cached icon for {app_id}")
        if screenshots is not None:
            actual = [image.text for image in component.findall("screenshots/screenshot/image")]
            expected = [shot["url"] for shot in screenshots[app_id]]
            if not expected or actual != expected:
                raise CatalogError(f"generated AppStream screenshots differ from the reviewed set for {app_id}")


def apply_screenshots(checkout: pathlib.Path, screenshots: dict[str, list[dict[str, Any]]]) -> None:
    """Add reviewed screenshots to repository metadata without changing app commits."""
    xml = checkout / "appstream.xml"
    compressed = checkout / "appstream.xml.gz"
    try:
        data = xml.read_bytes() if xml.exists() else gzip.decompress(compressed.read_bytes())
        root = ET.fromstring(data)
    except (OSError, ET.ParseError) as error:
        raise CatalogError(f"cannot read AppStream for screenshots: {error}") from error
    components = {component.findtext("id"): component for component in root.findall("component")}
    for app_id, shots in screenshots.items():
        component = components.get(app_id)
        if component is None or not shots:
            raise CatalogError(f"cannot add screenshots for missing or empty component {app_id}")
        for old in component.findall("screenshots"):
            component.remove(old)
        container = ET.SubElement(component, "screenshots")
        for index, shot in enumerate(shots):
            item = ET.SubElement(container, "screenshot", {"type": "default"} if index == 0 else {})
            ET.SubElement(item, "caption").text = shot["caption"]
            ET.SubElement(item, "image", {"type": "source", "width": str(shot["width"]),
                                         "height": str(shot["height"])}).text = shot["url"]
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # OSTree checkouts can use hardlinks. Replace files rather than modifying
    # their existing inodes, so the imported objects remain immutable.
    for destination, payload in ((xml, data), (compressed, gzip.compress(data, mtime=0))):
        if destination.exists():
            destination.unlink()
        destination.write_bytes(payload)


def stage_screenshots(resolved: dict[str, Any], output_dir: pathlib.Path, cache_dir: pathlib.Path) -> dict[str, list[dict[str, Any]]]:
    staged: dict[str, list[dict[str, Any]]] = {}
    screenshot_dir = output_dir / "screenshots"
    screenshot_dir.mkdir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    public_root = resolved["remote"]["descriptor_url"].rsplit("/", 1)[0]
    for app in resolved["apps"]:
        if not app["publish"]:
            continue
        staged[app["id"]] = []
        for shot in app["screenshots"]:
            filename = shot["sha256"] + ".png"
            cached = cache_dir / filename
            if not cached.exists() or sha256_file(cached) != shot["sha256"]:
                request = urllib.request.Request(shot["url"], headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(request, timeout=45) as response:
                        if not response.geturl().startswith("https://"):
                            raise CatalogError("screenshot redirect must retain HTTPS")
                        data = response.read(16 * 1024 * 1024 + 1)
                except OSError as error:
                    raise CatalogError(f"screenshot download failed for {app['id']}: {error}") from error
                if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != shot["sha256"]:
                    raise CatalogError(f"screenshot SHA-256/size mismatch for {app['id']}")
                cached.write_bytes(data)
            data = cached.read_bytes()
            if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
                raise CatalogError(f"screenshot for {app['id']} is not a PNG")
            width, height = struct.unpack(">II", data[16:24])
            if not (320 <= width <= 8192 and 200 <= height <= 8192):
                raise CatalogError(f"screenshot dimensions are invalid for {app['id']}")
            shutil.copyfile(cached, screenshot_dir / filename)
            staged[app["id"]].append({"url": f"{public_root}/screenshots/{filename}",
                                       "caption": shot["caption"], "width": width, "height": height})
        if not staged[app["id"]]:
            raise CatalogError(f"no screenshots staged for {app['id']}")
    return staged


def _export_public_key(key_id: str, gpg_homedir: pathlib.Path | None) -> bytes:
    command = ["gpg", "--batch"]
    if gpg_homedir is not None:
        command.extend(["--homedir", str(gpg_homedir)])
    command.extend(["--export", key_id])
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError as error:
        raise CatalogError(f"cannot execute gpg: {error}") from error
    if result.returncode or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CatalogError(f"cannot export GPG public key {key_id}: {detail}")
    return result.stdout


def render_flatpakrepo(remote: dict[str, Any], public_key: bytes | None) -> str:
    lines = [
        "[Flatpak Repo]",
        "Version=1",
        f"Title={remote['title']}",
        f"Url={remote['repository_url']}",
        f"Homepage={remote['repository_url'].rsplit('/flatpak-repo/', 1)[0]}/",
        f"Comment={remote['comment']}",
        f"Description={remote['description']}",
        f"Icon={remote['icon']}",
        f"DefaultBranch={remote['default_branch']}",
    ]
    if public_key is not None:
        lines.append(f"GPGKey={base64.b64encode(public_key).decode('ascii')}")
    else:
        lines.append("X-Spaced-Publishable=false")
    return "\n".join(lines) + "\n"


def render_flatpakref(
    remote: dict[str, Any], app: dict[str, Any], public_key: bytes | None
) -> str:
    """Render the preferred direct-install path for SpacedBazaar itself."""
    lines = [
        "[Flatpak Ref]",
        "Version=1",
        f"Name={app['id']}",
        f"Branch={app['branch']}",
        f"Title={app['name']}",
        f"Comment={app['summary']}",
        f"Description={remote['description']}",
        f"Icon={remote['icon']}",
        f"Homepage={app['homepage']}",
        f"Url={remote['repository_url']}",
        "IsRuntime=false",
        f"RuntimeRepo={app['runtime']['repository']}",
        f"SuggestRemoteName={remote['name']}",
    ]
    if public_key is not None:
        lines.append(f"GPGKey={base64.b64encode(public_key).decode('ascii')}")
    else:
        lines.append("X-Spaced-Publishable=false")
    return "\n".join(lines) + "\n"


def _write_index(output_dir: pathlib.Path, resolved: dict[str, Any], signed: bool) -> None:
    app_rows = []
    for app in resolved["apps"]:
        status = "Published" if app["publish"] else f"Blocked: {app['blocked_reason']}"
        app_rows.append(
            "<tr>"
            f"<td>{html.escape(app['name'])}</td>"
            f"<td><code>{html.escape(app['id'])}</code></td>"
            f"<td>{html.escape(str(app['release']['tag']))}</td>"
            f"<td>{html.escape(status)}</td>"
            "</tr>"
        )
    signature_status = "signed" if signed else "unsigned validation build"
    document = "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            '<head>',
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Spaced Linux GitHub Flatpak Repository</title>",
            '<style>body{font:16px/1.6 system-ui,sans-serif;margin:40px auto;padding:0 20px;max-width:1100px;background:#10141c;color:#f8f9fc}a{color:#92cbff}main{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:12px;text-align:left;border-bottom:1px solid #39404c}footer{margin-top:32px}</style>',
            '</head><body><main>',
            "<h1>Spaced Linux GitHub Flatpak Repository</h1>",
            f"<p>Repository status: {signature_status}.</p>",
            '<p><a href="spaced-github.flatpakrepo">Add the spaced-github remote</a></p>',
            '<p><a href="io.github.crhy.SpacedBazaar.flatpakref">Install SpacedBazaar</a></p>',
            "<table><thead><tr><th>App</th><th>ID</th><th>Release</th><th>Status</th></tr></thead><tbody>",
            *app_rows,
            "</tbody></table>",
            '<p><a href="catalog/resolved.json">View verified release metadata</a></p>',
            '</main><footer><a href="https://spacedlinux.com/help.html">Online Help</a> · <a href="https://discord.gg/BMW9Y6NB3y">Discord</a> · <a href="https://t.me/+pjmFzHo-i9A2ZWY5">Telegram</a></footer>',
            "</body></html>",
            "",
        ]
    )
    (output_dir / "index.html").write_text(document, encoding="utf-8")


def build_repository(
    catalog: dict[str, Any],
    resolved: dict[str, Any],
    output_dir: pathlib.Path,
    cache_dir: pathlib.Path,
    gpg_sign: str | None,
    gpg_homedir: pathlib.Path | None,
    require_signing: bool,
    generate_static_deltas: bool,
) -> dict[str, Any]:
    if require_signing and not gpg_sign:
        raise CatalogError("publishing requires --gpg-sign")
    if gpg_homedir is not None and not gpg_sign:
        raise CatalogError("--gpg-homedir requires --gpg-sign")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CatalogError(f"output directory must be absent or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots = stage_screenshots(resolved, output_dir, cache_dir / "screenshots")
    repo_dir = output_dir / "flatpak-repo"
    run_command(["ostree", "init", f"--repo={repo_dir}", "--mode=archive-z2"])

    imported: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="spaced-github-verify-") as temporary:
        temporary_root = pathlib.Path(temporary)
        for app in resolved["apps"]:
            if not app["publish"]:
                continue
            for asset in app["assets"]:
                bundle = download_asset(asset, cache_dir)
                asset_work = temporary_root / f"{app['id']}-{asset['arch']}"
                asset_work.mkdir()
                inspection = inspect_bundle(bundle, app, asset, asset_work)
                import_command = [
                    "flatpak",
                    "build-import-bundle",
                    "--no-update-summary",
                ]
                if gpg_sign:
                    import_command.append(f"--gpg-sign={gpg_sign}")
                    if gpg_homedir is not None:
                        import_command.append(f"--gpg-homedir={gpg_homedir}")
                import_command.extend([str(repo_dir), str(bundle)])
                run_command(import_command)
                imported.append(
                    {
                        "id": app["id"],
                        "arch": asset["arch"],
                        "release": app["release"]["tag"],
                        "asset": asset["name"],
                        "asset_sha256": asset["sha256"],
                        **inspection,
                    }
                )

    remote = catalog["remote"]
    update_command = [
        "flatpak",
        "build-update-repo",
        f"--title={remote['title']}",
        f"--comment={remote['comment']}",
        f"--description={remote['description']}",
        f"--homepage={catalog['publisher']['homepage']}",
        f"--icon={remote['icon']}",
        f"--default-branch={remote['default_branch']}",
    ]
    if generate_static_deltas:
        update_command.extend(["--generate-static-deltas", "--static-delta-jobs=2"])
    if gpg_sign:
        update_command.append(f"--gpg-sign={gpg_sign}")
        if gpg_homedir is not None:
            update_command.append(f"--gpg-homedir={gpg_homedir}")
    update_command.append(str(repo_dir))
    run_command(update_command)

    # Flatpak generates appstream and appstream2 refs for different client
    # versions. Keep both consistent, sign their new metadata commits, then
    # refresh the summary without regenerating AppStream from the bundles.
    for metadata_ref in run_command(["ostree", "refs", f"--repo={repo_dir}"]).splitlines():
        if not metadata_ref.startswith(("appstream/", "appstream2/")):
            continue
        arch = metadata_ref.split("/", 1)[1]
        selected = {app["id"]: screenshots[app["id"]] for app in resolved["apps"]
                    if app["publish"] and any(asset["arch"] == arch for asset in app["assets"])}
        with tempfile.TemporaryDirectory(prefix="spaced-github-screenshots-") as temporary:
            checkout = pathlib.Path(temporary) / "checkout"
            run_command(["ostree", "checkout", "--user-mode", f"--repo={repo_dir}", metadata_ref, str(checkout)])
            apply_screenshots(checkout, selected)
            command = ["ostree", "commit", f"--repo={repo_dir}", f"--branch={metadata_ref}",
                       "--subject=Publish reviewed application screenshots", f"--tree=dir={checkout}"]
            if gpg_sign:
                command.append(f"--gpg-sign={gpg_sign}")
                if gpg_homedir is not None:
                    command.append(f"--gpg-homedir={gpg_homedir}")
            run_command(command)
    run_command(update_command[:-1] + ["--no-update-appstream", str(repo_dir)])

    refs = sorted(
        line.strip()
        for line in run_command(["ostree", "refs", f"--repo={repo_dir}"]).splitlines()
        if line.strip()
    )
    expected_refs = sorted(item["ref"] for item in imported)
    missing_refs = sorted(set(expected_refs) - set(refs))
    if missing_refs:
        raise CatalogError(f"generated repository is missing imported refs: {missing_refs}")
    published_arches = sorted({item["arch"] for item in imported})
    for arch in published_arches:
        appstream_ref = next((ref for ref in (f"appstream2/{arch}", f"appstream/{arch}") if ref in refs), None)
        if appstream_ref is None:
            raise CatalogError(f"generated repository has no AppStream branch for {arch}")
        with tempfile.TemporaryDirectory(prefix="spaced-github-appstream-") as temporary:
            checkout = pathlib.Path(temporary) / "checkout"
            run_command([
                "ostree", "checkout", "--user-mode", f"--repo={repo_dir}",
                appstream_ref, str(checkout),
            ])
            validate_appstream_checkout(
                checkout, (item["id"] for item in imported if item["arch"] == arch), screenshots
            )

    public_key = _export_public_key(gpg_sign, gpg_homedir) if gpg_sign else None
    if require_signing and public_key is None:
        raise CatalogError("publishing requires an exported GPG public key")
    descriptor = render_flatpakrepo(remote, public_key)
    (output_dir / "spaced-github.flatpakrepo").write_text(descriptor, encoding="utf-8")
    bazaar_apps = [
        app
        for app in catalog["apps"]
        if app["id"] == "io.github.crhy.SpacedBazaar" and app["publish"]
    ]
    if len(bazaar_apps) != 1:
        raise CatalogError("catalog must contain one publishable SpacedBazaar app")
    flatpakref = render_flatpakref(remote, bazaar_apps[0], public_key)
    (output_dir / "io.github.crhy.SpacedBazaar.flatpakref").write_text(
        flatpakref, encoding="utf-8"
    )
    catalog_dir = output_dir / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "crhy-flatpaks.json").write_bytes(canonical_json_bytes(catalog))
    (catalog_dir / "resolved.json").write_bytes(canonical_json_bytes(resolved))
    report = {
        "schema_version": 1,
        "remote": remote["name"],
        "signed": public_key is not None,
        "published_arches": published_arches,
        "imported": sorted(imported, key=lambda item: (item["id"], item["arch"])),
        "refs": refs,
        "screenshots": screenshots,
    }
    (output_dir / "build-report.json").write_bytes(canonical_json_bytes(report))
    _write_index(output_dir, resolved, public_key is not None)
    return report


def _path(value: str) -> pathlib.Path:
    return pathlib.Path(value).expanduser().resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=_path,
        default=_path("catalog/crhy-flatpaks.json"),
        help="normalized catalog (default: catalog/crhy-flatpaks.json)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate catalog invariants without network access")

    resolve_parser = subparsers.add_parser(
        "resolve", help="resolve stable releases and explicitly reviewed release pins"
    )
    resolve_parser.add_argument("--output", type=_path, required=True)
    resolve_parser.add_argument(
        "--release-metadata-dir",
        type=_path,
        help="read deterministic GitHub API fixtures instead of the network",
    )

    build = subparsers.add_parser(
        "build", help="resolve, verify, and build the Flatpak OSTree repository"
    )
    build.add_argument("--output-dir", type=_path, required=True)
    build.add_argument("--cache-dir", type=_path, required=True)
    build.add_argument("--release-metadata-dir", type=_path)
    build.add_argument("--gpg-sign", help="GPG key ID used to sign commits and summary")
    build.add_argument("--gpg-homedir", type=_path)
    build.add_argument(
        "--require-signing",
        action="store_true",
        help="fail unless a signing key is supplied (mandatory for publication)",
    )
    build.add_argument(
        "--no-static-deltas",
        action="store_true",
        help="skip static deltas for local diagnostics",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.command == "validate":
            print(f"catalog valid: {len(catalog['apps'])} apps")
            return 0
        token = os.environ.get("GITHUB_TOKEN")
        resolved = resolve_catalog(catalog, args.release_metadata_dir, token)
        if args.command == "resolve":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical_json_bytes(resolved))
            print(f"resolved {len(resolved['apps'])} apps into {args.output}")
            return 0
        report = build_repository(
            catalog,
            resolved,
            args.output_dir,
            args.cache_dir,
            args.gpg_sign,
            args.gpg_homedir,
            args.require_signing,
            not args.no_static_deltas,
        )
        print(
            f"built {report['remote']} with {len(report['imported'])} app refs "
            f"(signed={str(report['signed']).lower()})"
        )
        return 0
    except CatalogError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
