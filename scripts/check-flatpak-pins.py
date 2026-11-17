#!/usr/bin/env python3
"""Compare the Flatpak manifest's pins against the reviewed pin records.

The manifest lets the Flatpak External Data Checker move its git sources, and
that checker opens a pull request which edits the ``tag`` and the ``commit``
lines of one source.  A pull request, or a hand edit, that moves only one of
the two lines leaves the module half-updated: the tag says one release and the
commit builds another.  Every source carrying ``x-checker-data`` must therefore
carry both a tag and a full 40-character commit, and both must match the
reviewed record in ``catalog/flatpak-pins.json``.

No network access is used: this only compares the two files in the checkout.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any


COMMIT_LENGTH = 40
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")
REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]


class PinError(RuntimeError):
    """A manifest, a reviewed record file, or a pin was unusable."""


def _load_json(path: pathlib.Path, context: str) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as error:
        raise PinError(f"{context} {path} could not be read: {error}") from error
    except json.JSONDecodeError as error:
        raise PinError(f"{context} {path} is not valid JSON: {error}") from error


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PinError(f"{context} must be an object")
    return value


def _require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise PinError(f"{context} must be an array")
    return value


def iter_pinned_sources(manifest: Any) -> list[dict[str, Any]]:
    """Return every git source the external data checker is allowed to move.

    Nested modules are walked as deep as the manifest nests them, which is
    where ostree (under polkit, under flatpak, under bazaar) lives.
    """

    root = _require_mapping(manifest, "manifest")
    pins: list[dict[str, Any]] = []

    def walk(modules: Any) -> None:
        for entry in _require_list(modules, "modules"):
            module = _require_mapping(entry, "module")
            name = module.get("name") or "(unnamed module)"
            for source in _require_list(module.get("sources", []), f"{name} sources"):
                source = _require_mapping(source, f"{name} source")
                if "x-checker-data" not in source:
                    continue
                if source.get("type") != "git":
                    continue
                pins.append(
                    {
                        "module": name,
                        "url": source.get("url") or "(no url)",
                        "tag": source.get("tag"),
                        "commit": source.get("commit"),
                    }
                )
            walk(module.get("modules", []))

    walk(root.get("modules", []))
    return pins


def load_reviewed_pins(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    reviewed = _require_mapping(_load_json(path, "reviewed pin file"), "reviewed pin file")
    pins: dict[str, dict[str, Any]] = {}
    for entry in _require_list(reviewed.get("pins", []), "reviewed pins"):
        record = _require_mapping(entry, "reviewed pin record")
        url = record.get("url")
        if not isinstance(url, str) or not url:
            raise PinError(f"reviewed pin record in {path} has no url")
        if url in pins:
            raise PinError(f"reviewed pin file {path} lists {url} twice")
        pins[url] = {
            "name": record.get("name") or "(unnamed)",
            "tag": record.get("tag"),
            "commit": record.get("commit"),
        }
    return pins


def _describe_commit(commit: Any) -> str | None:
    """Return the problem with a commit value, or None when it is a full hash."""

    if not isinstance(commit, str) or not commit:
        return "has no commit"
    if not HEX_RE.match(commit):
        return f"commit {commit!r} is not lowercase hexadecimal"
    if len(commit) != COMMIT_LENGTH:
        return f"commit {commit} is {len(commit)} characters, not {COMMIT_LENGTH}"
    return None


def compare_pins(
    pins: list[dict[str, Any]], reviewed: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    """Return one row per pin, each carrying either 'ok' or its problems."""

    rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for pin in pins:
        url = pin["url"]
        seen_urls.add(url)
        tag = pin["tag"]
        commit = pin["commit"]
        problems: list[str] = []

        if not isinstance(tag, str) or not tag:
            problems.append("has no tag")

        commit_problem = _describe_commit(commit)
        if commit_problem is not None:
            problems.append(commit_problem)

        record = reviewed.get(url)
        if record is None:
            problems.append("no reviewed record for this source")
        else:
            if isinstance(tag, str) and isinstance(record["tag"], str) and tag != record["tag"]:
                problems.append(f"tag {tag} differs from reviewed {record['tag']}")
            if isinstance(commit, str) and FULL_COMMIT_RE.match(commit) and commit != record["commit"]:
                problems.append(f"commit {commit} differs from reviewed {record['commit']}")
            if isinstance(record["commit"], str) and not FULL_COMMIT_RE.match(record["commit"]):
                problems.append(f"reviewed commit {record['commit']} is not a full hash")

        tag_differs = record is not None and isinstance(tag, str) and tag != record["tag"]
        commit_differs = (
            record is not None
            and isinstance(commit, str)
            and FULL_COMMIT_RE.match(commit)
            and commit != record["commit"]
        )
        if commit_differs and not tag_differs:
            problems.append("half-moved: tag moved, commit left behind")
        if tag_differs and not commit_differs:
            problems.append("half-moved: commit moved, tag left behind")

        rows.append(
            {
                "module": pin["module"],
                "url": url,
                "tag": str(tag) if tag is not None else "-",
                "commit": str(commit) if commit is not None else "-",
                "reviewed_tag": "-" if record is None else str(record["tag"]),
                "reviewed_commit": "-" if record is None else str(record["commit"]),
                "problem": "; ".join(problems) if problems else "ok",
            }
        )

    for url, record in reviewed.items():
        if url not in seen_urls:
            rows.append(
                {
                    "module": record["name"],
                    "url": url,
                    "tag": "-",
                    "commit": "-",
                    "reviewed_tag": str(record["tag"]),
                    "reviewed_commit": str(record["commit"]),
                    "problem": "reviewed record is not pinned by the manifest",
                }
            )
    return rows


def format_table(rows: list[dict[str, str]]) -> str:
    headers = {
        "module": "module",
        "url": "source",
        "tag": "tag",
        "commit": "commit",
        "reviewed_tag": "reviewed tag",
        "reviewed_commit": "reviewed commit",
        "problem": "problem",
    }
    keys = list(headers)
    widths = {key: len(headers[key]) for key in keys}
    for row in rows:
        for key in keys:
            widths[key] = max(widths[key], len(row[key]))

    lines = ["  ".join(headers[key].ljust(widths[key]) for key in keys).rstrip()]
    lines.append("  ".join("-" * widths[key] for key in keys))
    for row in rows:
        lines.append("  ".join(row[key].ljust(widths[key]) for key in keys).rstrip())
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=REPOSITORY_ROOT / "build-aux/flatpak/io.github.crhy.SpacedBazaar.json",
        help="Flatpak manifest to check",
    )
    parser.add_argument(
        "--pins",
        type=pathlib.Path,
        default=REPOSITORY_ROOT / "catalog/flatpak-pins.json",
        help="reviewed pin records to compare against",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        pins = iter_pinned_sources(_load_json(args.manifest, "manifest"))
        reviewed = load_reviewed_pins(args.pins)
    except PinError as error:
        parser.exit(1, f"error: {error}\n")

    if not pins:
        parser.exit(
            1,
            f"error: {args.manifest} pins no git source with x-checker-data; "
            "the checker walk found nothing\n",
        )

    rows = compare_pins(pins, reviewed)
    failures = [row for row in rows if row["problem"] != "ok"]
    print(format_table(rows))
    if failures:
        print(
            f"flatpak pins: {len(pins)} pinned source(s), "
            f"{len(reviewed)} reviewed record(s), {len(failures)} problem(s)"
        )
        return 1
    print(
        f"flatpak pins ok: {len(pins)} pinned source(s) match "
        f"{len(reviewed)} reviewed record(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
