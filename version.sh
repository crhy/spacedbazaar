#!/bin/sh

INSTR="$1"

VERSION=0.1.1
RELEASE_TAG=0.1.1
CACHE_VERSION=2

case "$INSTR" in
    get-version)
        echo "${VERSION}"
        ;;
    get-vcs)
        VCS_VERSION="$(git -C "$MESON_SOURCE_ROOT" describe --always --dirty)"
        if [ -n "$VCS_VERSION" ]; then
            echo "${VERSION} (vcs=${VCS_VERSION})"
        else
            echo "${VERSION}"
        fi
        ;;
    get-gh-release)
        TAG="${RELEASE_TAG}"
        echo "https://github.com/crhy/spacedbazaar/releases/tag/${TAG}"
        ;;
    get-cache)
        echo "${CACHE_VERSION}"
        ;;
    *)
        echo invalid arguments 1>&2
        exit 1
        ;;
esac
