#!/bin/sh

set -eu

remote_name=spaced-github
descriptor_url=https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo
repository_url=https://crhy.github.io/spacedbazaar/flatpak-repo/
priority=10
scope=--user

usage() {
    echo "Usage: $0 [--user|--system]" >&2
    exit 2
}

if [ "$#" -gt 1 ]; then
    usage
fi
if [ "$#" -eq 1 ]; then
    case "$1" in
        --user|--system)
            scope=$1
            ;;
        *)
            usage
            ;;
    esac
fi

run_flatpak() {
    if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null 2>&1; then
        flatpak-spawn --host flatpak "$@"
    else
        flatpak "$@"
    fi
}

command -v flatpak >/dev/null 2>&1 ||
    { [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null 2>&1; } || {
        echo "Flatpak is required to configure $remote_name." >&2
        exit 1
    }

if ! remotes=$(run_flatpak remotes "$scope" --columns=name,url); then
    echo "Could not inspect Flatpak remotes ($scope)." >&2
    exit 1
fi
existing_url=$(printf '%s\n' "$remotes" | awk -F '\t' -v name="$remote_name" '$1 == name { print $2 }')
remote_present=$(printf '%s\n' "$remotes" | awk -F '\t' -v name="$remote_name" '$1 == name { print "yes" }')
if [ -n "$remote_present" ]; then
    if [ "${existing_url%/}" != "${repository_url%/}" ]; then
        echo "$remote_name has an unexpected URL; repair it before configuring this source." >&2
        exit 1
    fi
    run_flatpak remote-modify "$scope" \
        --gpg-verify \
        --prio="$priority" \
        --enable \
        --enumerate \
        --use-for-deps \
        --update-metadata \
        "$remote_name"
else
    run_flatpak remote-add "$scope" \
        --noninteractive \
        --if-not-exists \
        --prio="$priority" \
        --from \
        "$remote_name" \
        "$descriptor_url"
fi

echo "$remote_name is configured at priority $priority ($scope)."
