#!/usr/bin/env python3
"""Offline pin checker for crhy/spacedbazaar#37 (flatpak + python3-babel bumps).

Parses build-aux/flatpak/io.github.crhy.SpacedBazaar.json without network
access and fails (non-zero exit) unless:

  (a) the flatpak git module source pins tag 1.18.6 at the full 40-char
      commit 7a986ba376d9e2fd8857b0afcdf5d171ef733b1f,
  (b) the python3-babel pypi file source url ends with babel-2.19.0.tar.gz
      and its sha256 is fddd2cbbbac7c299af3c2880be23609c331bd94f0912baca6cb0abfe054dfc27,
  (c) the ostree tag is still v2026.4 and the polkit tag is still 127 (those
      two bumps belong to strata/f098-spacedbazaar-ostree-polkit-pins),
  (d) every other x-checker-data source (md4c, xdg-dbus-proxy, bubblewrap,
      pyparsing, flit_core) is unchanged.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    REPOSITORY_ROOT / "build-aux" / "flatpak" / "io.github.crhy.SpacedBazaar.json"
)

FLATPAK_TAG = "1.18.6"
FLATPAK_COMMIT = "7a986ba376d9e2fd8857b0afcdf5d171ef733b1f"
BABEL_URL_SUFFIX = "babel-2.19.0.tar.gz"
BABEL_SHA256 = "fddd2cbbbac7c299af3c2880be23609c331bd94f0912baca6cb0abfe054dfc27"

# Left for strata/f098-spacedbazaar-ostree-polkit-pins; must stay put here.
OSTREE_TAG = "v2026.4"
POLKIT_TAG = "127"

# Issue #37 does not touch these x-checker-data sources; they must be unchanged.
UNCHANGED_GIT = {
    "md4c": ("472c417005c2c71b8617de4f7b8d6b30411d78f4", "release-0.5.3"),
    "xdg-dbus-proxy": ("72b40c8f6d9d585cfbdb249690724f740d207087", "0.1.9"),
    "bubblewrap": ("362936aea0d5c6e70f7af75d2d44b5a914cb4ba2", "v0.13.1"),
}
UNCHANGED_FILE_URLS = [
    (
        "pyparsing-3.3.3.tar.gz",
        "928ae7e20211f3b6f3915a72f06a0cfd29ab9d24279dd6346b6b1a7146397d36",
    ),
    (
        "flit_core-3.12.0.tar.gz",
        "18f63100d6f94385c6ed57a72073443e1a71a4acb4339491615d0f16d6ff01b2",
    ),
]


def iter_modules(manifest: dict):
    def walk(modules: list):
        for module in modules:
            yield module
            yield from walk(module.get("modules", []))

    yield from walk(manifest.get("modules", []))


def module_by_name(manifest: dict, name: str):
    for module in iter_modules(manifest):
        if module.get("name") == name:
            return module
    return None


def git_source(module):
    if module is None:
        return None
    for source in module.get("sources", []):
        if source.get("type") == "git":
            return source
    return None


def file_sources(module):
    if module is None:
        return []
    return [s for s in module.get("sources", []) if s.get("type") == "file"]


def check_manifest(manifest: dict) -> list[str]:
    """Return a list of failure reasons; empty list means every pin is right."""
    failures: list[str] = []

    def check(reason: str, ok: bool, row: str) -> None:
        print(f"{row}: {'ok' if ok else 'MISMATCH'}")
        if not ok:
            failures.append(reason)

    flatpak = git_source(module_by_name(manifest, "flatpak"))
    tag = (flatpak or {}).get("tag")
    commit = (flatpak or {}).get("commit", "")
    check(
        "flatpak git source must pin tag 1.18.6 at full commit "
        + FLATPAK_COMMIT,
        tag == FLATPAK_TAG
        and re.fullmatch(r"[0-9a-f]{40}", commit) is not None
        and commit == FLATPAK_COMMIT,
        f"flatpak git source: tag={tag} commit={commit}",
    )

    babel = [
        s
        for s in file_sources(module_by_name(manifest, "python3-babel"))
        if str(s.get("url", "")).endswith("/" + BABEL_URL_SUFFIX)
    ]
    babel_sha = babel[0].get("sha256") if babel else None
    check(
        "python3-babel file source must be "
        + BABEL_URL_SUFFIX
        + " with sha256 "
        + BABEL_SHA256,
        len(babel) == 1 and babel_sha == BABEL_SHA256,
        f"python3-babel file source: url suffix {BABEL_URL_SUFFIX} sha256={babel_sha}",
    )

    ostree = git_source(module_by_name(manifest, "ostree"))
    check(
        f"ostree tag must stay {OSTREE_TAG} (bumped on the f098 branch)",
        (ostree or {}).get("tag") == OSTREE_TAG,
        f"ostree git source: tag={(ostree or {}).get('tag')}",
    )

    polkit = git_source(module_by_name(manifest, "polkit"))
    check(
        f"polkit tag must stay {POLKIT_TAG} (bumped on the f098 branch)",
        (polkit or {}).get("tag") == POLKIT_TAG,
        f"polkit git source: tag={(polkit or {}).get('tag')}",
    )

    for name, (commit_expected, tag_expected) in UNCHANGED_GIT.items():
        source = git_source(module_by_name(manifest, name))
        check(
            f"{name} git source must stay at {tag_expected} @ {commit_expected}",
            (source or {}).get("commit") == commit_expected
            and (source or {}).get("tag") == tag_expected,
            f"{name} git source: tag={(source or {}).get('tag')} "
            f"commit={(source or {}).get('commit')}",
        )

    pyparsing_sources = file_sources(module_by_name(manifest, "python3-pyparsing"))
    for suffix, sha_expected in UNCHANGED_FILE_URLS:
        matches = [
            s
            for s in pyparsing_sources
            if str(s.get("url", "")).endswith("/" + suffix)
        ]
        check(
            f"python3-pyparsing file source must stay at {suffix} "
            f"with sha256 {sha_expected}",
            len(matches) == 1 and matches[0].get("sha256") == sha_expected,
            f"python3-pyparsing file source: {suffix} "
            f"sha256={(matches[0].get('sha256') if matches else None)}",
        )

    return failures


def main(argv: list[str]) -> int:
    manifest_path = pathlib.Path(argv[1]) if len(argv) > 1 else MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = check_manifest(manifest)
    if failures:
        for reason in failures:
            print(f"check-bump-37: FAIL: {reason}", file=sys.stderr)
        return 1
    print("flatpak 1.18.6 and babel 2.19.0 pinned; ostree/polkit left for f098.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
