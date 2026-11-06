#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test_build=$(mktemp -d)
trap 'rm -rf "$test_build"' EXIT
cc -Wall -Wextra -Wno-unused-parameter -Wno-deprecated-declarations \
    -Werror -Isrc tests/test-spaced-theme.c src/bz-spaced-theme.c \
    $(pkg-config --cflags --libs gtk4 libadwaita-1) -o "$test_build/test-theme"
G_DEBUG=fatal-criticals "$test_build/test-theme"
