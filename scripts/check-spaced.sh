#!/bin/sh

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
manifest="$repo_root/build-aux/flatpak/io.github.kolunmi.Bazaar.json"

python3 - "$manifest" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
finish_args = manifest["finish-args"]

assert "--filesystem=xdg-data/flatpak" in finish_args
assert not any("/home/" in arg for arg in finish_args)
assert not any(arg.startswith("--env=FLATPAK_USER_DIR=") for arg in finish_args)
PY

version=$($repo_root/version.sh get-version)
release_url=$($repo_root/version.sh get-gh-release)

test "$version" = "0.9.4"
test "$release_url" = "https://github.com/crhy/spacedbazaar/releases/tag/0.9.4-spaced1"

grep -q 'installation == self->user' "$repo_root/src/bz-flatpak-instance.c" || {
    echo "user-installation source enumeration fix is missing" >&2
    exit 1
}

grep -q 'bz_flatpak_entry_is_user' "$repo_root/src/bz-window.c" || {
    echo "user-installation selection fix is missing" >&2
    exit 1
}

echo "SpacedBazaar fork checks passed ($version)"
