#!/usr/bin/env python3
"""Fail when the screenshots this repository publishes are not at least half dark.

crhy/spacedbazaar#15: "Better to have at LEAST a 50/50 mix of dark mode, since
we are a dark mode by default OS."  What a reader sees is the README gallery plus
the AppStream metainfo, so this script measures exactly that set with
`scripts/png_luminance.py` and exits non-zero unless at least half of it is
dark.  Nothing is eyeballed and nothing is recoloured: a capture only counts as
dark when the pixels committed here say so.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import png_luminance  # noqa: E402

README = REPOSITORY_ROOT / "README.md"
METAINFO = REPOSITORY_ROOT / "data" / "io.github.crhy.SpacedBazaar.metainfo.xml.in"
GALLERY_IMAGE = '<img src="screenshots/([^"]+)"'


def readme_screenshots() -> list[str]:
    """Screenshot files the README gallery shows, in the order a reader sees them."""

    return re.findall(GALLERY_IMAGE, README.read_text(encoding="utf-8"))


def metainfo_screenshots() -> list[str]:
    """Screenshot files Flathub would show for SpacedBazaar itself."""

    root = ET.parse(str(METAINFO)).getroot()
    names = []
    for image in root.iter("image"):
        url = (image.text or "").strip()
        if "/screenshots/" not in url:
            continue
        names.append(url.split("/screenshots/", 1)[1])
    return names


def published_set() -> dict[str, list[str]]:
    """Map every published screenshot path to the surfaces that publish it."""

    published: dict[str, list[str]] = {}
    for name in readme_screenshots():
        published.setdefault(f"screenshots/{name}", []).append("README")
    for name in metainfo_screenshots():
        published.setdefault(f"screenshots/{name}", []).append("metainfo")
    return published


def main() -> int:
    published = published_set()
    if not published:
        print("no published screenshots found to measure", file=sys.stderr)
        return 1

    failures: list[str] = []
    rows: list[tuple[str, str, float, bool]] = []
    seen_captures: dict[str, str] = {}

    for name, surfaces in published.items():
        path = REPOSITORY_ROOT / name
        if not path.is_file():
            failures.append(f"{name} is published but not committed")
            continue
        try:
            luminance, capture = png_luminance.measure(path)
        except png_luminance.PNGError as error:
            failures.append(f"{name}: {error}")
            continue
        if capture in seen_captures:
            failures.append(
                f"{name} holds the same pixels as {seen_captures[capture]}: "
                "one view may not be counted twice under two names"
            )
            continue
        seen_captures[capture] = name
        rows.append((name, "+".join(dict.fromkeys(surfaces)), luminance,
                     png_luminance.is_dark(luminance)))

    print(f"{'screenshot':50s} {'published in':12s} {'luminance':11s} mode")
    for name, surface, luminance, dark in rows:
        print(f"{name:50s} {surface:12s} {luminance:11.3f} "
              f"{'dark' if dark else 'light'}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    dark_count = sum(1 for row in rows if row[3])
    total = len(rows)
    print(f"\n{dark_count} of {total} published screenshots are dark "
          f"({100 * dark_count // total}%), threshold "
          f"{png_luminance.DARK_THRESHOLD:g}")

    if dark_count * 2 < total:
        print(
            "FAIL: the published screenshot set is not at least half dark. "
            "Spaced Linux ships a dark desktop by default (crhy/spacedbazaar#15); "
            "re-curate the README gallery to captures already committed under "
            "screenshots/ instead of recolouring a light one.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
