#!/bin/sh

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
manifest="$repo_root/build-aux/flatpak/io.github.crhy.SpacedBazaar.json"

python3 - "$manifest" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
finish_args = manifest["finish-args"]

assert manifest["id"] == "io.github.crhy.SpacedBazaar"
assert "--filesystem=xdg-data/flatpak" in finish_args
assert not any("/home/" in arg for arg in finish_args)
assert not any(arg.startswith("--env=FLATPAK_USER_DIR=") for arg in finish_args)
PY

version=$($repo_root/version.sh get-version)
release_url=$($repo_root/version.sh get-gh-release)

test "$version" = "0.2.0"
test "$release_url" = "https://github.com/crhy/spacedbazaar/releases/tag/0.2.0"

grep -q 'installation == self->user' "$repo_root/src/bz-flatpak-instance.c" || {
    echo "user-installation source enumeration fix is missing" >&2
    exit 1
}

grep -q 'bz_flatpak_entry_is_user' "$repo_root/src/bz-window.c" || {
    echo "user-installation selection fix is missing" >&2
    exit 1
}

grep -q 'prefer_user_installation (store)' "$repo_root/src/bz-transaction-dialog.c" || {
    echo "user-only install dialog fix is missing" >&2
    exit 1
}

grep -Fq 'SpacedBazaar-${{ matrix.variant.arch }}.flatpak' "$repo_root/.github/workflows/build-flatpak.yml" || {
    echo "architecture-specific release bundle naming is missing" >&2
    exit 1
}

grep -Fq -- '--repo-url=https://crhy.github.io/spacedbazaar/flatpak-repo/' \
    "$repo_root/.github/workflows/build-flatpak.yml" || {
    echo "release bundle does not point back to spaced-github" >&2
    exit 1
}

grep -Fq -- '--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo' \
    "$repo_root/.github/workflows/build-flatpak.yml" || {
    echo "release bundle does not identify the Flathub runtime source" >&2
    exit 1
}

grep -q 'transaction_progress_button' "$repo_root/src/bz-window.blp" || {
    echo "global transaction progress indicator is missing" >&2
    exit 1
}

grep -q 'app_transaction_progress_button' "$repo_root/src/bz-full-view.blp" || {
    echo "app-page transaction progress indicator is missing" >&2
    exit 1
}

grep -q 'g_strcmp0 (priv->remote_repo_name, "spaced-github")' "$repo_root/src/bz-entry.c" || {
    echo "spaced-github source preference is missing" >&2
    exit 1
}

grep -q 'score += 2000' "$repo_root/src/bz-entry.c" || {
    echo "spaced-github must be preferred over the Flathub usefulness boost" >&2
    exit 1
}

grep -q 'name: "updating"' "$repo_root/src/bz-flathub-page.blp" || {
    echo "first-sync catalog loading page is missing" >&2
    exit 1
}

grep -q 'Updating app catalog from Flathub and Spaced GitHub' "$repo_root/src/bz-flathub-page.blp" || {
    echo "first-sync catalog message is missing" >&2
    exit 1
}

grep -q '"notify::syncing"' "$repo_root/src/bz-flathub-page.c" || {
    echo "first-sync page does not react to synchronization state" >&2
    exit 1
}

test -x "$repo_root/scripts/spaced_github_repo.py"
test -x "$repo_root/scripts/configure-spaced-github-remote.sh"
sh -n "$repo_root/scripts/configure-spaced-github-remote.sh"
python3 "$repo_root/scripts/spaced_github_repo.py" \
    --catalog "$repo_root/catalog/crhy-flatpaks.json" validate
python3 -m unittest discover -s "$repo_root/tests" -v

grep -q 'SPACED_FLATPAK_GPG_PRIVATE_KEY_B64' \
    "$repo_root/.github/workflows/publish-spaced-github-repo.yml" || {
    echo "signed repository publication gate is missing" >&2
    exit 1
}

grep -q -- '--require-signing' \
    "$repo_root/.github/workflows/publish-spaced-github-repo.yml" || {
    echo "publication does not require repository signing" >&2
    exit 1
}

echo "SpacedBazaar fork checks passed ($version)"
