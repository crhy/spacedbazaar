#!/usr/bin/env python3
"""Gate for crhy/spacedbazaar#17: the rhYciv catalog entry must carry a real
gameplay screenshot set.

Fails (exit non-zero) unless io.github.crhy.rhYciv has at least 5 screenshot
entries whose URLs all share one spacedbazaar commit SHA, whose referenced
screenshots/ files exist, decode as PNGs of at least 1200x800, differ pairwise
(pixel-diff mean >= 0.02), and whose recorded sha256 matches the file.
"""

import hashlib
import itertools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog" / "crhy-flatpaks.json"
APP_ID = "io.github.crhy.rhYciv"
URL_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/crhy/spacedbazaar/([0-9a-f]{40})/screenshots/([^/]+\.png)$"
)
MIN_WIDTH, MIN_HEIGHT = 1200, 800
MIN_DIFF = 0.02
MIN_ENTRIES = 5


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        fail("Pillow (PIL) is required to run this check")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    app = next(
        (a for a in catalog.get("apps", []) if a.get("id") == APP_ID),
        None,
    )
    if app is None:
        fail(f"no {APP_ID} entry in {CATALOG.name}")

    shots = app.get("screenshots", [])
    if len(shots) < MIN_ENTRIES:
        fail(f"{APP_ID} has {len(shots)} screenshots, need at least {MIN_ENTRIES}")

    files = []
    shas = set()
    for shot in shots:
        match = URL_RE.match(shot.get("url", ""))
        if not match:
            fail(f"unexpected screenshot url: {shot.get('url')!r}")
        commit, name = match.groups()
        shas.add(commit)
        files.append((name, shot))
    if len(shas) != 1:
        fail(f"screenshot urls span {len(shas)} commit SHAs, must share exactly one")

    arrays = {}
    for name, shot in files:
        path = ROOT / "screenshots" / name
        if not path.is_file():
            fail(f"screenshots/{name} referenced by the catalog does not exist")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != shot.get("sha256"):
            fail(f"sha256 of screenshots/{name} does not match the catalog entry")
        try:
            with Image.open(path) as image:
                if image.format != "PNG":
                    fail(f"screenshots/{name} is a {image.format}, not a PNG")
                if image.width < MIN_WIDTH or image.height < MIN_HEIGHT:
                    fail(
                        f"screenshots/{name} is {image.width}x{image.height}, "
                        f"need at least {MIN_WIDTH}x{MIN_HEIGHT}"
                    )
                rgb = image.convert("RGB")
                arrays[name] = (rgb.size, rgb.load())
        except Exception as error:  # noqa: BLE001
            fail(f"screenshots/{name} does not decode as a PNG: {error}")

    for a, b in itertools.combinations(files, 2):
        na, nb = a[0], b[0]
        (width, height), ia = arrays[na]
        size_b, ib = arrays[nb]
        if size_b != (width, height):
            fail(f"screenshots/{na} and screenshots/{nb} have different sizes")
        total = 0
        samples = 0
        for y in range(height):
            for x in range(0, width, 4):  # sampled pixel-diff mean
                pa, pb = ia[x, y], ib[x, y]
                total += abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])
                samples += 3
        diff = total / (samples * 255.0)
        if diff < MIN_DIFF:
            fail(
                f"screenshots/{na} and screenshots/{nb} are near-duplicates "
                f"(pixel-diff mean {diff:.4f} < {MIN_DIFF})"
            )

    print(f"OK: {APP_ID} has {len(files)} screenshots, all distinct, "
          f"valid PNGs >= {MIN_WIDTH}x{MIN_HEIGHT}, all urls on one commit")


if __name__ == "__main__":
    main()
