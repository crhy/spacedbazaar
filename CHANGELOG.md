# Changelog

## Unreleased

- The bundled runtime moved to current upstream releases: ostree `v2026.4` →
  `v2026.7` and polkit `127` → `128`. Both halves of every pinned source are
  now reviewed in `catalog/flatpak-pins.json`, and `scripts/check-flatpak-pins.py`
  prints a table and fails when a pin is half-moved, a new tag left with the
  old commit or the reverse, so a dependency update can no longer land halfway.
