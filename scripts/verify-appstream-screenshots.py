#!/usr/bin/python3
"""Fail the publication if any advertised screenshot cannot be fetched.

A screenshot that 404s is indistinguishable, in the store, from an application
that simply has no screenshots. Two separate causes produced exactly that in
the published repository: Voice2Text AI's build rewrote every screenshot URL
to Flathub's media CDN even though the application is published here rather
than on Flathub, and SpacedBazaar's older metadata pointed at
github.com/user-attachments, which refuses non-browser clients. Both shipped
because nothing ever asked whether the URLs resolved.

Usage: verify-appstream-screenshots.py <repository-root> [public-base-url]

A screenshot the publication rehosts itself is not on the network yet when
this runs, so when a base URL is given, URLs under it are resolved against the
built tree instead of fetched.
"""

from __future__ import annotations

import gzip
import pathlib
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

TIMEOUT = 30
# Some hosts reject the default urllib agent outright, which would make this
# check fail for a URL a browser can load. Ask the way a browser would.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) spaced-appstream-screenshot-check"


def appstream_documents(root: pathlib.Path):
    for path in sorted(root.rglob("appstream.xml*")):
        if path.suffix == ".gz":
            # A directory usually carries both forms; the plain file is enough.
            if path.with_suffix("").exists():
                continue
            with gzip.open(path, "rb") as stream:
                yield path, ET.parse(stream)
        else:
            yield path, ET.parse(path)


def screenshot_urls(document):
    for component in document.getroot():
        component_id = (component.findtext("id") or "").strip()
        screenshots = component.find("screenshots")
        if screenshots is None:
            continue
        for screenshot in screenshots:
            for image in screenshot.findall("image"):
                if image.text and image.text.strip():
                    yield component_id, image.text.strip()


def reachable(url):
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status == 200:
                return None
            return f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        # A HEAD refusal is not proof the image is missing; confirm with GET.
        if error.code in (403, 405):
            try:
                get = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(get, timeout=TIMEOUT) as response:
                    if response.status == 200:
                        response.read(1)
                        return None
                    return f"HTTP {response.status}"
            except OSError as retry_error:
                return str(retry_error)
        return f"HTTP {error.code}"
    except OSError as error:
        return str(error)


def local_target(url, base_url, root):
    """Path inside the built tree for a URL this publication hosts itself."""
    if not base_url:
        return None
    prefix = base_url if base_url.endswith("/") else base_url + "/"
    if not url.startswith(prefix):
        return None
    return root / url[len(prefix):]


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    root = pathlib.Path(argv[1])
    base_url = argv[2] if len(argv) == 3 else ""
    checked = 0
    failures = []
    seen = set()
    for path, document in appstream_documents(root):
        for component_id, url in screenshot_urls(document):
            if url in seen:
                continue
            seen.add(url)
            checked += 1
            target = local_target(url, base_url, root)
            if target is not None:
                problem = None if target.is_file() and target.stat().st_size > 0 \
                    else "not present in the built repository"
            else:
                problem = reachable(url)
            if problem is None:
                print(f"ok    {component_id} {url}")
            else:
                print(f"FAIL  {component_id} {url} -> {problem}")
                failures.append((component_id, url, problem))
        print(f"checked {path}")
    if not checked:
        print("no screenshots found in the published AppStream", file=sys.stderr)
        return 1
    print(f"\n{checked - len(failures)}/{checked} advertised screenshots are reachable")
    if failures:
        print("Publication would advertise unreachable screenshots:", file=sys.stderr)
        for component_id, url, problem in failures:
            print(f"  {component_id}: {url} ({problem})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
